---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
fixed_at: 2026-08-02T00:00:00Z
review_path: .planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 2
skipped: 3
status: partial
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-08-02T00:00:00Z
**Source review:** .planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope (fix_scope=critical_warning): 5 (CR-01, WR-01, WR-02, WR-03, WR-04)
- Fixed: 2 (CR-01, WR-01)
- Skipped: 3 (WR-02, WR-03, WR-04 -- run paused by user request before these were attempted)

**Note on this run:** the user issued `/gsd-pause-work` mid-run, immediately
after the WR-01 fix was mid-flight (source edits applied, not yet
verified/committed). Per this agent's atomicity guarantees, the in-flight
WR-01 fix was finished, verified, and committed rather than left as
uncommitted worktree state, and the run then stopped before starting
WR-02. WR-02, WR-03, and WR-04 were never attempted -- not evaluated,
not applied, not rolled back from a partial state. They remain open in
01-REVIEW.md exactly as reviewed. Re-run `/gsd-code-review --fix` on this
phase to continue with WR-02/03/04 (and IN-01/IN-02 if `--fix-scope all`
is desired).

## Fixed Issues

### CR-01: `archive_overflow` does not prevent the `.done` marker or a zero exit code

**Files modified:** `src/telemetry/logger/cli.py`, `tests/test_logger_cli_smoke.py`
**Commit:** `5c8fa04`
**Applied fix:** `_run_session`'s shutdown gate now requires BOTH
`not fan_out.counters.archive_write_failure` AND
`not fan_out.counters.archive_overflow` before calling `mark_done()` --
previously it checked only `archive_write_failure`, so a session that hit
CAP-03's fatal archive-queue-full path (frame lost before it ever reached
the writer) still got a `.done` marker and exit code 0. The "left WITHOUT
a .done marker" warning log now names both flags. Added
`test_cli_archive_overflow_leaves_no_done_marker_and_exits_nonzero` in
`tests/test_logger_cli_smoke.py`, which drives the real CLI as a subprocess
with `archive.queue_depth=1` and `flush_every_records=1` (fsync every
record, deliberately slower than the synthetic capture loop) to force a
deterministic overflow, then asserts no `.done` marker, a non-zero exit
code, and `archive_marked_done: false` in the JSON summary. Verified this
test fails (asserts `0 != 0`, `archive_marked_done: True`) against the
pre-fix code and passes against the fix.

### WR-01: Unsynchronized cross-thread write to `FanOutCounters.archive_high_water_mark`

**Files modified:** `src/telemetry/capture/fanout.py`, `src/telemetry/archive/runner.py`
**Commit:** `0725827`
**Applied fix:** Added a small lock (`FanOutCounters._archive_hwm_lock`,
a `threading.Lock` field excluded from `repr`/`==` via
`field(repr=False, compare=False)`) that guards ONLY the
`archive_high_water_mark` read-modify-write -- every other `FanOutCounters`
field keeps its existing lock-free, single-writer discipline, which the
module docstring still documents. Both write sites now take the lock:
`FanOut.submit()` in `fanout.py` and `ArchiveRunner._record_high_water_mark()`
in `archive/runner.py`. Updated `fanout.py`'s module docstring to name this
one field as the deliberate exception to the "no lock" invariant, and added
an inline comment at the `runner.py` call site cross-referencing it.

A supplementary concurrency regression test (two threads hammering the
shared counter via the real `FanOut.submit()`/`ArchiveRunner._record_high_water_mark()`
code paths) was attempted but discarded: under this project's default
Python threading/GIL scheduling, the test passed 5/5 times even with both
locks reverted, meaning it could not reliably distinguish fixed from
unfixed code and would have shipped as a false-confidence test. The
existing test suite (`tests/test_archive_writer.py::test_high_water_mark_recorded_on_shared_counters_after_join`,
`tests/test_fanout.py::test_high_water_marks_track_deepest_occupancy_and_never_decrease`)
continues to pass unchanged against the fix -- neither test's assertions
depend on the timing this fix corrects, so this finding is fixed at the
code level but does not carry new automated regression coverage for the
specific race. This is a real gap; a human wanting stronger proof should
either accept a probabilistic stress test with a documented low false-negative
rate, or restructure per REVIEW.md's alternative suggestion (separate
producer/consumer high-water-mark fields merged with `max()` only after
`join()`, which is a safe point requiring no lock at all and would be
directly assertable).

## Skipped Issues

### WR-02: Critical layout-divergence guard implemented as a bare `assert`

**File:** `src/telemetry/wire/batcher.py:43-47`
**Reason:** Run paused by user (`/gsd-pause-work`) before this finding was
started. Not evaluated, not applied.
**Original issue:** A bare `assert` guarding `BATCH_HEADER_STRUCT.size ==
overhead.BATCH_HEADER_BYTES` is stripped entirely under `python -O`,
silently disabling the one guard against the real batch header layout and
the analytic overhead model diverging. See 01-REVIEW.md for the full
finding and suggested fix (`raise RuntimeError(...)` instead of `assert`).

### WR-03: `Deframer.feed()`'s T-01-05 buffer-overflow cap only runs if the generator is fully drained

**File:** `src/telemetry/ground/deframe.py:79-104`
**Reason:** Run paused by user (`/gsd-pause-work`) before this finding was
started. Not evaluated, not applied.
**Original issue:** The buffer-overflow eviction logic lives as generator
tail code after the last `yield`, so it only runs if a caller fully drains
`feed()`'s generator -- a partial consumer would silently skip the memory
bound this method's docstring documents. See 01-REVIEW.md for the full
finding and suggested fix (move the overflow check to run unconditionally,
e.g. at the start of `feed()` before the first `yield`).

### WR-04: `UdpLink.recv()` does not guard against a closed socket, unlike `LoopbackLink.recv()`

**File:** `src/telemetry/link/udp.py:92-118`, `src/telemetry/link/loopback.py:36-40`
**Reason:** Run paused by user (`/gsd-pause-work`) before this finding was
started. Not evaluated, not applied.
**Original issue:** `UdpLink.recv()` after `close()` raises an unhandled
`OSError` instead of returning `None` like `LoopbackLink.recv()` and every
other `Link.recv()` timeout/no-data path. See 01-REVIEW.md for the full
finding and suggested fix (guard on `self._closed` and raise/return `None`
consistently, plus add the missing shared-suite test).

---

_Fixed: 2026-08-02T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
