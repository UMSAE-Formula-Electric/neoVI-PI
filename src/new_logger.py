"""
neoVI Pi CAN logger — python-ics edition
No Vehicle Spy X license required.

Output: timestamped CSV  (timestamp_s, arb_id_hex, network_id, dlc, data_hex, decoded)

Architecture:
  capture_thread  — polls ics.get_messages() as fast as possible, pushes raw
                    tuples onto a queue. Zero decoding, zero I/O here.
  writer_thread   — drains the queue, decodes with cantools, writes CSV rows.
  main thread     — handles timing, stats, and shutdown signalling.
"""

import ics
import random as rn
import cantools
import argparse
import time
import csv
import signal
import queue
import threading
#import curse_display
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_OUTPUT_DIR = str(Path(__file__).parent.parent / "logs")
DBC_FILE = "epbr2026_DBC_v1.0.dbc"
DEBUGGING = True

# How many raw frame tuples the queue can hold before capture_thread blocks.
# 50k frames at ~100 bytes each ≈ 5 MB — fine for a Pi.
QUEUE_MAXSIZE = 50_000

# Network-name → ics.NETID_* mapping for common neoVI Pi channels.
CHANNEL_MAP: dict[str, int] = {
    "HSCAN":     ics.NETID_HSCAN,
    "MSCAN":     ics.NETID_MSCAN,
    "SWCAN":     ics.NETID_SWCAN,
    "HSCAN2":    ics.NETID_HSCAN2,
    "HSCAN3":    ics.NETID_HSCAN3,
    "DW CAN 01": ics.NETID_HSCAN,
    "DW CAN 02": ics.NETID_HSCAN2,
    "neoVI":     ics.NETID_HSCAN,
}

# Sentinel pushed onto the queue to tell writer_thread to exit cleanly.
_STOP = object()

db = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_output_path(out_dir: str | None) -> str:
    out_dir = out_dir or DEFAULT_OUTPUT_DIR
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("log_%Y-%m-%d_%H-%M-%S.csv")
    return str(Path(out_dir) / filename)


def open_device(serial: str | None) -> "ics.NeoDevice":
    devices = ics.find_devices()
    if not devices:
        raise RuntimeError("No Intrepid devices found. Is the hardware connected?")

    device = None
    tx_device = None
    if serial:
        for d in devices:
            if str(d.SerialNumber) == serial or serial.lower() in str(d).lower():
                device = d
                break
        if device is None:
            raise RuntimeError(
                f"No device matching serial '{serial}' found. "
                f"Available: {[str(d) for d in devices]}"
            )
    else:
        device = devices[0]

    ics.open_device(device)
    print(f"Opened: {device}  (serial {device.SerialNumber})")
    return device


def resolve_net_ids(channel_names: list[str]) -> set[int]:
    net_ids = set()
    for name in channel_names:
        if name in CHANNEL_MAP:
            net_ids.add(CHANNEL_MAP[name])
        else:
            attr = f"NETID_{name.upper().replace(' ', '_')}"
            if hasattr(ics, attr):
                net_ids.add(getattr(ics, attr))
            else:
                print(f"[WARN] Unknown channel '{name}' — will not filter by network ID.")
    return net_ids

def build_dbc_index(db) -> dict[int, object] | None:
    """Flat arb_id → cantools Message lookup. Faster than db.decode_message()."""
    if db is None:
        return None
    return {msg.frame_id: msg for msg in db.messages}

# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------
    

def transmit_can(device,id,dlc,fps,stop_event,max=255):
    while not stop_event.is_set():
        msg = ics.SpyMessage()
        msg.ArbIDOrHeader = id  # CAN Arbitration ID
        msg.NumberBytesData = 1
        msg.Data = tuple(rn.randint(0,max) for _ in range(dlc))  # Data Bytes go here
        msg.NetworkID = ics.NETID_HSCAN # First channel of CAN on the device
        # msg parameter here can also be a tuple of messages
        ics.transmit_messages(device, msg)
        print(f"Tx: {msg.ArbIDOrHeader} - {msg.Data}")
        time.sleep(fps)

