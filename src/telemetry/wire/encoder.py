"""
telemetry.wire.encoder — the D-05 byte-producing core.

Implements the Compressed Frame Record (CFR) layout exactly as specified in
`.planning/research/ARCHITECTURE.md` Pattern 3 (quoted in this phase's
00-RESEARCH.md § "Architecture Patterns" Pattern 3) — this is the real,
reusable encoder core Phase 1 imports for capture and Phase 4 hardens for
the ground-station link (D-05), so any convenience deviation from that
layout becomes debt baked into what those phases build on (RESEARCH.md
Pitfall 5). Do not re-derive the byte layout here.

CFR layout (default `EncoderOptions`, header struct `"<BBBHB"`, 6 bytes):

    byte 0:      flags        bit0 = FLAG_KEYFRAME, bit1 = FLAG_EXTENDED_ID
    byte 1:      id_index     index into the static IdDictionary
    byte 2:      seq          per-CAN-ID sequence, wraps at 256
    bytes 3-4:   delta_t_us   uint16 LE, microseconds since batch base timestamp
    byte 5:      trim_count   trailing zero bytes elided from the XOR delta
    bytes 6..N:  payload      keyframe: full DLC bytes; delta: trimmed XOR

`EncoderOptions`' four ablation switches reshape the header (see
`cfr_header_format`) but never the fixed field *order* — flags, id, seq,
delta_t_us, trim_count, payload.

Per-ID state (`_last_payload`, `_next_seq`) is isolated per `id_index`
(ARCHITECTURE.md Anti-Pattern 1) — never a single running stream-compression
state — so a discontinuity in one CAN ID's traffic never corrupts another's
decode.
"""

import struct
from dataclasses import dataclass
from typing import Dict, Optional

from telemetry.wire.dictionary import IdDictionary
from telemetry.wire.frame_source import RawFrame

FLAG_KEYFRAME = 0x01
FLAG_EXTENDED_ID = 0x02

MAX_PAYLOAD_BYTES = 8
MAX_DELTA_T_US = 0xFFFF  # uint16


class CfrError(Exception):
    """Base exception for all CFR encode/decode failures."""


class BatchWindowExceeded(CfrError):
    """Raised when a frame's timestamp falls outside the batch's representable
    delta-t window (before the batch base, or more than 65535 us after it)."""


class PayloadTooLong(CfrError):
    """Raised when a frame's payload exceeds the 8-byte CAN DLC maximum."""


@dataclass(frozen=True)
class EncoderOptions:
    """The four D-10 ablation switches. Both `Encoder` and `Decoder` must be
    constructed with the *same* options instance — a mismatch between the two
    ends is a caller error, not something negotiated over the wire (that
    negotiation is Phase 4 scope, per `dict_version`'s own docstring)."""

    payload_delta: bool = True
    use_dictionary: bool = True
    sequence_byte: bool = True
    trim_trailing_zeros: bool = True


def cfr_header_format(options: EncoderOptions) -> str:
    """Build the `struct` format string for this options combination. Field
    order is always flags, id, [seq], delta_t_us, trim_count — only whether
    the id field is a 1-byte dictionary index or a 4-byte raw frame_id, and
    whether the seq byte is present at all, varies."""
    parts = ["<", "B"]  # flags
    parts.append("B" if options.use_dictionary else "I")  # id_index or raw frame_id
    if options.sequence_byte:
        parts.append("B")
    parts.append("H")  # delta_t_us
    parts.append("B")  # trim_count
    return "".join(parts)


# The default (full) options header — `"<BBBHB"`, 6 bytes. Referenced by
# tests and the interface contract; ablation modes build their own format
# string internally via `cfr_header_format` and do not share this instance.
CFR_HEADER_STRUCT = struct.Struct(cfr_header_format(EncoderOptions()))


class Encoder:
    """Encodes `RawFrame`s into CFR bytes, one instance per stream. Per-ID
    state means a fresh `Encoder`/`Decoder` pair must be used per independent
    stream (or `reset()` called), matching `.reset()`'s contract."""

    def __init__(self, dictionary: IdDictionary, options: Optional[EncoderOptions] = None):
        self.dictionary = dictionary
        self.options = options or EncoderOptions()
        self._header_struct = struct.Struct(cfr_header_format(self.options))
        self._last_payload: Dict[int, bytes] = {}
        self._next_seq: Dict[int, int] = {}

    def reset(self) -> None:
        """Clear all per-ID state (last payload, next sequence number)."""
        self._last_payload.clear()
        self._next_seq.clear()

    def encode(self, frame: RawFrame, batch_base_timestamp_us: int) -> bytes:
        payload = frame.payload
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise PayloadTooLong(
                f"frame_id=0x{frame.frame_id:X} payload length {len(payload)} "
                f"exceeds the {MAX_PAYLOAD_BYTES}-byte CAN DLC maximum"
            )

        delta_t = frame.timestamp_us - batch_base_timestamp_us
        if delta_t < 0 or delta_t > MAX_DELTA_T_US:
            raise BatchWindowExceeded(
                f"timestamp_us={frame.timestamp_us} is outside the batch window "
                f"for batch_base_timestamp_us={batch_base_timestamp_us} "
                f"(delta={delta_t}, allowed range [0, {MAX_DELTA_T_US}])"
            )

        # index_of() raises UnknownFrameId — always validated, even when
        # use_dictionary=False, since per-ID state is always keyed on
        # id_index and an unrecognized frame must never silently encode.
        id_index = self.dictionary.index_of(frame.frame_id, frame.is_extended)

        last_payload = self._last_payload.get(id_index)
        dlc_changed = last_payload is not None and len(last_payload) != len(payload)
        is_keyframe = (
            not self.options.payload_delta
            or last_payload is None
            or dlc_changed
        )

        flags = FLAG_KEYFRAME if is_keyframe else 0
        if frame.is_extended:
            flags |= FLAG_EXTENDED_ID

        if is_keyframe:
            body = payload
            trim_count = 0
        else:
            xor_delta = bytes(a ^ b for a, b in zip(payload, last_payload))
            if self.options.trim_trailing_zeros:
                trimmed = xor_delta.rstrip(b"\x00")
                trim_count = len(xor_delta) - len(trimmed)
                body = trimmed
            else:
                body = xor_delta
                trim_count = 0

        seq = self._next_seq.get(id_index, 0)

        header_fields = [flags]
        header_fields.append(id_index if self.options.use_dictionary else frame.frame_id)
        if self.options.sequence_byte:
            header_fields.append(seq)
        header_fields.append(delta_t)
        header_fields.append(trim_count)

        if len(header_fields) != len(self._header_struct.format.lstrip("<")):
            raise CfrError(
                f"header field count {len(header_fields)} does not match "
                f"struct format {self._header_struct.format!r} for this "
                f"encoder's options — refusing to pack a malformed header"
            )

        header = self._header_struct.pack(*header_fields)
        cfr = header + body

        self._last_payload[id_index] = payload
        if self.options.sequence_byte:
            self._next_seq[id_index] = (seq + 1) % 256

        return cfr
