"""
telemetry.framing — COBS + CRC-16 byte-level framing for the telemetry link.

New this phase (01-04, the tracer): the first use of the `cobs`/`crccheck`
libraries anywhere in this codebase. `01-RESEARCH.md` Pattern 6 is the
verified reference for both libraries' exact behavior; `cobs_frame.py`
deliberately corrects Pattern 7's sketch by placing the CRC-16 trailer
*inside* the COBS envelope rather than outside it — see `cobs_frame.py`'s
module docstring for why.

Nothing in this package depends on `telemetry.wire`, `telemetry.archive`, or
`telemetry.capture` — framing is a content-agnostic byte transform that sits
below the CFR encoder, matching `01-RESEARCH.md`'s architectural map.
"""
