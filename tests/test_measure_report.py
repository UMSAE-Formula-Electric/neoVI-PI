"""
tests/test_measure_report.py — plan 00-06 D-06 framing-overhead and
aggregation-engine tests.

Task 1 (below) asserts the pure-arithmetic overhead formulas in
`telemetry.wire.overhead` against hand-computable inputs. Task 2 appends
the aggregation-engine tests (per-ID, per-category, worst-N, ablations,
peak windows, bit rate) for `telemetry.measure.report`.
"""

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
