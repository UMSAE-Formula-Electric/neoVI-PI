"""
Requirements covered: LINK-01, LINK-02.

Proves framing's two hard claims under damage, not just that clean input
round-trips:

1. LINK-01 — a corrupted byte stream resynchronizes at the next frame
   delimiter. This is only true because the CRC-16 trailer lives *inside*
   the COBS envelope (the tracer's correction to `01-RESEARCH.md` Pattern
   7's sketch) — a raw CRC-16 value can itself contain a `0x00` byte, and
   if that byte sat outside the COBS envelope it could be mistaken for the
   real delimiter, splitting one valid frame into two fragments.
2. LINK-02 — every CRC, COBS, and batch-format failure is discarded and
   counted on its own counter, and nothing decoded from a damaged batch is
   ever yielded upstream.

Uses the session-scoped `dbc` fixture and a real `IdDictionary` so every
batch under test carries real CFR records encoded from real DBC-valid
frames — never invented bytes.

Corruption cases that require searching for a qualifying byte offset are
built from a seeded `random.Random` (SEED below) so a failure is
reproducible; the seed and offset are folded into the assertion message on
failure.
"""

import random

import pytest
from cobs import cobs

from telemetry.framing.cobs_frame import CRC_TRAILER_BYTES, DELIMITER
from telemetry.framing.cobs_frame import frame as cobs_frame
from telemetry.framing.cobs_frame import unframe
from telemetry.framing.crc16 import crc16, pack_crc
from telemetry.framing.errors import BatchFormatError, CobsDecodeFailed, CrcMismatch
from telemetry.ground.deframe import Deframer
from telemetry.logger.config import LoggerConfig, load_logger_config
from telemetry.wire import overhead
from telemetry.wire.batcher import (
    BATCH_HEADER_STRUCT,
    MAX_BATCH_RECORDS,
    PROTOCOL_VERSION,
    pack_batch,
    split_batch,
)
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import Encoder
from telemetry.wire.frame_source import RawFrame

# One fixed, checked-in seed for every deterministic-but-searched corruption
# case in this file — reproducible by construction, per this task's own
# action text ("Build the corruption cases deterministically from a seeded
# random.Random so a failure is reproducible").
SEED = 20260801

# The subject message this file carries end to end, matching the 01-04
# tracer's choice: on the config allowlist, single-signal, simple enough to
# assert an exact known-value round trip against.
SUBJECT_MESSAGE = "M195_Pedal_Press_Percent"
SUBJECT_SIGNAL_VALUES = {"Pedal_Press_Percent": 42}

# Read directly from the checked-in logger config, not copied as a literal
# — "the configured batch size" in this task's behavior text means
# whatever config/logger.json actually says, so a config tune can never
# silently stop meaning what this test's name says it means.
_LOGGER_CONFIG = load_logger_config(LoggerConfig.default_path())
CONFIGURED_BATCH_FRAMES = _LOGGER_CONFIG.telemetry.batch_frames


@pytest.fixture
def dictionary(dbc, logger_config):
    return build_id_dictionary(dbc, logger_config.dbc_path)


def _subject_records(dictionary, db, count, base_timestamp_us=0):
    """Encode `count` real CFR records for the subject message via a real
    `Encoder`, each on a strictly increasing per-record timestamp offset so
    the batch's delta_t_us stays representable even at the header's
    frame_count ceiling (`MAX_BATCH_RECORDS`, a uint16)."""
    message = db.get_message_by_name(SUBJECT_MESSAGE)
    payload = message.encode(SUBJECT_SIGNAL_VALUES)
    encoder = Encoder(dictionary)
    records = []
    for i in range(count):
        raw = RawFrame(
            timestamp_us=base_timestamp_us + i,
            frame_id=message.frame_id,
            is_extended=message.is_extended_frame,
            payload=payload,
        )
        records.append(encoder.encode(raw, base_timestamp_us))
    return records


def _build_batch(dictionary, db, count, batch_seq=0, base_timestamp_us=0):
    """Real CFR records, packed into one real batch payload (13-byte header
    + length-prefixed records) — the same construction `telemetry.logger`
    and `test_end_to_end.py` use, never invented bytes."""
    records = _subject_records(dictionary, db, count, base_timestamp_us)
    payload = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=base_timestamp_us,
        batch_seq=batch_seq,
        records=records,
    )
    return payload, records


