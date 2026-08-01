"""
telemetry.wire.batcher — batch container assembly and disassembly.

Header layout is `struct` format `"<BBQHB"`, 13 bytes: `protocol_version`,
`dict_version`, `base_timestamp_us`, `frame_count`, `batch_seq` — the same
four fields and the same 13-byte total `telemetry.wire.overhead`'s
`BATCH_HEADER_BYTES` already documents. The module-import-time assertion
below keeps the analytic overhead model and the real on-wire layout from
silently diverging.

**Per-record length prefix — a batch-layout cost this phase owns.** CFR
records are variable-length and their length is not derivable from the CFR
header alone (`telemetry.wire.encoder`'s header carries no length field), so
each record inside a batch is prefixed with one length byte. This costs
**one byte per frame beyond what Phase 0's D-06 overhead model assumed** —
that model (`telemetry.wire.overhead.BATCH_HEADER_BYTES` and friends)
predates this batching decision and does not include it. This is a
batch-layout choice this phase owns, not a change to the CFR byte layout
itself (D-05 is untouched — `telemetry.wire.encoder` is imported unchanged).
`01-04-SUMMARY.md` records the recomputed critical-subset bit rate this
extra byte produces, computed via `telemetry.wire.overhead`'s own functions
against the real twelve-message subset, not estimated.

`pack_batch`/`split_batch` raise `telemetry.framing.errors.BatchFormatError`
on any malformed input — truncation, a record that overruns the buffer, a
`frame_count` that disagrees with the number of records recovered, a record
longer than the one-byte length prefix can address (255 bytes), or more
records than the `frame_count` field (uint16) can address (65535).
"""

import struct
from typing import List, NamedTuple, Tuple

from telemetry.framing.errors import BatchFormatError
from telemetry.wire import overhead

PROTOCOL_VERSION = 1

BATCH_HEADER_STRUCT = struct.Struct("<BBQHB")

# Keep the real on-wire header size and the analytic overhead model's
# assumed header size from silently diverging (01-CRITICAL-CONSTRAINTS #4).
assert BATCH_HEADER_STRUCT.size == overhead.BATCH_HEADER_BYTES, (
    f"BATCH_HEADER_STRUCT.size={BATCH_HEADER_STRUCT.size} does not match "
    f"overhead.BATCH_HEADER_BYTES={overhead.BATCH_HEADER_BYTES} — the real "
    f"batch header layout and the analytic overhead model have diverged"
)

MAX_RECORD_BYTES = 255  # one-byte length prefix per record
MAX_BATCH_RECORDS = 0xFFFF  # frame_count is uint16


class BatchHeader(NamedTuple):
    """The 13-byte batch header's five fields, unpacked."""

    protocol_version: int
    dict_version: int
    base_timestamp_us: int
    frame_count: int
    batch_seq: int


def pack_batch(
    dict_version: int,
    base_timestamp_us: int,
    batch_seq: int,
    records: List[bytes],
) -> bytes:
    """Pack `records` (each a CFR-encoded frame's bytes) into one batch:
    a 13-byte header followed by each record as `len(record) + record`.

    Raises `BatchFormatError` if any record exceeds 255 bytes or the batch
    exceeds 65535 records.
    """
    if len(records) > MAX_BATCH_RECORDS:
        raise BatchFormatError(
            f"batch has {len(records)} records, exceeding the "
            f"{MAX_BATCH_RECORDS}-record limit (frame_count is uint16)"
        )

    body = bytearray()
    for i, record in enumerate(records):
        if len(record) > MAX_RECORD_BYTES:
            raise BatchFormatError(
                f"record {i} is {len(record)} byte(s), exceeding the "
                f"{MAX_RECORD_BYTES}-byte one-byte-length-prefix limit"
            )
        body.append(len(record))
        body.extend(record)

    header = BATCH_HEADER_STRUCT.pack(
        PROTOCOL_VERSION, dict_version, base_timestamp_us, len(records), batch_seq
    )
    return header + bytes(body)


def split_batch(payload: bytes) -> Tuple[BatchHeader, List[bytes]]:
    """Inverse of `pack_batch`. Raises `BatchFormatError` on truncation, a
    record length that overruns the buffer, or a `frame_count` that
    disagrees with the number of records actually recovered."""
    if len(payload) < BATCH_HEADER_STRUCT.size:
        raise BatchFormatError(
            f"payload is {len(payload)} byte(s), shorter than the "
            f"{BATCH_HEADER_STRUCT.size}-byte batch header"
        )

    fields = BATCH_HEADER_STRUCT.unpack(payload[: BATCH_HEADER_STRUCT.size])
    header = BatchHeader(*fields)
    body = payload[BATCH_HEADER_STRUCT.size :]

    records: List[bytes] = []
    offset = 0
    for i in range(header.frame_count):
        if offset >= len(body):
            raise BatchFormatError(
                f"batch truncated: header declares frame_count="
                f"{header.frame_count} but only {len(records)} record(s) "
                f"were recoverable before running out of bytes"
            )
        length = body[offset]
        offset += 1
        if offset + length > len(body):
            raise BatchFormatError(
                f"record {i} declares length {length} but only "
                f"{len(body) - offset} byte(s) remain in the buffer"
            )
        records.append(body[offset : offset + length])
        offset += length

    if offset != len(body):
        raise BatchFormatError(
            f"batch has {len(body) - offset} trailing byte(s) after "
            f"{header.frame_count} declared record(s)"
        )

    if len(records) != header.frame_count:
        raise BatchFormatError(
            f"recovered {len(records)} record(s) but header declares "
            f"frame_count={header.frame_count}"
        )

    return header, records
