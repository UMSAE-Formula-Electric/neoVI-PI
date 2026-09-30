"""
Task 1's behaviour-first pass for 03-02 (OPS-03): pins `check_disk_space`'s
boundary bands, the non-existent-path ancestor-resolution fallback, and the
`used + free < total` real-ext4 case, all against a fake `disk_usage_fn` so
no test touches the real filesystem's free space.
"""

from collections import namedtuple
from pathlib import Path

from telemetry.ops.disk_monitor import (
    DISK_CRITICAL,
    DISK_OK,
    DISK_WARN,
    check_disk_space,
)

_Usage = namedtuple("_Usage", ["total", "used", "free"])

WARN_BYTES = 20_000_000_000
CRITICAL_BYTES = 5_000_000_000


def _fake_disk_usage_fn(free_bytes, total_bytes=100_000_000_000, calls=None):
    def _fn(path):
        if calls is not None:
            calls.append(path)
        used_bytes = total_bytes - free_bytes
        return _Usage(total=total_bytes, used=used_bytes, free=free_bytes)

    return _fn


# ---------------------------------------------------------------------------
# Boundary bands -- strictly-less-than at both thresholds.
# ---------------------------------------------------------------------------


def test_one_byte_below_critical_is_critical(tmp_path):
    reading = check_disk_space(
        tmp_path,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fake_disk_usage_fn(CRITICAL_BYTES - 1),
    )
    assert reading.state == DISK_CRITICAL


def test_exactly_at_critical_is_warn_not_critical(tmp_path):
    reading = check_disk_space(
        tmp_path,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fake_disk_usage_fn(CRITICAL_BYTES),
    )
    assert reading.state == DISK_WARN


def test_one_byte_below_warn_and_above_critical_is_warn(tmp_path):
    reading = check_disk_space(
        tmp_path,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fake_disk_usage_fn(WARN_BYTES - 1),
    )
    assert reading.state == DISK_WARN


def test_exactly_at_warn_is_ok(tmp_path):
    reading = check_disk_space(
        tmp_path,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fake_disk_usage_fn(WARN_BYTES),
    )
    assert reading.state == DISK_OK


def test_far_above_both_is_ok(tmp_path):
    reading = check_disk_space(
        tmp_path,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fake_disk_usage_fn(WARN_BYTES * 10),
    )
    assert reading.state == DISK_OK


# ---------------------------------------------------------------------------
# disk_usage_fn contract: resolved path, called exactly once.
# ---------------------------------------------------------------------------


def test_disk_usage_fn_receives_resolved_path_and_is_called_exactly_once(tmp_path):
    calls = []
    reading = check_disk_space(
        tmp_path,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fake_disk_usage_fn(WARN_BYTES * 10, calls=calls),
    )
    assert len(calls) == 1
    assert calls[0] == tmp_path
    assert reading.measured_path == tmp_path


# ---------------------------------------------------------------------------
# Non-existent path: measure the nearest existing ancestor, never raise,
# never create anything.
# ---------------------------------------------------------------------------


def test_nonexistent_path_measures_nearest_existing_ancestor(tmp_path):
    missing = tmp_path / "does" / "not" / "exist" / "yet"
    assert not missing.exists()

    reading = check_disk_space(
        missing,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fake_disk_usage_fn(WARN_BYTES * 10),
    )

    assert reading.measured_path == tmp_path
    assert not missing.exists()
    assert not (tmp_path / "does").exists()


def test_nonexistent_single_component_path_falls_back_to_parent(tmp_path):
    missing = tmp_path / "sessions"
    assert not missing.exists()

    reading = check_disk_space(
        missing,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fake_disk_usage_fn(CRITICAL_BYTES - 1),
    )

    assert reading.measured_path == tmp_path
    assert reading.state == DISK_CRITICAL
    assert not missing.exists()


# ---------------------------------------------------------------------------
# `used + free < total` -- the real ext4 root-reserve case -- produces a
# correct band with no error; nothing derives a percentage from `total`.
# ---------------------------------------------------------------------------


def test_used_plus_free_less_than_total_produces_correct_band_no_error(tmp_path):
    total_bytes = 100_000_000_000
    free_bytes = CRITICAL_BYTES - 1
    # A `used` deliberately inconsistent with `total - free` (root-reserved
    # blocks counted in `used` but not in `free` -- see module docstring).
    used_bytes = total_bytes - free_bytes - 1_000_000_000
    assert used_bytes + free_bytes < total_bytes

    def _fn(path):
        return _Usage(total=total_bytes, used=used_bytes, free=free_bytes)

    reading = check_disk_space(
        tmp_path,
        warn_free_bytes=WARN_BYTES,
        critical_free_bytes=CRITICAL_BYTES,
        disk_usage_fn=_fn,
    )

    assert reading.state == DISK_CRITICAL
    assert reading.free_bytes == free_bytes
    assert reading.total_bytes == total_bytes
