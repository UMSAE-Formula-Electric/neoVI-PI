"""
telemetry.framing.crc16 — CRC-16/CCITT-FALSE over each framed batch (LINK-01).

No requirement mandates a specific CRC-16 variant — `01-CONTEXT.md` leaves
this to Claude's Discretion. CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)
is chosen as a widely-used, well-understood choice for byte-stream framing
with no project-specific reason to prefer an alternative.

`01-RESEARCH.md` Pattern 6 verified this session that `crccheck`'s
`Crc16CcittFalse.__name__` resolves to `"Crc16Ibm3740"` — the same
registered CRC-16 parameters under two names, not a different algorithm.
Callers should not be surprised by that name appearing in a repr/traceback.
"""

import struct

from crccheck.crc import Crc16CcittFalse

from telemetry.framing.errors import CrcMismatch

_CRC_STRUCT = struct.Struct("<H")


def crc16(data: bytes) -> int:
    """Compute the CRC-16/CCITT-FALSE checksum of `data`."""
    return Crc16CcittFalse.calc(data)


def pack_crc(value: int) -> bytes:
    """Pack a CRC-16 value as 2 little-endian bytes."""
    return _CRC_STRUCT.pack(value)


def verify_crc(payload: bytes, trailer: bytes) -> None:
    """Raise `CrcMismatch` naming both the computed and received values if
    `trailer` (2 little-endian bytes) does not match the CRC-16 computed
    over `payload`. Returns `None` on a match."""
    (received,) = _CRC_STRUCT.unpack(trailer)
    computed = crc16(payload)
    if computed != received:
        raise CrcMismatch(
            f"CRC mismatch: computed 0x{computed:04X}, received 0x{received:04X} "
            f"over a {len(payload)}-byte payload"
        )