def _classify(segment: bytes) -> str:
    """What `unframe` does with a COBS-encoded (delimiter-stripped)
    `segment`: `'cobs'` if it raises `CobsDecodeFailed`, `'crc'` if it
    raises `CrcMismatch`, `'ok'` if it decodes and verifies cleanly."""
    try:
        unframe(segment)
    except CobsDecodeFailed:
        return "cobs"
    except CrcMismatch:
        return "crc"
    return "ok"


def _find_flip(rng: random.Random, encoded: bytes, want: str, max_attempts: int = 500):
    """Search deterministically (seeded `rng`) for a single-byte XOR flip of
    `encoded` whose `_classify` outcome is `want`. Never produces a `0x00`
    byte in the result — a flip that happens to XOR to zero would inject a
    spurious delimiter and split one corrupt segment into two, which is a
    different (separately tested) failure mode."""
    for _ in range(max_attempts):
        idx = rng.randrange(len(encoded))
        xor_value = rng.randrange(1, 256)
        corrupted = bytearray(encoded)
        corrupted[idx] ^= xor_value
        if corrupted[idx] == 0:
            continue
        if _classify(bytes(corrupted)) == want:
            return idx, bytes(corrupted)
    raise AssertionError(
        f"seed={SEED}: exhausted {max_attempts} attempts searching for a "
        f"'{want}' corruption of a {len(encoded)}-byte segment"
    )


# ---------------------------------------------------------------------------
# LINK-01: round trip, zero-byte delimiter safety, and the overhead model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record_count",
    [1, CONFIGURED_BATCH_FRAMES, MAX_BATCH_RECORDS],
    ids=["one", "configured", "max"],
)
def test_round_trip_at_one_configured_and_maximum_batch_size(dictionary, dbc, record_count):
    payload, records = _build_batch(dictionary, dbc, record_count)
    framed = cobs_frame(payload)

    unframed = unframe(framed[: -len(DELIMITER)])
    assert unframed == payload

    header, recovered = split_batch(unframed)
    assert header.frame_count == record_count
    assert recovered == records


def test_framed_output_has_exactly_one_zero_byte_the_trailing_delimiter(dictionary, dbc):
    payload, _records = _build_batch(dictionary, dbc, 50)
    assert 0 in payload, (
        "fixture assumption: a realistic 50-record batch is expected to "
        "contain at least one zero byte in its CFR records (e.g. a "
        "non-extended delta record's flags byte) — this is exactly the "
        "case the delimiter-safety property below must hold against"
    )

    framed = cobs_frame(payload)
    zero_positions = [i for i, b in enumerate(framed) if b == 0]
    assert zero_positions == [len(framed) - 1]


def test_regression_crc_containing_a_zero_byte_does_not_split_the_frame(dictionary, dbc):
    """Deliberate regression guard for the tracer's correction to
    `01-RESEARCH.md` Pattern 7: the CRC-16 trailer lives *inside* the COBS
    envelope specifically because a raw CRC-16 value can itself contain a
    `0x00` byte. Search exhaustively (not randomly — `batch_seq` is a
    one-byte field, so all 256 values is a bounded, deterministic sweep) for
    a real batch whose CRC-16, packed little-endian, contains a zero byte,
    then assert the framed output still has exactly one `0x00` byte — the
    trailing delimiter — and that the round trip still holds."""
    _template_payload, records = _build_batch(dictionary, dbc, 1)

    found = None
    for batch_seq in range(256):
        payload = pack_batch(
            dict_version=dictionary.dict_version,
            base_timestamp_us=0,
            batch_seq=batch_seq,
            records=records,
        )
        trailer = pack_crc(crc16(payload))
        if 0 in trailer:
            found = (batch_seq, payload, trailer)
            break

    assert found is not None, (
        "expected at least one batch_seq in 0..255 to produce a CRC-16 "
        "trailer containing a zero byte — if this ever fails, the CRC "
        "algorithm or batch header changed and this regression case needs "
        "a new search axis"
    )
    batch_seq, payload, trailer = found

    framed = cobs_frame(payload)
    zero_positions = [i for i, b in enumerate(framed) if b == 0]
    assert zero_positions == [len(framed) - 1], (
        f"batch_seq={batch_seq} trailer={trailer.hex()} contains a zero "
        f"byte, but framed output has zero byte(s) at {zero_positions}, "
        f"not just the trailing delimiter — this is exactly the regression "
        f"the tracer's CRC-inside-COBS correction prevents"
    )

    unframed = unframe(framed[: -len(DELIMITER)])
    assert unframed == payload


