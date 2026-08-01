"""
telemetry.link.base — the `Link` transport Protocol (LINK-03).

Minimal surface, same style as `telemetry.wire.frame_source.FrameSource`:
exactly the three methods `01-CONTEXT.md` locked. `LoopbackLink` (this
plan), `UdpLink` (01-08), and a future serial implementation (Phase 9) each
satisfy this contract with no change required anywhere above it.
"""

from typing import Optional, Protocol


class Link(Protocol):
    """A synchronous, swappable byte-pipe transport. The transport owns its
    own thread (if it needs one) — no asyncio, per `01-CONTEXT.md`."""

    def send(self, data: bytes) -> None: ...

    def recv(self, timeout: Optional[float] = None) -> Optional[bytes]: ...

    def close(self) -> None: ...
