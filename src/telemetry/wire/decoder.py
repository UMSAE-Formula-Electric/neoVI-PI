"""
telemetry.wire.decoder — the D-09 round-trip target, mirroring `encoder.py`.

Every synthetic frame this phase counts must decode back byte-identical
through this module (D-09) — "a byte count for an encoding nobody proved
reversible is not a measurement." Per-ID state (`_last_payload`) mirrors the
encoder's isolation: a decode failure or gap for one CAN ID never corrupts
another ID's state.

Unlike `src/new_logger.py::writer_thread`'s decode-failure convention (a bare
`except Exception: pass`, lines 244-247), this module raises a named
exception on any malformed input — RESEARCH.md's Security Domain and
Common Pitfalls sections explicitly call out that anti-pattern as
inapplicable here.
"""

import struct
from typing import Dict, Optional

from telemetry.wire.dictionary import IdDictionary
from telemetry.wire.encoder import (
    FLAG_EXTENDED_ID,
    FLAG_KEYFRAME,
    MAX_PAYLOAD_BYTES,
    EncoderOptions,
    cfr_header_format,
)
from telemetry.wire.frame_source import RawFrame


class DecodeError(Exception):
    """Raised on any malformed or under-length CFR buffer, or a delta record
    for an `id_index` with no stored previous payload. Never raised as a bare
    `struct.error` — callers get a message naming the offending value."""


class Decoder:
    """Decodes CFR bytes back into `RawFrame`s. Must be constructed with the
    same `EncoderOptions` instance the corresponding `Encoder` used — this is
    a caller contract, not something negotiated over the wire in Phase 0."""

    def __init__(self, dictionary: IdDictionary, options: Optional[EncoderOptions] = None):
        self.dictionary = dictionary
        self.options = options or EncoderOptions()
        self._header_struct = struct.Struct(cfr_header_format(self.options))
        self._last_payload: Dict[int, bytes] = {}

    def reset(self) -> None:
        """Clear all per-ID state (last decoded payload)."""
        self._last_payload.clear()

    def decode(self, cfr: bytes, batch_base_timestamp_us: int) -> RawFrame:
        header_size = self._header_struct.size
        if len(cfr) < header_size:
            raise DecodeError(
                f"buffer length {len(cfr)} is shorter than the "
                f"{header_size}-byte header for this decoder's options"
            )

        fields = list(self._header_struct.unpack(cfr[:header_size]))
        body = cfr[header_size:]

        flags = fields.pop(0)
        id_field = fields.pop(0)
        seq = fields.pop(0) if self.options.sequence_byte else None
        delta_t = fields.pop(0)
        trim_count = fields.pop(0)

        is_keyframe = bool(flags & FLAG_KEYFRAME)
        is_extended = bool(flags & FLAG_EXTENDED_ID)

        if self.options.use_dictionary:
            id_index = id_field
            frame_id, _ = self.dictionary.key_of(id_index)
        else:
            frame_id = id_field
            id_index = self.dictionary.index_of(frame_id, is_extended)

        implied_dlc = len(body) + trim_count
        if implied_dlc > MAX_PAYLOAD_BYTES:
            raise DecodeError(
                f"id_index={id_index} trim_count={trim_count} with body "
                f"length {len(body)} implies a DLC of {implied_dlc} bytes, "
                f"exceeding the {MAX_PAYLOAD_BYTES}-byte CAN maximum"
            )

        if is_keyframe:
            payload = body
        else:
            last_payload = self._last_payload.get(id_index)
            if last_payload is None:
                raise DecodeError(
                    f"delta record received for id_index={id_index} with no "
                    f"stored previous payload — cannot XOR-undo against an "
                    f"unknown baseline"
                )
            restored = body + b"\x00" * trim_count
            if len(restored) != len(last_payload):
                raise DecodeError(
                    f"id_index={id_index} reconstructed delta length "
                    f"{len(restored)} does not match stored payload length "
                    f"{len(last_payload)} — a DLC change must be encoded as "
                    f"a keyframe, never a delta"
                )
            payload = bytes(a ^ b for a, b in zip(restored, last_payload))

        self._last_payload[id_index] = payload

        return RawFrame(
            timestamp_us=batch_base_timestamp_us + delta_t,
            frame_id=frame_id,
            is_extended=is_extended,
            payload=payload,
        )
