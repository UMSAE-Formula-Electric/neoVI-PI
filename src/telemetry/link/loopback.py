"""
telemetry.link.loopback — the in-process, zero-OS-dependency `Link`
implementation (LINK-04), built directly on `01-RESEARCH.md` Pattern 7's
verified reference.

Exists so the full chain — capture, archive, encode, batch, frame, link,
deframe, decode — can run and be tested with no radio, no vehicle hardware,
and no network stack at all. `01-08` adds `UdpLink` for a real network hop.
"""

import queue
from typing import Optional


class LoopbackLink:
    """Wraps a `queue.Queue`. `recv` returns `None` on timeout rather than
    raising — the same "no data yet" signal every `Link` implementation
    gives its caller."""

    def __init__(self) -> None:
        self._q: "queue.Queue[bytes]" = queue.Queue()

    def send(self, data: bytes) -> None:
        self._q.put(data)

    def recv(self, timeout: Optional[float] = None) -> Optional[bytes]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        pass
