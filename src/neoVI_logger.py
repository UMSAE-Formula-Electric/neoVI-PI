import vspyx
import argparse
import time
import can
import cantools
from typing import List,Tuple,Optional
from datetime import datetime
from pathlib import Path
import queue
import threading

TESTING_MODE = False
output_path = str(Path(__file__).parent.parent / "logs")
output_file = str(datetime.now().strftime("log_%Y-%m-%d_%H-%M-%S.vsb"))
hardware_sn = 'icsneo **1' # connects to the first available device
channel_name = 'HSCAN' # channel to log from
                       # CAN BUSSES
                       # neoVI
                       # DW CAN 01
                       # DW CAN 02

frame_queue = queue.Queue(maxsize=1000)
db = cantools.database.load_file("epbr2026_DBC_v1.0.dbc")
frame_count = 0


if(TESTING_MODE):
    print("Running in TESTING MODE: No hardware will be used.")
    hardware_sn = str(Path('./src/Vehicle Can.vsb').resolve()) # this is the path to the buffer file
    print(hardware_sn)

def ensure_output_path(out:str=output_path) -> str:
    out = out if out != None else output_path
    try:
        Path(out).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating output directory: {e}")
    return out + '/' + output_file

def init_neo_VI_logger() -> "vspyx.Core.Application":
    app = vspyx.Core.Application.New()
    app.Initialize(loadAllModules=True)
    return app

def list_discovery_channels(app, prefix=None):
    r = app.Resolver
    root = r.Root
    stack = [root]
    found = []
    while stack:
        obj = stack.pop()
        try:
            uri = obj.URITo()
        except Exception:
            uri = r.ShortestURITo(obj)
        if(uri.endswith("Discovery Channel") and (prefix is None or uri.startswith(prefix))):
            found.append(uri)
        for child in getattr(obj,"Children",[]):
            stack.append(child)
    for u in sorted(found):
        print(u) 


def attach_controllers(app:"vspyx.Core.Application",
                       hardware_sn:str,
                       channels: List[str],
                       listen_only:bool=True):
    device = app.VehicleSpy.AddSource(hardware_sn)
    if device is None or getattr(device, "Source", None) is None:
        raise RuntimeError(
            f"Could not activate hardware source '{hardware_sn}'. "
            f"Make sure you're passing a real hardware selector (e.g. 'icsneo **1') "
            f"and that the device is connected/visible on this machine."
        )

    list_discovery_channels(app,prefix=f"{device.Source.Identifier} ")

    attatched = []

    for ch_name in channels:
        print(ch_name)
        resolver_key = f"{device.Source.Identifier} {ch_name} Discovery Channel"

        channel = app.Resolver[resolver_key]
        assert isinstance(channel, vspyx.Communication.Channel)

        controller_name = f"logger_{ch_name}"
        controller,connector = channel.NewAttachedController(controller_name,listenOnly=listen_only)
        attatched.append((ch_name,controller,connector))
    return attatched

def main():
    p = argparse.ArgumentParser(description="neoVI Pi CAN -> VSB logger (vspyx).")
    p.add_argument("--sn", default="icsneo **1",
                   help="Hardware serial selector (Intrepid wildcard works, e.g. 'icsneo **1').")
    p.add_argument("--channels", nargs="+", required=True,
                   help="Vehicle Spy channel names to attach (e.g. DW CAN 01, DW CAN 02, neoVI).")
    p.add_argument("--out", required=False,
                   help="Output .vsb file path OR directory (directory => timestamped file is created).")
    p.add_argument("--listen-only", action="store_true",
                   help="Attach controllers with listenOnly=True.")
    p.add_argument("--duration", type=float, default=0.0,
                   help="Stop after N seconds (0 = run forever).")
    p.add_argument("--stats", action="store_true",
                   help="Print frames/sec every second.")
    args = p.parse_args()

    out_path = ensure_output_path(args.out)

    app = init_neo_VI_logger()
    print(f"Vehicle Spy X version: {app.Version}")

    # Make sure Frames module can write this buffer type, then open it
    if hasattr(app, "Frames") and hasattr(app.Frames, "CanWriteBuffer"):
        if not app.Frames.CanWriteBuffer(out_path):
            raise RuntimeError(f"Frames module reports it cannot write this buffer path: {out_path}")

    writable = app.Frames.OpenWritableBuffer(out_path) 
    print(f"Logging to: {out_path}")

    # Attach the hardware channels/controllers
    attach_controllers(app, args.sn, args.channels, args.listen_only)

    # Fast path: append each incoming frame directly into the writable buffer
    frame_count = 0
    last_stats_t = time.monotonic()

    lock = threading.Lock()

    def consumer_thread():
        while True:
            try:
                item = frame_queue.get(timeout=1.0)
                if item is None:
                    break
                
                frame,id,data,timestamp,channel = item
                decoded = db.decode_message(id,data)
                writable.Append(frame)
                for sig in decoded:
                    print(f"{id} - {sig}:{decoded[sig]:.2f}")
                print("---------------------------------------")
            except queue.Empty:
                continue
            except Exception as e:
                print(f" Consumer error : {e}")

    def on_point(point: "vspyx.Runtime.Point"):
        nonlocal frame_count, last_stats_t

        # We only care about link-layer PDUs (CAN, etc.)
        if not isinstance(point, vspyx.Communication.DataLinkPDUPoint):
            return

        channel = point.GetAttribute("ChannelName")
        c_in = False
        for c in args.channels:
            if c in channel:
                c_in = True

        if not c_in:
            return

        try:
            frame_queue.put_nowait((
                point.Frame,
                point.GetAttribute("ArbID"),
                point.GetAttribute("Payload"),
                point.GetAttribute("Timestamp"),
                point.GetAttribute("ChannelName"),))
        except frame_queue.Full:
            print("Queue Full")
        except Exception as e: 
            print(f"on_point q error")
# ------------------------------------------------------------------------------------
    consumer = threading.Thread(target=consumer_thread, daemon=True)
    consumer.start()

    observer = app.VehicleSpy.PrepareForStart(analysisMode=False)  
    observer.OnPoint.Add(on_point)                                 

    app.VehicleSpy.Start()                                         
    print("Online. Press Ctrl+C to stop.")

    start_t = time.monotonic()
    try:
        while True:
            time.sleep(0.25)
            if args.duration > 0 and (time.monotonic() - start_t) >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        # Best-effort stop/cleanup (API differs a bit across versions)
        frame_queue.put(None)
        consumer.join(timeout=3.0)
        if hasattr(app.VehicleSpy, "Stop"):
            try:
                writable
                app.VehicleSpy.Stop()
            except Exception:
                pass

        # Some builds expose app.Free() to shutdown modules cleanly
        if hasattr(app, "Free"):
            try:
                app.Free()
            except Exception:
                pass
            
        # try:
        #     if writable:
        #         writable.Close()
        # except Exception:
        #     pass
        
        

    print(f"Stopped. Wrote {frame_count} frames to {out_path}")


if __name__ == "__main__":
    main()
