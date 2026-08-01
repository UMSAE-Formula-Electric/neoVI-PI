"""
tests/test_measure_report.py — plan 00-06 D-06 framing-overhead and
aggregation-engine tests.

Task 1 (below) asserts the pure-arithmetic overhead formulas in
`telemetry.wire.overhead` against hand-computable inputs. Task 2 appends
the aggregation-engine tests (per-ID, per-category, worst-N, ablations,
peak windows, bit rate) for `telemetry.measure.report`.
"""

import dataclasses

import pytest

from telemetry.wire.overhead import (
    BATCH_HEADER_BYTES,
    CRC16_BYTES,
    COBS_BLOCK_BYTES,
    OverheadBreakdown,
    cobs_worst_case_overhead,
    all_in_bytes_per_batch,
    overhead_breakdown,
)


# ---------------------------------------------------------------------------
# Task 1: D-06 analytic framing overhead
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload_bytes, expected",
    [(0, 1), (253, 1), (254, 2), (507, 2), (508, 3)],
)
def test_cobs_worst_case_overhead_closed_form(payload_bytes, expected):
    assert cobs_worst_case_overhead(payload_bytes) == expected


def test_all_in_bytes_per_batch_zero_payload_matches_header_plus_crc_plus_cobs():
    assert all_in_bytes_per_batch(0) == (
        BATCH_HEADER_BYTES + CRC16_BYTES + cobs_worst_case_overhead(CRC16_BYTES)
    )


def test_all_in_bytes_per_batch_strictly_increasing():
    values = [all_in_bytes_per_batch(n) for n in range(0, 2000, 7)]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_overhead_breakdown_all_in_bytes_matches_batch_formula():
    breakdown = overhead_breakdown(800, 100)
    assert breakdown.all_in_bytes == all_in_bytes_per_batch(800)


def test_overhead_breakdown_clean_bytes_per_frame_reconstructs_total():
    breakdown = overhead_breakdown(800, 100)
    assert breakdown.clean_bytes_per_frame * breakdown.frames_in_batch == pytest.approx(800)


def test_overhead_breakdown_overhead_pct_formula():
    breakdown = overhead_breakdown(800, 100)
    expected_pct = (breakdown.all_in_bytes - 800) / 800 * 100
    assert breakdown.overhead_pct == pytest.approx(expected_pct)


def test_overhead_breakdown_zero_frames_raises_value_error_naming_parameter():
    with pytest.raises(ValueError, match="frames_in_batch"):
        overhead_breakdown(800, 0)


def test_overhead_breakdown_at_100_frames_8_bytes_clean_overhead_is_small_additive_term():
    breakdown = overhead_breakdown(800, 100)
    diff = breakdown.all_in_bytes_per_frame - breakdown.clean_bytes_per_frame
    assert 0.1 < diff < 0.3


def test_overhead_breakdown_exposes_all_nine_fields():
    breakdown = overhead_breakdown(800, 100)
    expected_fields = {
        "clean_payload_bytes",
        "batch_header_bytes",
        "crc_bytes",
        "cobs_bytes",
        "all_in_bytes",
        "frames_in_batch",
        "clean_bytes_per_frame",
        "all_in_bytes_per_frame",
        "overhead_pct",
    }
    assert set(OverheadBreakdown.__dataclass_fields__) == expected_fields


# ---------------------------------------------------------------------------
# Task 2: aggregation engine — per-ID, per-category, worst-N, ablations,
# peak windows, bit rate (src/telemetry/measure/report.py)
# ---------------------------------------------------------------------------

from telemetry.measure.report import (
    ABLATIONS,
    PerIdStats,
    StreamMeasurement,
    ablation_options,
    bitrate_summary,
    build_report,
    measure_stream,
    peak_windows,
    write_report_csv,
    _category_rollup,
)
from telemetry.measure.classify import CATEGORIES
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import Encoder, EncoderOptions
from telemetry.wire.decoder import Decoder
from telemetry.synth.generator import SyntheticFrameSource


def _make_measurement(id_specs, batch_timestamp_us=1_000_000):
    """`id_specs`: list of (frame_id, is_extended, frame_count, clean_bytes,
    all_in_bytes) tuples. Builds a hand-computable `StreamMeasurement` with
    one synthetic batch-timeline entry, so peak/bit-rate/report-structure
    tests never depend on running the real generator."""
    measurement = StreamMeasurement()
    total_all_in = 0.0
    for i, (frame_id, is_extended, frame_count, clean_bytes, all_in_bytes) in enumerate(id_specs):
        measurement.per_id[i] = PerIdStats(
            frame_id=frame_id,
            is_extended=is_extended,
            frame_count=frame_count,
            clean_encoded_bytes=clean_bytes,
            all_in_encoded_bytes=all_in_bytes,
        )
        measurement.total_frames += frame_count
        measurement.total_bytes += clean_bytes
        total_all_in += all_in_bytes
    measurement.total_all_in_bytes = total_all_in
    measurement.batch_timeline = [(batch_timestamp_us, total_all_in * 8)]
    return measurement


