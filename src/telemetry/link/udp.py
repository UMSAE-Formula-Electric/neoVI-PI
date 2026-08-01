"""
telemetry.link.udp — `UdpLink`, the real-network-hop `Link` implementation
(LINK-03), built directly on `01-RESEARCH.md` Pattern 7's verified
reference and satisfying the exact same `Link` Protocol as `LoopbackLink`
(`telemetry.link.base.Link`) — three methods, nothing more, so the layers
above never need to know which transport is underneath.

UDP's own inherent, unordered packet loss is treated as a feature here, not
a defect to work around: it models the real RFD900x radio link's lossy
behavior more faithfully than TCP would (`.planning/research/ARCHITECTURE.md`
Pattern 4). Phase 1 sends one datagram per batch and does not coalesce —
`01-RESEARCH.md` Pattern 6 computed, using this repository's own
`telemetry.wire.overhead` module, that every Phase-1-plausible batch size
sits well under the practical Ethernet/Wi-Fi UDP payload ceiling (~1,472
bytes), so fragmentation is not a concern at this phase's sizes and no
special handling is added on speculation.

`recv_bufsize` must be sized generously above the largest configured batch,
never tightly. Its behavior on an undersized buffer is platform-dependent,
verified directly this session (01-08), not assumed from documentation:

- **POSIX (the deployment target — Linux/CM4):** `socket.recvfrom(bufsize)`
  silently truncates a datagram larger than `bufsize`, with **no error
  raised**. `recv()` returns the truncated bytes; they simply fail CRC (or
  COBS decode) once fed to `telemetry.ground.deframe.Deframer`, and are
  discarded and counted like any other corruption (LINK-02).
- **Winsock (the dev box — `01-CONTEXT.md`'s Windows dev interpreter
  decision):** `recvfrom` instead *raises* `WSAEMSGSIZE`
  (`errno.EMSGSIZE`, WinError 10040) and the oversized datagram's bytes are
  unrecoverable through the standard socket API — there is no truncated
  payload to hand back. `recv()` catches this specific error and returns
  `None`, exactly like a timeout, so the caller's loop never sees an
  unhandled exception on either platform.

Either way, an undersized buffer never threatens correctness — worst case
the datagram is lost entirely (Windows) or arrives corrupt-and-counted
(Linux) — but it *does* inflate the corrupt-batch counters (Linux) or the
apparent loss rate (Windows) with events that were never actual link
corruption, which would mislead the loss/saturation diagnostics Phase 5
builds on top of those counters. `config/logger.json`'s shipped
`link.udp.recv_bufsize` (8192) is deliberately generous relative to any
Phase-1-plausible batch, not tuned tight.
"""

import errno
import socket
from typing import Optional, Tuple

Address = Tuple[str, int]


class UdpLink:
    """A `Link` over one bound UDP datagram socket. `send` writes exactly
    one datagram per call — no coalescing. `recv` sets the socket timeout
    per call and returns the received bytes, or `None` on timeout (the
    socket timeout exception is caught here so it never escapes to the
    caller — `None` on timeout is the `Link` Protocol's contract and every
    caller is written against it). `close` closes the socket and is safe to
    call more than once."""

    def __init__(
        self,
        local_addr: Address,
        remote_addr: Optional[Address] = None,
        recv_bufsize: int = 8192,
    ) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(local_addr)
        self._remote_addr = remote_addr
        self._bufsize = recv_bufsize
        self._closed = False

    @property
    def local_addr(self) -> Address:
        """The socket's actual bound `(host, port)` — reads back the real
        ephemeral port the OS assigned when constructed with port `0`, so a
        caller (or a test wiring two `UdpLink`s together) can discover the
        real port without hardcoding one, and so the ground station can log
        the port it is actually listening on."""
        return self._sock.getsockname()

    def send(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("cannot send on a closed UdpLink")
        if self._remote_addr is None:
            raise RuntimeError(
                "UdpLink has no remote_addr configured — cannot send with "
                "nowhere to send to"
            )
        self._sock.sendto(data, self._remote_addr)

    def recv(self, timeout: Optional[float] = None) -> Optional[bytes]:
        self._sock.settimeout(timeout)
        try:
            data, _ = self._sock.recvfrom(self._bufsize)
            return data
        except socket.timeout:
            return None
        except OSError as exc:
            # Verified this session (01-08, dev box is Windows per
            # PROJECT.md's Python-environment decision — the deployment
            # target is Linux/CM4): Winsock's `recvfrom` does NOT silently
            # truncate an oversized datagram the way POSIX does. It raises
            # `WSAEMSGSIZE` (`errno.EMSGSIZE`, WinError 10040) instead, and
            # the oversized datagram's bytes are unrecoverable through the
            # standard socket API — there is no truncated payload to hand
            # back. Treat this exactly like a timeout (`None`, "nothing
            # usable arrived this call") rather than letting it propagate
            # and crash the caller's loop — LINK-02's discard-and-count
            # spirit applies here too: an oversized datagram must never be
            # able to take down the consumer, on any platform. On Linux,
            # this branch is simply never taken; `recvfrom` there returns
            # the POSIX-truncated bytes through the `return data` path
            # above, and `Deframer` counts the truncation as a normal CRC
            # failure once it fails to find a valid frame.
            if exc.errno == errno.EMSGSIZE:
                return None
            raise

    def close(self) -> None:
        if not self._closed:
            self._sock.close()
            self._closed = True
