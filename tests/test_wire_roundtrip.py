"""
D-09 round-trip assertions for the Phase 0 tracer slice: every synthetic
frame for the traced CAN ID must decode back byte-identical through
`telemetry.wire.decoder.Decoder`. A byte count for an encoding nobody proved
reversible is not a measurement (GATE-01's transparency prohibition) — this
suite is the enforcement mechanism.

Task 2 extends this with the hardening assertions from 00-02-PLAN.md's
`<behavior>` block: malformed input must raise a named exception naming the
offending value (never a bare `struct.error` or a silently wrong byte
count), and all four D-10 `EncoderOptions` ablation modes must round-trip
byte-identical over both a standard-ID and an extended-ID subject before any
of them is trusted to produce a reported bytes/frame number.
"""

import pytest

from telemetry.synth.generator import SyntheticFrameSource
from telemetry.wire.decoder import Decoder, DecodeError
from telemetry.wire.dictionary import UnknownFrameId, build_id_dictionary
from telemetry.wire.encoder import (
    CFR_HEADER_STRUCT,
    FLAG_EXTENDED_ID,
    FLAG_KEYFRAME,
    BatchWindowExceeded,
    Encoder,
    EncoderOptions,
    PayloadTooLong,
)
from telemetry.wire.frame_source import RawFrame

TRACED_MESSAGE = "M192_Command_Message"  # standard-ID subject (frame_id 0xC0)
EXTENDED_MESSAGE = "INV_Diag_Buffer"  # extended-ID subject (frame_id 0xAA5)

ABLATION_MODES = [
    pytest.param(EncoderOptions(), id="full"),
    pytest.param(EncoderOptions(sequence_byte=False), id="sequence_byte=False"),
    pytest.param(EncoderOptions(payload_delta=False), id="payload_delta=False"),
    pytest.param(EncoderOptions(use_dictionary=False), id="use_dictionary=False"),
]

ROUNDTRIP_SUBJECTS = [
    pytest.param(TRACED_MESSAGE, id="standard_id"),
    pytest.param(EXTENDED_MESSAGE, id="extended_id"),
]


@pytest.fixture(scope="module")
def dictionary(dbc):
    """`IdDictionary` built once per test module from the session-scoped `dbc`
    fixture (`tests/conftest.py`)."""
    return build_id_dictionary(dbc)


def test_cfr_header_struct_shape():
    """The default (full-options) header is exactly 6 bytes, format `<BBBHB`,
    per `.planning/research/ARCHITECTURE.md` Pattern 3."""
    assert CFR_HEADER_STRUCT.size == 6
    assert CFR_HEADER_STRUCT.format == "<BBBHB"


def test_traced_message_roundtrip_byte_identical(dbc, dictionary, gate_config):
    """Every synthetic frame for M192_Command_Message decodes back
    byte-identical, and at least one emitted CFR is shorter than the 6-byte
    header plus 8 payload bytes — proving the delta path actually compresses
    rather than always emitting keyframes."""
    source = SyntheticFrameSource(
        dbc,
        dictionary,
        gate_config,
        "typical",
        duration_s=5.0,
        only_message_names=[TRACED_MESSAGE],
    )
    enc = Encoder(dictionary)
    dec = Decoder(dictionary)

    frames = list(source.frames())
    assert frames, "synthetic source produced no frames for the traced message"

    shortest_cfr_len = None
    for frame in frames:
        # Each frame is its own batch base here (delta_t_us == 0) — this test
        # exercises the dictionary/keyframe/delta/sequence mechanics of a
        # single encode+decode round trip, not the CLI's batching window
        # (report.py::measure_stream owns that policy separately).
        batch_base_timestamp_us = frame.timestamp_us
        cfr = enc.encode(frame, batch_base_timestamp_us)
        recovered = dec.decode(cfr, batch_base_timestamp_us)

        assert recovered == frame

        if shortest_cfr_len is None or len(cfr) < shortest_cfr_len:
            shortest_cfr_len = len(cfr)

    assert shortest_cfr_len < CFR_HEADER_STRUCT.size + 8