def test_aggregate_clean_bytes_equals_sum_over_per_id(dbc, gate_config):
    dictionary = build_id_dictionary(dbc)
    source = SyntheticFrameSource(
        dbc, dictionary, gate_config, "typical", duration_s=0.5,
        only_message_names=["M192_Command_Message", "INV_Diag_Buffer"],
    )
    frames = list(source.frames())
    measurement = measure_stream(frames, Encoder(dictionary), Decoder(dictionary), gate_config.batch_frames)

    assert measurement.total_bytes == sum(s.clean_encoded_bytes for s in measurement.per_id.values())


class _AlwaysWrongDecoder:
    """Wraps a real decoder but corrupts every recovered frame's payload —
    used to prove `measure_stream` raises on its own byte-identity check
    rather than silently excluding a mismatched frame from the count."""

    def __init__(self, inner):
        self._inner = inner

    def decode(self, cfr, batch_base_timestamp_us):
        frame = self._inner.decode(cfr, batch_base_timestamp_us)
        return frame._replace(payload=frame.payload + b"\x00")


def test_measure_stream_raises_on_roundtrip_mismatch(dbc, gate_config):
    dictionary = build_id_dictionary(dbc)
    source = SyntheticFrameSource(
        dbc, dictionary, gate_config, "typical", duration_s=0.1,
        only_message_names=["M192_Command_Message"],
    )
    frames = list(source.frames())
    encoder = Encoder(dictionary)
    poisoned_decoder = _AlwaysWrongDecoder(Decoder(dictionary))

    with pytest.raises(RuntimeError, match="round-trip mismatch"):
        measure_stream(frames, encoder, poisoned_decoder, gate_config.batch_frames)


def test_peak_windows_exact_value_for_a_deliberate_burst():
    # (timestamp_us, bits) — one entry per batch. A burst at t=200_000us.
    timeline = [
        (0, 1000),
        (100_000, 1000),
        (200_000, 5000),
        (300_000, 1000),
        (400_000, 1000),
    ]
    result = peak_windows(timeline, [0.1])
    # Hand-computed: the window [100_000, 200_000] carries 1000 + 5000 = 6000
    # bits over 0.1s = 60_000 bits/s, the maximum over any 0.1s slide.
    assert result["0.1s"]["peak_bits_per_s"] == pytest.approx(60_000.0)
    assert result["0.1s"]["is_whole_run_average"] is False


def test_peak_windows_longer_than_run_returns_whole_run_average():
    timeline = [
        (0, 1000),
        (100_000, 1000),
        (200_000, 5000),
        (300_000, 1000),
        (400_000, 1000),
    ]
    result = peak_windows(timeline, [1.0])
    # Run spans 0.4s; a 1.0s window is longer than the run, so this must be
    # the whole-run average: 9000 bits / 0.4s = 22_500 bits/s.
    assert result["1s"]["peak_bits_per_s"] == pytest.approx(22_500.0)
    assert result["1s"]["is_whole_run_average"] is True


def test_bitrate_summary_exact_kbps():
    # 12_500 bytes * 8 bits/byte = 100_000 bits over 1.0s = 100.0 kbit/s.
    assert bitrate_summary(12_500, 1.0) == pytest.approx(100.0)


def test_ablation_options_differs_from_full_in_exactly_one_field():
    full = ablation_options("full")
    fields = ("payload_delta", "use_dictionary", "sequence_byte", "trim_trailing_zeros")
    for name in ("no_sequence_byte", "raw_payload", "no_dictionary"):
        opts = ablation_options(name)
        diffs = [f for f in fields if getattr(opts, f) != getattr(full, f)]
        assert len(diffs) == 1, (name, diffs)


def test_ablation_byte_totals_ordering_over_same_frame_list(dbc, gate_config):
    dictionary = build_id_dictionary(dbc)
    source = SyntheticFrameSource(
        dbc, dictionary, gate_config, "typical", duration_s=0.5,
        only_message_names=["M192_Command_Message"],
    )
    frames = list(source.frames())

    totals = {}
    for name in ABLATIONS:
        options = ablation_options(name)
        measurement = measure_stream(
            frames, Encoder(dictionary, options), Decoder(dictionary, options), gate_config.batch_frames
        )
        totals[name] = measurement.total_bytes

    assert totals["no_sequence_byte"] < totals["full"]
    assert totals["raw_payload"] > totals["full"]
    assert totals["no_dictionary"] > totals["full"]


