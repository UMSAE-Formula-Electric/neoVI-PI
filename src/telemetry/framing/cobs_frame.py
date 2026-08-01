"""
telemetry.framing.cobs_frame — COBS framing with an inline CRC-16 trailer
and a trailing zero-byte delimiter (LINK-01).

**Deliberate correction of `01-RESEARCH.md` Pattern 7's sketch:** Pattern 7's
code example computes COBS over the payload alone and appends the CRC-16
*outside* the COBS envelope, after the encoded bytes. That ordering breaks
LINK-01's stated resync property. COBS's whole guarantee is that the only
`0x00` byte anywhere in its *encoded* output is a delimiter a receiver adds
itself — but a raw CRC-16 trailer can itself contain a `0x00` byte (it's an
arbitrary 16-bit value), and if that trailer sits outside the COBS envelope,
a delimiter-scanning receiver can split a single valid frame into two
fragments at a false delimiter hiding inside the CRC bytes. Putting the
CRC-16 trailer *inside* the COBS envelope — i.e. running COBS over
`payload + crc_bytes` as one unit — guarantees the only zero byte anywhere
in the framed stream is the real delimiter, which is exactly what
"resynchronizes at the next frame delimiter" requires.

Frame layout, `frame_bytes = frame(payload)`:

    cobs.encode(payload + pack_crc(crc16(payload)))  +  b"\\x00"
    \\_______________________ COBS envelope ________________/  \\_ delimiter _/

`unframe` is `frame`'s exact inverse, given the COBS-encoded segment with
the trailing delimiter already stripped (that stripping is
`telemetry.ground.deframe.Deframer.feed`'s job, since a byte-stream reader
must scan for delimiters across multiple `feed()` calls, not once per
frame).
"""

from cobs import cobs

from telemetry.framing.crc16 import crc16, pack_crc, verify_crc
from telemetry.framing.errors import CobsDecodeFailed, CrcMismatch

DELIMITER = b"\x00"
CRC_TRAILER_BYTES = 2


def frame(payload: bytes) -> bytes:
    """COBS-encode `payload + crc16(payload)` and append the delimiter."""
    trailer = pack_crc(crc16(payload))
    return cobs.encode(payload + trailer) + DELIMITER


def unframe(frame_bytes: bytes) -> bytes:
    """Inverse of `frame`, given the COBS-encoded segment (no trailing
    delimiter — the caller has already split on it). Raises
    `CobsDecodeFailed` (wrapping `cobs.cobs.DecodeError`, or a
    shorter-than-the-CRC-trailer decoded result) or `CrcMismatch`."""
    try:
        decoded = cobs.decode(frame_bytes)
    except cobs.DecodeError as exc:
        raise CobsDecodeFailed(f"COBS decode failed: {exc}") from exc

    if len(decoded) < CRC_TRAILER_BYTES:
        raise CobsDecodeFailed(
            f"COBS-decoded segment is {len(decoded)} byte(s), shorter than "
            f"the {CRC_TRAILER_BYTES}-byte CRC trailer it must contain"
        )

    payload, trailer = decoded[:-CRC_TRAILER_BYTES], decoded[-CRC_TRAILER_BYTES:]
    verify_crc(payload, trailer)  # raises CrcMismatch on mismatch
    return payload
