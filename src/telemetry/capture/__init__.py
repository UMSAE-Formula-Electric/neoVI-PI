"""
telemetry.capture — the architectural centre of Phase 1: one capture fan-out
feeding two independent consumers with divergent overflow policies
(CAP-01..06).

`fanout.FanOut` (this plan) is the whole mechanism. A real hardware source
(`01-07`) and a real-log replay source (deferred Phase 0 re-check condition)
both feed the same `FanOut.submit` call — this package owns none of the
capture-source logic itself, only the divergence point.
"""