def test_category_rollup_key_set_and_empty_bucket_notes():
    rollup = _category_rollup(StreamMeasurement(), classifications={})

    assert set(rollup.keys()) == set(CATEGORIES)
    for category, stats in rollup.items():
        assert stats["message_count"] == 0
        assert stats["note"]


def test_build_report_worst_n_independent_of_categories_and_threshold_comparison_shape(gate_config):
    id_specs = [
        (0x100, False, 10, 100.0, 110.0),  # 10.0 clean bytes/frame
        (0x200, False, 10, 50.0, 55.0),  # 5.0
        (0x300, False, 10, 200.0, 210.0),  # 20.0 <- worst
    ]
    full = _make_measurement(id_specs)
    ablation_measurements = {"typical": {name: full for name in ABLATIONS}}

    meta = {
        "input_provenance": "synthesized from epbr2026_DBC_v1.0.dbc, not a captured log",
        "known_limitation": "payload entropy is modelled, not measured",
    }
    report = build_report(
        ablation_measurements=ablation_measurements,
        duration_s=1.0,
        rates=[],
        classifications={},
        worst_n=2,
        peak_windows_s=[0.1, 1.0],
        thresholds=gate_config.thresholds,
        meta=meta,
    )

    bracket = report["brackets"]["typical"]

    # categories block, computed from an empty classification map here, is
    # still keyed exactly by CATEGORIES with every bucket noted.
    assert set(bracket["categories"].keys()) == set(CATEGORIES)

    # worst_n is independent of the (empty) categorical buckets above.
    assert len(bracket["worst_n"]) == 2
    worst_values = [entry["clean_bytes_per_frame"] for entry in bracket["worst_n"]]
    assert worst_values == sorted(worst_values, reverse=True)
    assert worst_values[0] == pytest.approx(20.0)
    assert worst_values[1] == pytest.approx(10.0)

    assert set(bracket["ablations"]) == set(ABLATIONS)
    assert all(entry["roundtrip_verified"] for entry in bracket["ablations"].values())

    tc = report["meta"]["threshold_comparison"]
    expected_keys = {"criterion", "measured", "threshold", "headroom_pct", "within_threshold"}
    for entry in tc:
        assert set(entry.keys()) == expected_keys

    verdict_words = {"pass", "fail", "go", "no-go", "nogo"}

    def _walk_strings(value):
        if isinstance(value, dict):
            for v in value.values():
                yield from _walk_strings(v)
        elif isinstance(value, list):
            for v in value:
                yield from _walk_strings(v)
        elif isinstance(value, str):
            yield value

    for s in _walk_strings(report):
        assert s.lower() not in verdict_words

    assert report["meta"]["input_provenance"]
    assert report["meta"]["known_limitation"]


def test_build_report_raises_when_peak_window_s_not_in_peak_windows_s(gate_config):
    # WR-03: thresholds.peak_window_s and peak_windows_s have no enforced
    # relationship in gate.json. A mismatch must raise loudly rather than
    # silently reporting a 0.0 kbit/s peak as trivially passing.
    id_specs = [(0x100, False, 10, 100.0, 110.0)]
    full = _make_measurement(id_specs)
    ablation_measurements = {"typical": {name: full for name in ABLATIONS}}
    mismatched_thresholds = dataclasses.replace(gate_config.thresholds, peak_window_s=5.0)

    with pytest.raises(ValueError, match="peak_window_s"):
        build_report(
            ablation_measurements=ablation_measurements,
            duration_s=1.0,
            rates=[],
            classifications={},
            worst_n=1,
            peak_windows_s=[0.1, 1.0],  # 5.0 deliberately absent
            thresholds=mismatched_thresholds,
            meta={"input_provenance": "x", "known_limitation": "y"},
        )


def test_write_report_csv_one_row_per_bracket_and_id(tmp_path, gate_config):
    id_specs = [
        (0x100, False, 10, 100.0, 110.0),
        (0x200, False, 10, 50.0, 55.0),
        (0x300, False, 10, 200.0, 210.0),
    ]
    full = _make_measurement(id_specs)
    ablation_measurements = {"typical": {name: full for name in ABLATIONS}}
    report = build_report(
        ablation_measurements=ablation_measurements,
        duration_s=1.0,
        rates=[],
        classifications={},
        worst_n=10,
        peak_windows_s=[0.1, 1.0],
        thresholds=gate_config.thresholds,
        meta={"input_provenance": "x", "known_limitation": "y"},
    )

    csv_path = tmp_path / "out.csv"
    write_report_csv(report, csv_path)

    import csv as csv_module

    with open(csv_path, newline="") as f:
        rows = list(csv_module.reader(f))

    assert rows[0][0] == "bracket"
    assert "clean_bytes_per_frame" in rows[0]
    assert "all_in_bytes_per_frame" in rows[0]
    assert len(rows) - 1 == len(id_specs)