def test_framed_size_matches_overhead_model_within_length_prefix_and_delimiter(dictionary, dbc):
    """`telemetry.wire.overhead`'s D-06 model predates this phase's batcher,
    which adds one length-prefix byte per record (`01-04-SUMMARY.md`'s
    documented, measured correction) and a trailing delimiter byte outside
    the COBS envelope the model never accounted for. Feed the
    length-prefix-adjusted size through the model's own worst-case formula
    — its `cobs_worst_case_overhead` is a true upper bound, achieved only by
    zero-byte-free data, so real framed output (which always carries some
    zero bytes from real CFR records) must never exceed it."""
    for record_count in (1, 10, 100, 1000):
        payload, records = _build_batch(dictionary, dbc, record_count)
        clean_payload_bytes = sum(len(r) for r in records)
        framed = cobs_frame(payload)

        adjusted_clean = clean_payload_bytes + record_count  # +1/record length prefix
        predicted_upper = overhead.all_in_bytes_per_batch(adjusted_clean) + len(DELIMITER)

        assert len(framed) <= predicted_upper, (
            f"record_count={record_count}: framed size {len(framed)} "
            f"exceeds the overhead model's worst-case prediction "
            f"{predicted_upper} — assert against overhead.py's own "
            f"functions, this is not a copied number"
        )

        # COBS never removes bytes, so the framed size can never be smaller
        # than the un-COBS'd length plus the one mandatory code byte plus
        # the delimiter.
        floor = len(payload) + CRC_TRAILER_BYTES + 1 + len(DELIMITER)
        assert len(framed) >= floor


# ---------------------------------------------------------------------------
# LINK-02: corruption discrimination — each damage class, its own error
# ---------------------------------------------------------------------------


def test_flipping_the_crc_trailer_itself_raises_crc_mismatch_not_cobs_error(dictionary, dbc):
    """Corrupting only the CRC-16 trailer bytes (not the COBS structure)
    leaves COBS decoding intact and fails CRC verification specifically."""
    payload, _records = _build_batch(dictionary, dbc, 5)
    real_trailer = pack_crc(crc16(payload))

    corrupted_trailer = bytearray(real_trailer)
    corrupted_trailer[0] ^= 0xFF
    if corrupted_trailer[0] == real_trailer[0]:
        corrupted_trailer[0] ^= 0x01
    assert bytes(corrupted_trailer) != real_trailer

    segment = cobs.encode(payload + bytes(corrupted_trailer))
    with pytest.raises(CrcMismatch):
        unframe(segment)


def test_corrupting_the_cobs_length_chain_raises_cobs_decode_failed(dictionary, dbc):
    payload, _records = _build_batch(dictionary, dbc, 5)
    to_cobs = payload + pack_crc(crc16(payload))
    encoded = cobs.encode(to_cobs)

    rng = random.Random(SEED)
    idx, corrupted = _find_flip(rng, encoded, "cobs")

    raised = None
    try:
        unframe(corrupted)
    except CobsDecodeFailed:
        raised = CobsDecodeFailed
    except Exception as exc:  # pragma: no cover - failure path only
        raised = type(exc)
    assert raised is CobsDecodeFailed, f"seed={SEED} offset={idx}: expected CobsDecodeFailed, got {raised!r}"


def test_truncated_mid_record_raises_batch_format_error(dictionary, dbc):
    """Truncating the batch payload itself (before framing) mid-record,
    then framing the truncated payload fresh — `frame()` computes a
    correct, internally-consistent CRC over whatever bytes it's given, so
    COBS decode and CRC verification both succeed, and only `split_batch`'s
    own structural check can fail."""
    payload, _records = _build_batch(dictionary, dbc, 5)
    truncated_payload = payload[:-1]

    framed = cobs_frame(truncated_payload)
    unframed = unframe(framed[: -len(DELIMITER)])
    assert unframed == truncated_payload  # sanity: COBS + CRC both succeeded

    with pytest.raises(BatchFormatError):
        split_batch(unframed)


