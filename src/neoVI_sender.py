import vspyx
import time
import can
import argparse
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="neoVI CAN Bus Sender")
    parser.add_argument('--hardware_sn', type=str, default='icsneo **1', help='Hardware serial number or path to buffer file')
    parser.add_argument('--channels', type=str, default='HSCAN', help='Channel name to send messages on')
    args = parser.parse_args()

    hardware_sn = args.hardware_sn
    channel_name = args.channels

    app = vspyx.Core.Application.New()
    app.Initialize(loadAllModules=True)

    device = app.VehicleSpy.AddSource(hardware_sn)
    if device is None or getattr(device, "Source", None) is None:
        print(f"Failed to add source with hardware SN or path: {hardware_sn}")
        exit(1)
        
    channel = None
    for ch in device.Source.Channels:
        if ch.Name == channel_name:
            channel = ch
            break

    if channel is None:
        print(f"Channel {channel_name} not found on device {hardware_sn}")
        exit(1)

    channel.Start()

    bus = can.interface.Bus(bustype='vspyx', channel=channel.URITo())

    try:
        while True:
            msg = can.Message(arbitration_id=0x123, data=[0x11, 0x22, 0x33, 0x44], is_extended_id=False)
            bus.send(msg)
            print(f"Sent message: {msg}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping sender...")
    finally:
        channel.Stop()
        app.Shutdown()