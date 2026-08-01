"""
telemetry.ground — the headless ground-station consumer (GND-01):
deframe -> CFR decode -> DBC decode -> print/record. `deframe.py` (this
plan) is the byte-stream-to-`RawFrame` half; the CLI entry point and DBC
decode wiring are `01-11`'s scope.
"""
