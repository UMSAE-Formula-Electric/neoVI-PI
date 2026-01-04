import vspyx,argparse,time
from typing import List,Tuple,Optional

TESTING_MODE = False

def on_point(point):
  if not isinstance(point, vspyx.Communication.ISignalPoint):
      return

  print(f"[{point.Timestamp}] {point.GetAttribute("ShortName")}" +
        f" = {point.PhysicalValue} {point.UnitString}{'' if point.Valid else ' -- Warning: Invalid'}")

def decode(database: str,
            buffer_path: str,
            controller_network_name_to_channel: List[Tuple[str, str]],
            signal_ids: Optional[List[str]]=None):
    app = vspyx.Core.Application.New()
    app.Initialize(loadAllModules=True)

    app.VehicleSpy.AddDatabase(database)
    buffer = app.VehicleSpy.AddSource(buffer_path)
    buffer.Source.Loop = False # Set to true if we want to loop the buffer
    
    print(controller_network_name_to_channel)
    
    for controller_network_name, channel_id in controller_network_name_to_channel:
        controller = \
            app.Resolver[f"{buffer.Source.Identifier} {controller_network_name} Controller"]
        channel = app.Resolver[channel_id]
        assert isinstance(controller, vspyx.Communication.Controller)
        assert isinstance(channel, vspyx.Communication.Channel)
        app.Communication.ConnectControllerToChannel(controller, channel)

    observer = app.VehicleSpy.PrepareForStart(analysisMode=TESTING_MODE)
    
    if signal_ids is not None:
        for signal_id in signal_ids:
            signal = app.Resolver[signal_id]
            assert isinstance(signal, vspyx.Communication.ISignal)
            trace = observer.GetTrace(signal)
            trace.OnPoint.Add(on_point)
    else:
        observer.OnPoint.Add(on_point)

    app.VehicleSpy.Start()
    app.VehicleSpy.StartLogging("umsae_log.vspylog")
    app.VehicleSpy.Schedule.Wait(buffer.Source.BufferEndEvent)
    app.VehicleSpy.StopLogging()
    app.VehicleSpy.Stop()


if(__name__ == "__main__"):
    parser = argparse.ArgumentParser(description='Decode signals using Vehicle Spy X')
    parser.add_argument('database', type=str, help='Path to database')
    parser.add_argument('buffer', type=str, help='Path to buffer')
    parser.add_argument('--mapping', nargs=2, action='append',
        metavar=('"Buffer Network Name"', '"Channel Name"'), help='Connector to channel mapping')
    parser.add_argument('--signal', metavar=('"Signal Name"'), action='append', help='Signal to view')

    args = parser.parse_args()
    decode(args.database, args.buffer, args.mapping, args.signal)