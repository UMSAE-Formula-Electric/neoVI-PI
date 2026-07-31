"""
D-09 round-trip assertions for the Phase 0 tracer slice: every synthetic
frame for the traced CAN ID must decode back byte-identical through
`telemetry.wire.decoder.Decoder`. A byte count for an encoding nobody proved
reversible is not a measurement (GATE-01's transparency prohibition) — this
suite is the enforcement mechanism.
"""

import pytest

from telemetry.synth.generator import SyntheticFrameSource
from telemetry.wire.decoder import Decoder
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import CFR_HEADER_STRUCT, Encoder

TRACED_MESSAGE = "M192_Command_Message"


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


def test_traced_message_roundtrip_byte_identical(dbc, dictionary):
    """Every synthetic frame for M192_Command_Message decodes back
    byte-identical, and at least one emitted CFR is shorter than the 6-byte
    header plus 8 payload bytes — proving the delta path actually compresses
    rather than always emitting keyframes."""
    source = SyntheticFrameSource(
        dbc, dictionary, seed=42, duration_s=5.0, only_message_names=[TRACED_MESSAGE]
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
