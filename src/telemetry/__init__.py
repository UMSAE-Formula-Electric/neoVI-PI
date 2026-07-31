"""
telemetry — the first brick of the whole-stack rebuild committed to in PROJECT.md.

This package replaces the existing same-machine, decode-on-car pipeline
(`src/new_logger.py`, `src/neoVI_logger.py`) with a layout that separates a
reusable car-side telemetry library (`telemetry.wire`) from Phase-0-only
offline analysis tooling (`telemetry.synth`, `telemetry.measure`). Phase 1
and Phase 2 build the real capture/archive/link stack into this package;
Phase 0 only lays the skeleton and proves the DBC ground truth it depends on.
"""
