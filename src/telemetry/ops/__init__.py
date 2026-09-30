"""
telemetry.ops -- Phase 3's unattended-on-car-operation surface
(OPS-01/02/03/07): the heartbeat status file writer/reader
(`heartbeat.py`) and the separate `telemetry-status` reader process
(`cli.py`).

This package observes the existing logger process (`telemetry.logger.cli`)
and its Phase 1 counter dataclasses -- it never re-derives or re-counts
anything those already own, and it never modifies the capture, archive, or
telemetry data paths themselves (`03-CONTEXT.md`'s phase boundary). Disk
monitoring (`03-02`), the hardware-wait retry loop and terminal states
(`03-03`), and the LED indicator seam (`03-04`) each add their own module
here on top of the heartbeat seam this plan (03-01) establishes.
"""