def test_frame_count_disagreeing_with_records_present_raises_batch_format_error(dictionary, dbc):
    payload, records = _build_batch(dictionary, dbc, 5)
    header_size = BATCH_HEADER_STRUCT.size
    body = payload[header_size:]

    bad_header = BATCH_HEADER_STRUCT.pack(
        PROTOCOL_VERSION, dictionary.dict_version, 0, len(records) + 1, 0
    )
    bad_payload = bad_header + body

    framed = cobs_frame(bad_payload)
    unframed = unframe(framed[: -len(DELIMITER)])
    assert unframed == bad_payload  # sanity: COBS + CRC both succeeded

    with pytest.raises(BatchFormatError):
        split_batch(unframed)


def _corrupt_cobs_segment(dictionary, dbc):
    payload, _records = _build_batch(dictionary, dbc, 5)
    to_cobs = payload + pack_crc(crc16(payload))
    encoded = cobs.encode(to_cobs)
    rng = random.Random(SEED)
    _idx, corrupted = _find_flip(rng, encoded, "cobs")
    return corrupted


def _corrupt_crc_segment(dictionary, dbc):
    payload, _records = _build_batch(dictionary, dbc, 5)
    real_trailer = pack_crc(crc16(payload))
    bad_trailer = bytearray(real_trailer)
    bad_trailer[0] ^= 0xFF
    if bad_trailer[0] == real_trailer[0]:
        bad_trailer[0] ^= 0x01
    return cobs.encode(payload + bytes(bad_trailer))


def _corrupt_batch_format_segment(dictionary, dbc):
    payload, _records = _build_batch(dictionary, dbc, 5)
    truncated = payload[:-1]
    trailer = pack_crc(crc16(truncated))
    return cobs.encode(truncated + trailer)


@pytest.mark.parametrize(
    "build_segment, expected_counter",
    [
        (_corrupt_cobs_segment, "cobs_failures"),
        (_corrupt_crc_segment, "crc_failures"),
        (_corrupt_batch_format_segment, "batch_format_failures"),
    ],
    ids=["cobs", "crc", "batch_format"],
)
def test_deframer_discards_and_counts_each_damage_class_yields_nothing(
    dictionary, dbc, build_segment, expected_counter
):
    segment = build_segment(dictionary, dbc)
    deframer = Deframer(dictionary)

    recovered = list(deframer.feed(segment + DELIMITER))

    assert recovered == []
    counters = deframer.counters
    for name in ("cobs_failures", "crc_failures", "batch_format_failures"):
        expected = 1 if name == expected_counter else 0
        assert getattr(counters, name) == expected, (
            f"{expected_counter} case: expected only {expected_counter}==1, "
            f"got counters={counters!r}"
        )
    assert counters.batches_ok == 0
    assert counters.records_decoded == 0


# ---------------------------------------------------------------------------
# LINK-01's actual claim: resync after corruption
# ---------------------------------------------------------------------------


def _build_three_batches(dictionary, db, per_batch=3):
    """Three real, continuous batches from one shared `Encoder` — batch_seq
    0/1/2, non-overlapping timestamp windows so each batch's delta_t_us
    stays representable."""
    message = db.get_message_by_name(SUBJECT_MESSAGE)
    payload_bytes = message.encode(SUBJECT_SIGNAL_VALUES)
    encoder = Encoder(dictionary)

    batches = []
    for batch_seq in range(3):
        base_ts = batch_seq * per_batch
        records = []
        for i in range(per_batch):
            raw = RawFrame(
                timestamp_us=base_ts + i,
                frame_id=message.frame_id,
                is_extended=message.is_extended_frame,
                payload=payload_bytes,
            )
            records.append(encoder.encode(raw, base_ts))
        batch_payload = pack_batch(
            dict_version=dictionary.dict_version,
            base_timestamp_us=base_ts,
            batch_seq=batch_seq,
            records=records,
        )
        batches.append((batch_payload, records, base_ts))
    return batches, message, payload_bytes


def _corrupted_three_batch_stream(dictionary, db, per_batch=3):
    """`frame_a` + a structurally-corrupted `frame_b` + `frame_c`, all real
    batches from one continuous encoder stream. Returns the concatenated
    byte stream plus enough context to assert the surviving content."""
    batches, message, payload_bytes = _build_three_batches(dictionary, db, per_batch)
    (payload_a, records_a, base_a), (payload_b, _records_b, _base_b), (payload_c, records_c, base_c) = batches

    frame_a = cobs_frame(payload_a)
    frame_c = cobs_frame(payload_c)

    to_cobs_b = payload_b + pack_crc(crc16(payload_b))
    encoded_b = cobs.encode(to_cobs_b)
    rng = random.Random(SEED)
    idx, corrupted_b = _find_flip(rng, encoded_b, "cobs")
    frame_b_corrupt = corrupted_b + DELIMITER

    stream = frame_a + frame_b_corrupt + frame_c
    return stream, message, payload_bytes, records_a, base_a, records_c, base_c, idx