def capture_thread(
    device,
    net_ids: set[int],
    raw_queue: queue.Queue,
    stop_event: threading.Event,
    poll_s: float,
    hw_errors: list[int],   # shared mutable counter [total_errors]
):
    """
    Polls ics.get_messages() and pushes raw tuples onto raw_queue.
    Does NO decoding, NO formatting, NO file I/O — kept as thin as possible.

    Tuple layout: (timestamp, arb_id, network_id, dlc, data_bytes)
    """
    while not stop_event.is_set():
        time.sleep(poll_s)

        try:
            msgs, error_count = ics.get_messages(device)
        except Exception as e:
            print(f"[capture] get_messages error: {e}")
            stop_event.set()
            break

        if error_count:
            hw_errors[0] += error_count

        for m in msgs:
            if net_ids and m.NetworkID not in net_ids:
                continue
            # Extract everything from the C object here, before releasing GIL.
            # bytes() copies the data out of the SpyMessage buffer immediately.
            
            raw_queue.put((
                m.TimeSystem,
                m.ArbIDOrHeader,
                m.NetworkID,
                m.NumberBytesData,
                bytes(m.Data[:m.NumberBytesData]),
            ))

    # Signal the writer that capture is done.
    raw_queue.put(_STOP)


def writer_thread(
    raw_queue: queue.Queue,
    out_path: str,
    dbc_index: dict | None,
    verbose: bool,
    frame_counter: list[int],   # shared mutable counter [total_frames]
):
    """
    Drains raw_queue, decodes each frame, and writes CSV rows.
    All slow work (string formatting, DBC decode, file I/O) lives here.
    """
    with open(out_path, "w", newline="", buffering=131072) as csvfile:  # 128 KB buffer
        writer = csv.writer(csvfile)
        writer.writerow(["timestamp_s", "arb_id", "network_id", "dlc", "data_hex", "decoded"])

        while True:
            try:
                item = raw_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is _STOP:
                break

            ts, arb_id, net_id, dlc, data = item
            # DBC decode
            decoded = ""
            # print(f"{arb_id} - {data}")
            if dbc_index is not None:
                msg_def = dbc_index.get(arb_id)
                if msg_def is not None:
                    try:
                        decoded = msg_def.decode(data)
                    except Exception:
                        pass

            hex_data = data.hex(" ").upper()
            # print(decoded)
            # name = db.get_message_by_frame_id(arb_id)
            print("-----------------------------------")
            for sig in decoded:
                print(f"{arb_id} - {sig}:{decoded[sig]}")

            writer.writerow([
                f"{ts:.6f}",
                f"0x{arb_id:08X}",
                net_id,
                dlc,
                hex_data,
                decoded,
            ])

            if verbose:
                print(f"{ts:.3f}  [{net_id:3d}]  0x{arb_id:08X}  {hex_data}"
                      + (f"  →  {decoded}" if decoded else ""))

            frame_counter[0] += 1

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="neoVI Pi CAN -> CSV logger (python-ics, threaded).")
    p.add_argument("--serial", default=None,
                   help="Device serial number (omit = first found).")
    p.add_argument("--channels", nargs="+", required=True,
                   help="Channel names, e.g. HSCAN HSCAN2 'DW CAN 01'.")
    p.add_argument("--out", default=None,
                   help="Output directory (timestamped .csv created inside).")
    p.add_argument("--duration", type=float, default=0.0,
                   help="Stop after N seconds (0 = run until Ctrl+C).")
    p.add_argument("--stats", action="store_true",
                   help="Print frame count every second.")
    p.add_argument("--verbose", action="store_true",
                   help="Print every decoded frame to stdout (slow on busy bus).")
    p.add_argument("--dbc", default=DBC_FILE,
                   help="Path to .dbc file for decoding.")
    p.add_argument("--poll-ms", type=float, default=10.0,
                   help="Capture poll interval in milliseconds (default: 10).")
    args = p.parse_args()

    # Load DBC
    # db = None
    try:
        db = cantools.database.load_file(args.dbc)
        print(f"Loaded DBC: {args.dbc}  ({len(db.messages)} messages)")
    except Exception as e:
        print(f"[WARN] Could not load DBC '{args.dbc}': {e}. Decoding disabled.")

    dbc_index = build_dbc_index(db)
    out_path  = ensure_output_path(args.out)
    net_ids   = resolve_net_ids(args.channels)
    device    = open_device(args.serial)

    print(f"Channels : {args.channels}  →  net_ids={net_ids}")
    print(f"Poll     : {args.poll_ms} ms")
    print(f"Output   : {out_path}")

    # Shared state (lists so threads can mutate without nonlocal)
    frame_counter = [0]
    hw_errors     = [0]

    raw_queue  = queue.Queue(maxsize=QUEUE_MAXSIZE)
    stop_event = threading.Event()

    # Wire up signal handlers before starting threads
    def _stop(*_):
        stop_event.set()
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Start threads
    t_capture = threading.Thread(
        target=capture_thread,
        args=(device, net_ids, raw_queue, stop_event, args.poll_ms / 1000.0, hw_errors),
        name="capture",
        daemon=True,
    )
    t_writer = threading.Thread(
        target=writer_thread,
        args=(raw_queue, out_path, dbc_index, args.verbose, frame_counter),
        name="writer",
        daemon=False,   # non-daemon so it finishes flushing before process exits
    )
    t_transmitter = threading.Thread(
        target=transmit_can,
        args=(device,0x0A5,8,1,stop_event),
        name="transmitter",
        daemon=False, 
    )
    t2_transmitter = threading.Thread(
        target=transmit_can,
        args=(device,0xA7,8,1,stop_event),
        name="transmitter",
        daemon=False, 
    )
    t3_transmitter = threading.Thread(
        target=transmit_can,
        args=(device,0xA6,8,1,stop_event),
        name="transmitter",
        daemon=False, 
    )
    t4_transmitter = threading.Thread(
        target=transmit_can,
        args=(device,0x105,8,1,stop_event),
        name="transmitter",
        daemon=False, 
    )
    t5_transmitter = threading.Thread(
        target=transmit_can,
        args=(device,0x16,1,0.5,stop_event,4),
        name="transmitter",
        daemon=False, 
    )
    
    t_capture.start()
    t_writer.start()
    t_transmitter.start()
    t2_transmitter.start()
    t3_transmitter.start()
    t4_transmitter.start()
    t5_transmitter.start()
    
    # calibrate angle sensor
    # msg = ics.SpyMessage() 
    # msg.ArbIDOrHeader = 0x7C0  # CAN Arbitration ID
    # msg.NumberBytesData = 8
    # msg.Data = tuple([0x5,0x00,0x00,0x00,0x00,0x00,0x00,0x00])  # Data Bytes go here
    # msg.NetworkID = ics.NETID_HSCAN2 # First channel of CAN on the device
    # # msg parameter here can also be a tuple of messages
    # ics.transmit_messages(device, msg)
    # print(f"Tx: {msg.ArbIDOrHeader} - {msg.Data}")
    
    # set angle to 0
    # msg = ics.SpyMessage()
    # msg.ArbIDOrHeader = 0x7C0  # CAN Arbitration ID
    # msg.NumberBytesData = 8
    # msg.Data = tuple([0x3,0x00,0x00,0x00,0x00,0x00,0x00,0x00])  # Data Bytes go here
    # msg.NetworkID = ics.NETID_HSCAN2 # First channel of CAN on the device
    # # msg parameter here can also be a tuple of messages
    # ics.transmit_messages(device, msg)
    # print(f"Tx: {msg.ArbIDOrHeader} - {msg.Data}")
    
    print("Online. Press Ctrl+C to stop.")

    # Main thread: stats + duration watchdog only
    start_t      = time.monotonic()
    last_stats_t = start_t

    while not stop_event.is_set():
        time.sleep(0.25)

        if args.stats:
            now = time.monotonic()
            if now - last_stats_t >= 1.0:
                qsize = raw_queue.qsize()
                print(f"[stats] {frame_counter[0]} frames  |  queue: {qsize}  |  hw errors: {hw_errors[0]}")
                if qsize > QUEUE_MAXSIZE * 0.8:
                    print("[WARN] Queue >80% full — writer can't keep up. Consider --poll-ms 25.")
                last_stats_t = now

        if args.duration > 0 and (time.monotonic() - start_t) >= args.duration:
            stop_event.set()

    # Capture thread sees stop_event and pushes _STOP onto the queue.
    # Wait for it to do that, then wait for writer to drain and close the file.
    t_capture.join(timeout=5)
    t_writer.join(timeout=30)
    t_transmitter.join(timeout=50)
    t2_transmitter.join(timeout=50)
    t3_transmitter.join(timeout=50)
    t4_transmitter.join(timeout=50)
    t5_transmitter.join(timeout=50)
    
    
    
    try:
        ics.close_device(device)
    except Exception:
        pass

    print(f"\nStopped. Wrote {frame_counter[0]} frames to {out_path}")
    if hw_errors[0]:
        print(f"[WARN] Total hardware errors reported: {hw_errors[0]}")


if __name__ == "__main__":
    main()