@pytest.mark.parametrize("options", ABLATION_MODES)
@pytest.mark.parametrize("message_name", ROUNDTRIP_SUBJECTS)
def test_ablation_roundtrip_byte_identical(
    dbc, dictionary, gate_config, message_name, options
):
    """Every one of the four D-10 ablation modes round-trips byte-identical,
    for both a standard-ID and an extended-ID subject. GATE-01's
    transparency prohibition means an ablation's bytes/frame number is only
    meaningful if the encoding that produced it was proven reversible over
    the same frames that were counted."""
    source = SyntheticFrameSource(
        dbc,
        dictionary,
        gate_config,
        "typical",
        duration_s=2.0,
        only_message_names=[message_name],
    )
    enc = Encoder(dictionary, options)
    dec = Decoder(dictionary, options)

    frames = list(source.frames())
    assert frames, f"synthetic source produced no frames for {message_name}"

    for frame in frames:
        batch_base_timestamp_us = frame.timestamp_us
        cfr = enc.encode(frame, batch_base_timestamp_us)
        recovered = dec.decode(cfr, batch_base_timestamp_us)
        assert recovered == frame


def test_extended_id_flag_set_and_roundtrips(dbc, dictionary):
    """An extended-ID message sets FLAG_EXTENDED_ID in byte 0 and round-trips
    with `is_extended` True."""
    message = dbc.get_message_by_name(EXTENDED_MESSAGE)
    assert message.is_extended_frame, (
        f"fixture assumption broken: {EXTENDED_MESSAGE} is expected to be "
        f"extended-ID but the DBC says otherwise"
    )

    frame = RawFrame(
        timestamp_us=0,
        frame_id=message.frame_id,
        is_extended=True,
        payload=bytes(range(message.length)),
    )
    enc = Encoder(dictionary)
    dec = Decoder(dictionary)

    cfr = enc.encode(frame, 0)
    assert cfr[0] & FLAG_EXTENDED_ID

    recovered = dec.decode(cfr, 0)
    assert recovered == frame
    assert recovered.is_extended is True


def test_payload_too_long_raises(dbc, dictionary):
    """Encoding a frame whose payload exceeds 8 bytes raises `PayloadTooLong`
    naming the frame_id and the actual length; it never truncates."""
    message = dbc.get_message_by_name(TRACED_MESSAGE)
    enc = Encoder(dictionary)
    bad_frame = RawFrame(
        timestamp_us=0,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=bytes(9),
    )
    with pytest.raises(PayloadTooLong, match=r"length 9"):
        enc.encode(bad_frame, 0)


def test_batch_window_exceeded_raises(dbc, dictionary):
    """Encoding a frame whose timestamp_us is below the batch base, or more
    than 65535 microseconds above it, raises `BatchWindowExceeded` naming
    both values."""
    message = dbc.get_message_by_name(TRACED_MESSAGE)
    enc = Encoder(dictionary)
    payload = bytes(range(message.length))

    below_base = RawFrame(
        timestamp_us=-1,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=payload,
    )
    with pytest.raises(BatchWindowExceeded, match=r"timestamp_us=-1.*batch_base_timestamp_us=0"):
        enc.encode(below_base, 0)

    above_window = RawFrame(
        timestamp_us=70000,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=payload,
    )
    with pytest.raises(
        BatchWindowExceeded, match=r"timestamp_us=70000.*batch_base_timestamp_us=0"
    ):
        enc.encode(above_window, 0)


def test_unknown_frame_id_raises(dictionary):
    """Encoding a frame whose (frame_id, is_extended) pair is absent from the
    dictionary raises `UnknownFrameId`."""
    known_ids = {fid for fid, _ in dictionary.index}
    unknown_id = max(known_ids) + 1000

    enc = Encoder(dictionary)
    unknown_frame = RawFrame(
        timestamp_us=0, frame_id=unknown_id, is_extended=False, payload=bytes(8)
    )
    with pytest.raises(UnknownFrameId, match=rf"frame_id=0x{unknown_id:X}"):
        enc.encode(unknown_frame, 0)


def test_decode_buffer_too_short_raises(dictionary):
    """Decoding a buffer shorter than the configured header size raises
    `DecodeError` rather than raising `struct.error`."""
    dec = Decoder(dictionary)
    with pytest.raises(DecodeError, match=r"shorter than"):
        dec.decode(b"\x00\x00\x00", 0)


def test_decode_delta_with_no_previous_payload_raises(dbc, dictionary):
    """Decoding a delta record for an id_index with no stored previous
    payload raises `DecodeError` naming the id_index — it never silently
    treats the delta as a keyframe."""
    message = dbc.get_message_by_name(TRACED_MESSAGE)
    id_index = dictionary.index_of(message.frame_id, message.is_extended_frame)

    # flags=0 -> FLAG_KEYFRAME not set, so this parses as a delta record
    # against an id_index no Decoder instance has ever seen a payload for.
    header = CFR_HEADER_STRUCT.pack(0, id_index, 0, 0, 0)

    dec = Decoder(dictionary)
    with pytest.raises(DecodeError, match=rf"id_index={id_index}\b"):
        dec.decode(header, 0)


