"""
telemetry.link.loopback — the in-process, zero-OS-dependency `Link`
implementation (LINK-04), built directly on `01-RESEARCH.md` Pattern 7's
verified reference.

Exists so the full chain — capture, archive, encode, batch, frame, link,
deframe, decode — can run and be tested with no radio, no vehicle hardware,
and no network stack at all. `01-08` adds `UdpLink` for a real network hop,
and (01-08 deviation, see that plan's SUMMARY) gives `close()` a real
closed-state contract here too — `01-04`'s original `close()` was a no-op,
but `01-08`'s shared test suite requires `send` after `close` to raise
across *both* `Link` implementations (LINK-03: one suite, no divergence
between implementations), so this can no longer be silent.
"""

import queue
from typing import Optional


class LoopbackLink:
    """Wraps a `queue.Queue`. `recv` returns `None` on timeout rather than
    raising — the same "no data yet" signal every `Link` implementation
    gives its caller. `close()` is idempotent; `send` after `close` raises
    `RuntimeError` rather than silently queuing into a link nothing will
    ever drain again."""

    def __init__(self) -> None:
        self._q: "queue.Queue[bytes]" = queue.Queue()
        self._closed = False

    def send(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("cannot send on a closed LoopbackLink")
        self._q.put(data)

    def recv(self, timeout: Optional[float] = None) -> Optional[bytes]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._closed = True
