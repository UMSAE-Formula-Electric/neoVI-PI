"""
telemetry.link — the swappable transport abstraction (LINK-03).

`base.Link` is the only seam any transport implementation has to satisfy;
no layer above it changes when the transport does. `01-04` (the tracer)
ships `LoopbackLink`; `01-08` adds `UdpLink`; a serial implementation waits
for Phase 9. Mirrors `telemetry.wire.frame_source.FrameSource`'s minimal
`typing.Protocol` style — no asyncio, per `01-CONTEXT.md`'s locked decision.
"""
