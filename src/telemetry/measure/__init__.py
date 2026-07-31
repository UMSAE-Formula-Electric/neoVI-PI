"""
telemetry.measure — Phase-0-only offline analysis tooling.

Aggregates encoder output into the compression-ratio gate's report: bytes
per frame, per-ID and ablation breakdowns, and sliding-window peak bit rate.
Consumes `telemetry.wire` and `telemetry.synth` but is never imported by
either — nothing outside Phase 0 imports this package.
"""
