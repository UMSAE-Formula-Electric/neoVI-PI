"""
telemetry.archive.record — the archive's per-message payload layout.

Defined exactly once here and shared by the writer (this plan), the
recovery reader (01-05), and the replay source (01-12) so all three agree
on one on-disk shape rather than three independent encodings drifting apart.

`struct` format `"<IB"`, 5 bytes: `frame_id` as uint32, then a flags byte
whose bit 0 marks an extended ID. The CAN payload follows immediately and
its DLC is implied by the remaining buffer length — never stored
explicitly, since the archive already knows the total record length from
the MCAP message framing around it.

The archive stores raw frames, never CFR bytes (see this package's
`__init__.py`) — this is the raw-frame layout, structurally unrelated to
`telemetry.wire.encoder`'s CFR header.
"""

import struct

from telemetry.wire.frame_source import RawFrame

_HEADER_STRUCT = struct.Struct("<IB")
_FLAG_EXTENDED = 0x01


def pack_frame(frame: RawFrame) -> bytes:
    """Pack a `RawFrame` into the archive's on-disk record layout: 5-byte
    header (frame_id, flags) followed by the raw CAN payload."""
    flags = _FLAG_EXTENDED if frame.is_extended else 0
    return _HEADER_STRUCT.pack(frame.frame_id, flags) + frame.payload


def unpack_frame(data: bytes, log_time_ns: int) -> RawFrame:
    """Inverse of `pack_frame`. `log_time_ns` is the MCAP message's
    `log_time` (nanoseconds since epoch, as written by `ArchiveWriter`);
    it is converted back to `RawFrame.timestamp_us` here since the archive
    layout itself carries no timestamp field of its own — MCAP's own
    `log_time` is the single source of truth for when a record was
    captured."""
    header_size = _HEADER_STRUCT.size
    if len(data) < header_size:
        raise ValueError(
            f"archive record is {len(data)} byte(s), shorter than the "
            f"{header_size}-byte header"
        )

    frame_id, flags = _HEADER_STRUCT.unpack(data[:header_size])
    payload = data[header_size:]

    return RawFrame(
        timestamp_us=log_time_ns // 1000,
        frame_id=frame_id,
        is_extended=bool(flags & _FLAG_EXTENDED),
        payload=payload,
    )
