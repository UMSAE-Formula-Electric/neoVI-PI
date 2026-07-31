"""
telemetry.wire — the car-side telemetry library.

This is the D-05 reusable core: ID dictionary, wire encoder/decoder, the
pluggable frame-source interface, and the analytic framing-overhead
calculation. Phase 1 imports this package for real CAN capture and Phase 4
hardens it for the ground-station link — nothing in this tier may depend on
anything Phase-0-only (`telemetry.synth`, `telemetry.measure`).
"""