def _assert_resync_result(recovered, message, payload_bytes, records_a, base_a, records_c, base_c):
    assert len(recovered) == 2, f"seed={SEED}: expected 2 surviving batches (A and C), got {len(recovered)}"

    batch_a_frames, batch_c_frames = recovered
    assert len(batch_a_frames) == len(records_a)
    assert len(batch_c_frames) == len(records_c)

    for i, raw_frame in enumerate(batch_a_frames):
        assert raw_frame.frame_id == message.frame_id
        assert raw_frame.is_extended == message.is_extended_frame
        assert raw_frame.payload == payload_bytes
        assert raw_frame.timestamp_us == base_a + i

    for i, raw_frame in enumerate(batch_c_frames):
        assert raw_frame.frame_id == message.frame_id
        assert raw_frame.is_extended == message.is_extended_frame
        assert raw_frame.payload == payload_bytes
        assert raw_frame.timestamp_us == base_c + i


def test_resync_after_middle_batch_corruption_single_feed(dictionary, dbc):
    (
        stream,
        message,
        payload_bytes,
        records_a,
        base_a,
        records_c,
        base_c,
        idx,
    ) = _corrupted_three_batch_stream(dictionary, dbc)

    deframer = Deframer(dictionary)
    recovered = list(deframer.feed(stream))

    _assert_resync_result(recovered, message, payload_bytes, records_a, base_a, records_c, base_c)

    total_corruption = (
        deframer.counters.cobs_failures
        + deframer.counters.crc_failures
        + deframer.counters.batch_format_failures
    )
    assert total_corruption == 1, (
        f"seed={SEED} offset={idx}: expected exactly 1 corrupt batch, "
        f"got counters={deframer.counters!r}"
    )
    assert deframer.counters.batches_ok == 2


def test_resync_after_middle_batch_corruption_chunked_feed(dictionary, dbc):
    (
        stream,
        message,
        payload_bytes,
        records_a,
        base_a,
        records_c,
        base_c,
        idx,
    ) = _corrupted_three_batch_stream(dictionary, dbc)

    rng = random.Random(SEED)
    chunks = []
    remaining = stream
    while remaining:
        # Deliberately small and uneven -- guarantees some chunk boundaries
        # land mid-frame, not just cleanly between frames.
        size = rng.randint(1, 7)
        chunks.append(remaining[:size])
        remaining = remaining[size:]
    assert len(chunks) > 1, "fixture assumption: the stream must actually be split across multiple feed() calls"

    deframer = Deframer(dictionary)
    recovered = []
    for chunk in chunks:
        recovered.extend(deframer.feed(chunk))

    assert len(recovered) == 2, (
        f"seed={SEED} offset={idx} chunk_count={len(chunks)}: expected 2 "
        f"surviving batches fed in {len(chunks)} arbitrarily-sized chunks, "
        f"got {len(recovered)}"
    )
    _assert_resync_result(recovered, message, payload_bytes, records_a, base_a, records_c, base_c)

    total_corruption = (
        deframer.counters.cobs_failures
        + deframer.counters.crc_failures
        + deframer.counters.batch_format_failures
    )
    assert total_corruption == 1, (
        f"seed={SEED}: expected exactly 1 corrupt batch under chunked "
        f"feeding, got counters={deframer.counters!r}"
    )