def test_decode_trim_count_implies_dlc_above_8_raises(dbc, dictionary):
    """Decoding a record whose trim_count implies a DLC above 8 raises
    `DecodeError`."""
    message = dbc.get_message_by_name(TRACED_MESSAGE)
    id_index = dictionary.index_of(message.frame_id, message.is_extended_frame)

    # body is 0 bytes; trim_count=9 implies a reconstructed DLC of 9, over
    # the 8-byte CAN maximum.
    header = CFR_HEADER_STRUCT.pack(FLAG_KEYFRAME, id_index, 0, 0, 9)

    dec = Decoder(dictionary)
    with pytest.raises(DecodeError, match=r"exceeding"):
        dec.decode(header, 0)


def test_dlc_change_forces_keyframe_and_roundtrips(dbc, dictionary):
    """A frame whose DLC differs from the previous frame of the same ID is
    encoded as a keyframe, and round-trips."""
    message = dbc.get_message_by_name(TRACED_MESSAGE)
    enc = Encoder(dictionary)
    dec = Decoder(dictionary)

    frame1 = RawFrame(
        timestamp_us=0,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=bytes(range(1, 9)),  # 8 bytes
    )
    frame2 = RawFrame(
        timestamp_us=100,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=bytes(range(1, 4)),  # 3 bytes — DLC changed
    )

    cfr1 = enc.encode(frame1, 0)
    cfr2 = enc.encode(frame2, 0)

    assert cfr2[0] & FLAG_KEYFRAME, "a DLC change must force a keyframe, never a delta"

    recovered1 = dec.decode(cfr1, 0)
    recovered2 = dec.decode(cfr2, 0)

    assert recovered1 == frame1
    assert recovered2 == frame2


def test_identical_payload_produces_header_size_delta(dbc, dictionary):
    """Two frames of the same ID with identical payloads produce a delta
    record of exactly the header size (all-zero XOR fully trimmed)."""
    message = dbc.get_message_by_name(TRACED_MESSAGE)
    enc = Encoder(dictionary)
    payload = bytes(range(1, 1 + message.length))

    frame1 = RawFrame(0, message.frame_id, message.is_extended_frame, payload)
    frame2 = RawFrame(50, message.frame_id, message.is_extended_frame, payload)

    enc.encode(frame1, 0)
    cfr2 = enc.encode(frame2, 0)

    assert len(cfr2) == CFR_HEADER_STRUCT.size


def test_sequence_byte_wraps_at_256(dbc, dictionary):
    """The per-ID sequence byte increments independently per CAN ID and
    wraps from 255 to 0."""
    message = dbc.get_message_by_name(TRACED_MESSAGE)
    enc = Encoder(dictionary)
    payload = bytes(range(message.length))

    seqs = []
    for i in range(257):
        frame = RawFrame(i, message.frame_id, message.is_extended_frame, payload)
        cfr = enc.encode(frame, 0)
        seqs.append(cfr[2])  # byte 2 is `seq` under default (full) options

    assert seqs[0] == 0
    assert seqs[255] == 255
    assert seqs[256] == 0, "sequence byte must wrap from 255 back to 0"


def test_sequence_byte_independent_per_id(dbc, dictionary):
    """Two different CAN IDs advance their per-ID sequence counters
    independently."""
    standard = dbc.get_message_by_name(TRACED_MESSAGE)
    extended = dbc.get_message_by_name(EXTENDED_MESSAGE)
    enc = Encoder(dictionary)
    standard_payload = bytes(range(standard.length))
    extended_payload = bytes(range(extended.length))

    standard_seqs = []
    extended_seqs = []
    for i in range(3):
        f_standard = RawFrame(i, standard.frame_id, standard.is_extended_frame, standard_payload)
        standard_seqs.append(enc.encode(f_standard, 0)[2])

        f_extended = RawFrame(i, extended.frame_id, extended.is_extended_frame, extended_payload)
        extended_seqs.append(enc.encode(f_extended, 0)[2])

    assert standard_seqs == [0, 1, 2]
    assert extended_seqs == [0, 1, 2]
