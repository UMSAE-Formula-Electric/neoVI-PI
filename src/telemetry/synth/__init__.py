"""
telemetry.synth — Phase-0-only offline analysis tooling.

Generates synthetic CAN traffic from `epbr2026_DBC_v1.0.dbc` (entropy
brackets, per-message rate assignment) so the compression-ratio gate can be
measured before any real captured log exists in this repository (D-01).
Nothing outside Phase 0 imports this package.
"""
