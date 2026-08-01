"""
telemetry.archive — the durable, crash-safe MCAP archive (ARCH-01..05).

New this phase (01-04, the tracer): the first use of `mcap` anywhere in this
codebase. `01-RESEARCH.md` Pattern 2 (writer, verified crash-recovery
mechanics) and Pattern 3 (`.done` marker write ordering) are the
authoritative, empirically-verified references `writer.py` and `session.py`
build directly on — see each module's docstring for what was measured, not
assumed.

The archive stores raw frames (`archive/record.py`'s layout), never CFR
bytes: CFR carries per-ID delta state that is fragile to loss across a
crash and is a wire format, not an archive of record.
"""
