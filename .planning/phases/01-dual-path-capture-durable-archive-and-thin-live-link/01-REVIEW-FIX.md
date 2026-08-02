---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
fixed_at: 2026-08-02T00:00:00Z
review_path: .planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-REVIEW.md
iteration: 2
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-08-02T00:00:00Z
**Source review:** .planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope (fix_scope=critical_warning): 5 (CR-01, WR-01, WR-02, WR-03, WR-04)
- Fixed: 5 (CR-01, WR-01, WR-02, WR-03, WR-04)
- Skipped: 0

**Note on this run:** iteration 1 fixed CR-01 and WR-01 and then ended
early before WR-02, WR-03, or WR-04 were attempted -- those three were not
evaluated, not applied, and not rolled back from any partial state; they
remained open in `01-REVIEW.md` exactly as reviewed. Iteration 2 (this
run) completed all three remaining findings. Test suite baseline before
this run: 284 passed. After this run: 287 passed (three new regression
tests added, zero regressions).

## Fixed Issues

### CR-01: `archive_overflow` does not prevent the `.done` marker or a zero exit code

**Files modified:** `src/telemetry/logger/cli.py`, `tests/test_logger_cli_smoke.py`
**Commit:** `5c8fa04`
**Applied fix (iteration 1):** `_run_session`'s shutdown gate now requires
BOTH `not fan_out.counters.archive_write_failure` AND
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
**Applied fix (iteration 1):** Added a small lock (`FanOutCounters._archive_hwm_lock`,
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

### WR-02: Critical layout-divergence guard implemented as a bare `assert`

**Files modified:** `src/telemetry/wire/batcher.py`
**Commit:** `759f5a5`
**Applied fix (iteration 2):** Replaced the bare
`assert BATCH_HEADER_STRUCT.size == overhead.BATCH_HEADER_BYTES` (stripped
entirely under `python -O`/`PYTHONOPTIMIZE=1`) with an explicit
`if BATCH_HEADER_STRUCT.size != overhead.BATCH_HEADER_BYTES: raise
RuntimeError(...)`, preserving the exact original diagnostic message. This
guard survives optimized runs, which is the whole point of
01-CRITICAL-CONSTRAINTS #4 -- it is the only thing keeping the real on-wire
batch header size and the analytic overhead model (used for the Phase 0
compression-ratio gate's own pass/fail numbers) from silently diverging.
No test change was needed: this is a module-import-time invariant already
implicitly exercised by every test that imports `telemetry.wire.batcher`
(the module fails to import if the check trips), and no test asserted on
the specific exception type (`AssertionError`) that would need updating.
Confirmed via `python -c "import ast; ast.parse(...)"` and a direct import
that the module still loads cleanly, and `tests/test_framing.py` (17 tests
exercising `batcher.py` directly) passes unchanged.

### WR-03: `Deframer.feed()`'s T-01-05 buffer-overflow cap only runs if the generator is fully drained

**Files modified:** `src/telemetry/ground/deframe.py`, `tests/test_framing.py`
**Commit:** `a92fb4c`
**Applied fix (iteration 2):** Restructured `feed()` so the delimiter-scan
loop appends each recovered batch to a local `recovered_batches` list
instead of `yield`ing immediately, then runs the buffer-overflow
check/reset, and only afterward does `yield from recovered_batches`. This
puts the method's *only* yield point after all buffer-management code, so
a generator's lazy execution model works in the fix's favor rather than
against it: the first `next()` call on the returned generator always runs
the full scan-and-overflow-check before producing any item, regardless of
how many (if any) items the caller then consumes.

Added
`test_buffer_overflow_check_runs_even_when_generator_is_only_partially_consumed`
to `tests/test_framing.py`: builds a stream with two complete, valid
batches (so the generator has more than one item to yield) followed by an
undelimited tail exceeding `max_buffer_bytes`, then calls `next()` exactly
once (deliberately partial consumption) and asserts
`buffer_overflow_count == 1`. Verified this test fails against the pre-fix
generator (`assert 0 == 1` -- the overflow check never ran because the
generator was suspended at the first `yield` inside the loop, before ever
reaching the post-loop tail code) and passes against the fix. This was
called out in the task scope as the one finding with real runtime
consequences (unbounded buffer growth on the pit-side receiver if a future
caller or refactor ever partially consumes `feed()`), so it received the
most scrutiny of the three.

### WR-04: `UdpLink.recv()` does not guard against a closed socket, unlike `LoopbackLink.recv()`

**Files modified:** `src/telemetry/link/udp.py`, `src/telemetry/link/loopback.py`, `tests/test_link.py`
**Commit:** `da69359`
**Applied fix (iteration 2):** Guarded both `recv()` implementations on
`self._closed`, raising `RuntimeError("cannot recv on a closed
{Link name}")` immediately -- the same closed-state contract `send()`
already had on both implementations since 01-08. `UdpLink.recv()`
previously called `settimeout()`/`recvfrom()` on an already-closed socket,
raising an unhandled `OSError` (`Bad file descriptor` on POSIX, `WinError
10038` on Windows). `LoopbackLink.recv()` previously kept working after
`close()` since its internal `queue.Queue` is untouched by `close()`.
Chose the `RuntimeError`-on-both option (over the review's alternative,
permissive `None`-on-both option) to match the already-established
`send()` convention in this same package, keeping one consistent
closed-state idiom across all three `Link` methods.

Added
`test_recv_after_close_raises_runtime_error_on_both_implementations` to
the existing **shared, `link_pair`-parameterised** suite in
`tests/test_link.py` (not a UDP-only test), right beside the existing
`test_close_is_idempotent_and_send_after_close_raises` it mirrors. Verified
this test fails against both pre-fix implementations when run without
`-x` (`loopback` param: `Failed: DID NOT RAISE RuntimeError`; `udp` param:
`OSError: [WinError 10038] An operation was attempted on something that is
not a socket`) and passes against the fix on both parametrizations.

## Skipped Issues

None -- all five in-scope findings (CR-01, WR-01, WR-02, WR-03, WR-04) are fixed.

---

_Fixed: 2026-08-02T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