def test_garbage_between_two_valid_frames_does_not_poison_the_following_frame(dictionary, dbc):
    """A run of non-zero garbage bounded by its own delimiter (mimicking
    noise that eventually resynchronizes, either from a stray zero byte in
    the noise itself or from equipment din) is isolated as its own corrupt
    segment and does not prevent the valid frame that follows it from
    decoding — LINK-01's resync claim in miniature."""
    payload_a, records_a = _build_batch(dictionary, dbc, 3, batch_seq=10)
    payload_b, records_b = _build_batch(dictionary, dbc, 3, batch_seq=11)
    frame_a = cobs_frame(payload_a)
    frame_b = cobs_frame(payload_b)

    rng = random.Random(SEED)
    garbage = bytes(rng.randrange(1, 256) for _ in range(40))
    assert 0 not in garbage
    assert _classify(garbage) != "ok", (
        f"seed={SEED}: the random garbage coincidentally decoded and "
        f"verified cleanly through COBS+CRC — vanishingly unlikely; pick a "
        f"different seed if this ever fires"
    )

    stream = frame_a + garbage + DELIMITER + frame_b
    deframer = Deframer(dictionary)
    recovered = list(deframer.feed(stream))

    assert len(recovered) == 2, f"seed={SEED}: expected batch A and the following batch B both to decode"
    batch_a_frames, batch_b_frames = recovered
    assert len(batch_a_frames) == len(records_a)
    assert len(batch_b_frames) == len(records_b)

    message = dbc.get_message_by_name(SUBJECT_MESSAGE)
    payload_bytes = message.encode(SUBJECT_SIGNAL_VALUES)
    for raw_frame in batch_b_frames:
        assert raw_frame.frame_id == message.frame_id
        assert raw_frame.payload == payload_bytes

    total_corruption = (
        deframer.counters.cobs_failures
        + deframer.counters.crc_failures
        + deframer.counters.batch_format_failures
    )
    assert total_corruption == 1, (
        f"seed={SEED}: expected exactly 1 corrupt segment (the garbage), "
        f"got counters={deframer.counters!r}"
    )
    assert deframer.counters.batches_ok == 2


def test_undelimited_stream_exceeding_max_buffer_is_discarded_and_counted_without_growth(dictionary):
    """T-01-05: a stream that never presents a delimiter has its pending
    bytes discarded and the event counted, rather than growing memory
    without bound. Uses a small, explicit `max_buffer_bytes` (never the
    shipped config default) so the test is fast and its meaning can't drift
    with a config tune."""
    max_buffer_bytes = 200
    deframer = Deframer(dictionary, max_buffer_bytes=max_buffer_bytes)

    chunk = bytes([1, 2, 3, 4] * 64)  # 256 bytes, no zero byte anywhere
    assert 0 not in chunk
    assert len(chunk) > max_buffer_bytes

    for i in range(1, 6):
        recovered = list(deframer.feed(chunk))
        assert recovered == []
        assert deframer.counters.buffer_overflow_count == i
        # White-box check of this module's own T-01-05 invariant: the
        # accumulation buffer must never grow past roughly one feed()'s
        # worth of bytes beyond the cap -- proving memory does not grow
        # with continued feeding of an undelimited stream.
        assert len(deframer._buffer) <= max_buffer_bytes + len(chunk)


def test_buffer_overflow_check_runs_even_when_generator_is_only_partially_consumed(dictionary, dbc):
    """WR-03 regression: `feed()`'s T-01-05 overflow check must run
    unconditionally on every call, not only once a caller fully drains the
    returned generator to `StopIteration`. If the check instead lived as
    generator tail code reachable only after the last `yield` inside the
    delimiter-scanning loop, a caller that partially consumes the generator
    (here, one `next()` call, stopping before the second recovered batch)
    would never trigger it.

    Builds a stream with two complete, valid, delimiter-terminated batches
    (so `feed()` has more than one item to yield) followed by an
    undelimited tail exceeding `max_buffer_bytes`. Calling `next()` exactly
    once must still trip the overflow guard, proving the check does not
    depend on the caller reaching exhaustion."""
    max_buffer_bytes = 200
    payload_a, records_a = _build_batch(dictionary, dbc, 3, batch_seq=0)
    payload_b, _records_b = _build_batch(dictionary, dbc, 3, batch_seq=1)
    frame_a = cobs_frame(payload_a)
    frame_b = cobs_frame(payload_b)

    tail = bytes([1, 2, 3, 4] * 64)  # 256 bytes, no zero byte anywhere
    assert 0 not in tail
    assert len(tail) > max_buffer_bytes

    stream = frame_a + frame_b + tail
    deframer = Deframer(dictionary, max_buffer_bytes=max_buffer_bytes)

    gen = deframer.feed(stream)
    first_recovered = next(gen)  # deliberately partial consumption

    assert len(first_recovered) == len(records_a)
    assert deframer.counters.buffer_overflow_count == 1, (
        "the T-01-05 overflow check did not run after a single next() "
        "call -- it must run unconditionally per feed() call, not only "
        "once the generator is fully drained to StopIteration"
    )
    assert len(deframer._buffer) == 0
