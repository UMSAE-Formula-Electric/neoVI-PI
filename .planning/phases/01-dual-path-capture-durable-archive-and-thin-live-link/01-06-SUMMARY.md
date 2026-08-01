---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 06
subsystem: telemetry-pipeline
tags: [mcap, archive, fsync, threading, durability, fanout]

# Dependency graph
requires:
  - phase: 01-04
    provides: "ArchiveWriter (mcap.Writer wrapper, use_chunking=False, record-count-or-time fsync cadence scaffold), FanOut/CapturedFrame/FanOutCounters (the capture divergence point), archive/record.py's on-disk layout"
  - phase: 01-05
    provides: "telemetry.archive.reader.recover_session, the one supported crash-recovery read path this plan's round-trip tests read back through"
provides:
  - "ArchiveWriter.records_written / .flush_count read-only properties and an injectable monotonic clock, making the count-or-time fsync cadence directly inspectable and testable without sleeping"
  - "close() routed through the same _flush_and_sync() cadence helper add() uses, so its final sync is unconditional and counted"
  - "telemetry.archive.runner.ArchiveRunner — the non-daemon consumer thread draining FanOut.archive_queue into the writer, with the public STOP sentinel"
  - "FanOutCounters.archive_write_failure — the durability-side counterpart to the existing archive_overflow field"
  - "tests/test_archive_writer.py filled in from its Wave-0 placeholder: 13 tests covering ARCH-01 round-trip, ARCH-04 cadence/sync accounting, the mcap-chunking regression pin, and the archive drain thread's never-stalls-capture proof"
affects: [01-07, 01-10, 01-13]

# Tech tracking
tech-stack:
  added: []  # mcap already pinned by 01-02/01-04; this plan hardens its writer usage
  patterns:
    - "ArchiveWriter's clock= injectable callable, defaulting to time.monotonic, so the time-based cadence branch is testable without sleeping"
    - "_flush_and_sync() is the single cadence primitive both add()'s triggered path and close()'s unconditional final sync route through, so flush_count accounts for both uniformly"
    - "ArchiveRunner mirrors src/new_logger.py's writer_thread discipline (named non-daemon thread, poll stop_event every iteration, module-level-style sentinel pushed onto the queue, drain-not-discard on either exit path) while replacing its invisible debug-only exception handling with a critical-severity log + counters + re-raise"
    - "telemetry.archive depends on telemetry.capture.fanout (for CapturedFrame/FanOutCounters); telemetry.capture.fanout imports nothing from telemetry.archive — the one-directional dependency that makes ARCH-04/CAP-04 structural"

key-files:
  created:
    - src/telemetry/archive/runner.py
  modified:
    - src/telemetry/archive/writer.py
    - src/telemetry/capture/fanout.py
    - tests/test_archive_writer.py

key-decisions:
  - "flush_count/records_written exposed as read-only properties rather than the plan's literal 'writer.flush_count'/'writer.records_written' phrasing being ambiguous about public vs. private — implemented as public @property, matching is_closed's existing shape"
  - "close()'s final sync refactored to call the same _flush_and_sync() helper add() uses (rather than duplicating flush+fsync inline, as the tracer's original close() did) so flush_count correctly accounts for the final sync without a second counter or special-case"
  - "ArchiveRunner's inter-module sentinel is named STOP (public, no leading underscore) rather than new_logger.py's file-local _STOP, because the producer of the sentinel (a caller in a different module, or a test) is not the same file as the consumer that checks for it"
  - "FanOutCounters.archive_write_failure added as a new field on the existing dataclass (alongside archive_overflow) rather than a separate ArchiveRunner-specific counters class, since the plan's action text calls it 'the shared counters object' and fanout.py already carries archive-related fields without importing telemetry.archive"
  - "Test channel constants (MAIN/SENSOR) match config/logger.json's real channel names for readability, but every record count, cadence value (flush_every_records/flush_every_s), and queue size in the test file is an explicit literal argument, never read from the shipped config, per the plan's critical constraint 1"

requirements-completed: [ARCH-04]

coverage:
  - id: D1
    description: "Two hundred frames spread across two channels round-trip through recover_session with id/extended-flag/payload/timestamp all intact and no frame missing or duplicated (multiset equality), and each frame's recovered topic matches the channel it was submitted on"
    requirement: "ARCH-01"
    verification:
      - kind: unit
        ref: "tests/test_archive_writer.py#test_two_hundred_frames_across_two_channels_round_trip"
        status: pass
    human_judgment: false
  - id: D2
    description: "The count-or-time fsync cadence fires exactly on schedule on both triggers independently, a count-triggered sync resets the elapsed-time window so it cannot also fire a redundant time-triggered sync in the same window, close() always performs one more unconditional sync regardless of how many records are pending, and flush_count/records_written agree with the observed sync/record counts"
    requirement: "ARCH-04"
    verification:
      - kind: unit
        ref: "tests/test_archive_writer.py#test_count_cadence_produces_exactly_the_configured_sync_count"
        status: pass
      - kind: unit
        ref: "tests/test_archive_writer.py#test_time_cadence_fires_once_per_elapsed_window"
        status: pass
      - kind: unit
        ref: "tests/test_archive_writer.py#test_count_trigger_resets_the_elapsed_window_no_redundant_time_sync"
        status: pass
      - kind: unit
        ref: "tests/test_archive_writer.py#test_close_always_syncs_once_more_regardless_of_pending_records"
        status: pass
      - kind: unit
        ref: "tests/test_archive_writer.py#test_flush_count_and_records_written_agree_with_observed_counts"
        status: pass
    human_judgment: false
  - id: D3
    description: "One record reaches the OS-visible file and is readable through recover_session before close() is ever called — the regression guard for mcap's default chunking behaviour, which would leave the file effectively empty at this point"
    requirement: "ARCH-01"
    verification:
      - kind: unit
        ref: "tests/test_archive_writer.py#test_one_record_reaches_disk_and_is_readable_before_close"
        status: pass
    human_judgment: false
  - id: D4
    description: "A raising sync function propagates out of add() rather than being swallowed"
    requirement: "ARCH-04"
    verification:
      - kind: unit
        ref: "tests/test_archive_writer.py#test_a_raising_sync_propagates_rather_than_being_swallowed"
        status: pass
    human_judgment: false
  - id: D5
    description: "ArchiveRunner, started against a real FanOut's archive queue, drains every submitted frame into the writer with none missing and none duplicated"
    requirement: "CAP-03"
    verification:
      - kind: unit
        ref: "tests/test_archive_writer.py#test_archive_runner_drains_every_submitted_frame_none_missing_or_duplicated"
        status: pass
    human_judgment: false
  - id: D6
    description: "With the writer's sync patched to sleep far longer than a submit() call has any business taking, every individual FanOut.submit() call stays bounded well under that sleep, and every frame still reaches the archive after the drain completes — the flush cost lands on the queue, not on the producer"
    requirement: "ARCH-04"
    verification:
      - kind: unit
        ref: "tests/test_archive_writer.py#test_slow_sync_does_not_slow_the_producer_and_every_frame_still_lands"
        status: pass
    human_judgment: false
  - id: D7
    description: "The runner exits cleanly on the STOP sentinel, and separately exits on the stop event even with items still queued, draining what remains before returning rather than discarding it"
    verification:
      - kind: unit
        ref: "tests/test_archive_writer.py#test_runner_exits_cleanly_on_sentinel"
        status: pass
      - kind: unit
        ref: "tests/test_archive_writer.py#test_runner_exits_on_stop_event_and_drains_remaining_items"
        status: pass
    human_judgment: false
  - id: D8
    description: "The runner records the archive queue's high-water mark as it drains, and that value is visible on the shared FanOutCounters object after join"
    verification:
      - kind: unit
        ref: "tests/test_archive_writer.py#test_high_water_mark_recorded_on_shared_counters_after_join"
        status: pass
    human_judgment: false

# Metrics
duration: 35min
completed: 2026-08-01
status: complete
---

# Phase 1 Plan 6: Archive Writer Cadence Hardening and the Drain Thread Summary

**ArchiveWriter's count-or-time fsync cadence made directly inspectable (records_written/flush_count properties, injectable clock) and ArchiveRunner — the non-daemon thread draining FanOut's archive queue — proven to keep a deliberately slow sync entirely off the producer's critical path.**

## Performance

- **Duration:** 35 min (approx.)
- **Started:** 2026-08-01T19:53:00Z (approx., immediately following 01-05's completion)
- **Completed:** 2026-08-01T20:22:00Z
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- `ArchiveWriter` now exposes its cadence bookkeeping directly: `records_written` and `flush_count` read-only properties, plus an injectable `clock=` callable (defaulting to `time.monotonic`) so the time-based trigger is testable without sleeping — all state the tracer's writer already computed internally but never surfaced.
- `close()` was refactored to route its final, unconditional sync through the exact same `_flush_and_sync()` helper `add()` uses, rather than duplicating the flush+fsync sequence inline as the tracer's original implementation did — this is what makes `flush_count` correctly account for `close()`'s sync too, with no second counter or special-case.
- Both cadence trackers (`_records_since_flush`, `_last_flush_t`) reset together on every sync, verified by a dedicated test that arranges the exact condition where a stale time tracker would fire a spurious, redundant sync immediately after a count-triggered one in the same window — confirmed this does not happen.
- Empirically reverified (not assumed) this session, per ground-truth discipline: under the writer's default cadence, a single `add()` call leaves the file at 0 bytes on disk (Python's own `io.BufferedWriter` holds the write until flushed) — and with `flush_every_records=1`, that same single record produces a 202-byte file immediately readable through `recover_session` while the writer's file handle is still open. Both facts are now asserted directly in `test_one_record_reaches_disk_and_is_readable_before_close`, the mcap-default-chunking regression pin.
- `src/telemetry/archive/runner.py`'s `ArchiveRunner` is the archive queue's one consumer: a named, non-daemon thread that polls a shared `threading.Event` every loop iteration, drains via a public `STOP` sentinel, and — on either exit path — drains whatever remains queued before returning, so a shutdown never discards already-captured frames. Its exception handling deliberately departs from `new_logger.py`'s invisible, debug-only `except Exception: pass`-adjacent pattern: a writer failure is logged at critical severity with the frame's channel/id/extended-flag/timestamp, recorded on `FanOutCounters.archive_write_failure`, and re-raised after `stop_event` is set.
- `test_slow_sync_does_not_slow_the_producer_and_every_frame_still_lands` proves ARCH-04's real claim rather than merely asserting it: with the writer's sync patched to sleep 50 ms per call (`flush_every_records=1`, so every one of 40 submitted frames triggers a sync), every individual `FanOut.submit()` call on the producer's thread stayed under 25 ms — nowhere near the 50 ms sync cost sitting entirely on the runner thread — and all 40 frames were still recovered from the archive after the drain completed.
- `telemetry.capture.fanout` imports nothing from `telemetry.archive` — `ArchiveRunner` is the only file that imports across that boundary, in the archive→capture direction, keeping ARCH-04's "flushing never stalls capture" and CAP-04's "the telemetry consumer cannot backpressure the archive path" structural facts, not promises.

## Task Commits

1. **Task 1: Count-or-time flush cadence, sync accounting, and the unchunked-write pin** - `fcc9587` (feat)
2. **Task 2: The archive drain thread and the never-stalls-capture proof** - `fbf76a1` (feat)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `src/telemetry/archive/writer.py` — `records_written`/`flush_count` properties, injectable `clock=`, `close()` routed through `_flush_and_sync()`
- `src/telemetry/archive/runner.py` — `ArchiveRunner`, the archive queue's non-daemon consumer thread; public `STOP` sentinel
- `src/telemetry/capture/fanout.py` — `FanOutCounters` gains `archive_write_failure: bool = False`
- `tests/test_archive_writer.py` — filled in from its Wave-0 placeholder: 13 tests across both tasks (round-trip, cadence accounting, the chunking regression pin, sync-propagation, and the drain thread's four behaviors)

## Decisions Made

- **`flush_count`/`records_written` as public `@property`, mirroring `is_closed`'s existing shape** — the plan's action text names them as properties to expose, so this follows the module's own established convention rather than introducing a new access pattern.
- **`close()` refactored to call `_flush_and_sync()`** instead of keeping its own inline flush+fsync sequence — required for `flush_count` to be accurate without a parallel counter, and a small, clearly-scoped simplification of code the tracer wrote before these properties existed.
- **`ArchiveRunner`'s sentinel is named `STOP` (public)**, departing from `new_logger.py`'s file-local `_STOP` convention, because the sentinel here crosses a module boundary — a caller in `telemetry.archive.runner`'s importer (the eventual `01-10` CLI, and this plan's own tests) must be able to reference the same object to push it onto the queue, which a leading-underscore name would signal against.
- **`FanOutCounters.archive_write_failure` added to the existing dataclass** rather than a new archive-specific counters type, since the plan's own action text calls it "the counters object" (singular, shared) and `FanOutCounters` already tracks `archive_overflow` without any import from `telemetry.archive` — the precedent for archive-related fields living there without creating a reverse dependency was already established.
- **Test cadence values and queue sizes are always explicit literals**, never read from `config/logger.json`, per the plan's critical constraint 1 — channel *names* (`MAIN`/`SENSOR`) are reused from the real config for readability only, since names carry no cadence semantics a config tune could silently invalidate.

## Deviations from Plan

None — plan executed exactly as written. All four `<critical_constraints>` were followed precisely: the flush cadence stays batched by record-count-or-time (never made synchronous with capture); the Windows/Linux `os.fdatasync`/`os.fsync` platform branch remains the existing explicit `getattr` resolved once at construction, untouched and still verified this session to be `os.fdatasync` absent on the Windows dev box; `use_chunking=False` was kept exactly as the tracer set it, never touched; and every fact restated in `writer.py`'s docstring (the file-size-before-flush behavior, the cross-handle-read-while-open behavior) was reverified empirically this session against the real installed `mcap==1.4.0`, not carried forward from memory or from `01-04-SUMMARY.md`'s prose.

## Issues Encountered

None. The tracer's `ArchiveWriter` (01-04) already implemented the core cadence logic (`use_chunking=False`, count-or-time trigger, the `getattr(os, "fdatasync", os.fsync)` platform resolution) correctly — this plan's Task 1 work was making that logic inspectable and pinning its edge cases with tests, not rewriting it. The one empirical surprise, confirmed rather than assumed: a single `add()` call under the writer's *default* cadence (`flush_every_records=1000`, `flush_every_s=0.25`) leaves the file at 0 bytes on disk, because Python's own `io.BufferedWriter` holds unflushed small writes in userspace regardless of `mcap`'s `use_chunking=False` — the pin test therefore uses `flush_every_records=1` to force the cadence to fire on the single write being asserted, which is the correct scope for what that specific test is proving (unchunked writes reaching the stream immediately, not the cadence timing itself, which the other Task 1 tests already cover).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `ArchiveRunner` is ready for `01-10`'s logger CLI to start and join before process exit, per this plan's own `key_links` — the CLI's shutdown sequence needs only to set the shared `stop_event` and/or push `runner.STOP` (or `telemetry.archive.runner.STOP`) onto `fan_out.archive_queue`, then call `runner.join()` before calling `writer.close()`/`mark_done()`.
- `ARCH-04` is the only requirement this plan marks complete in `REQUIREMENTS.md`. `ARCH-01` is also claimed by `01-12` (the replay source plan) and `CAP-03` is also claimed by `01-07` and `01-13` — per this plan's own success criteria, neither is marked complete here even though both hold for everything this plan tested; the last plan to claim each ID marks it.
- `tests/test_fanout.py` remains `01-07`'s Wave-0 placeholder — this plan constructed real `FanOut` instances directly in `test_archive_writer.py` (since `FanOut` itself was already fully implemented by `01-04`), but ownership of `FanOut`'s own dedicated test file (fan-out capture/discard-counting proofs) is unchanged and still belongs to `01-07`.
- The Linux-only half of `ArchiveWriter`'s fsync cadence (`os.fdatasync`) remains untested on this dev box, exactly as `01-04-SUMMARY.md` already recorded as a known, non-blocking scope limit — `docs/power-pull-test.md` (`01-05`) is where that branch is actually proven, on real hardware.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*

## Self-Check: PASSED

All 4 created/modified source and test files (`src/telemetry/archive/runner.py`, `src/telemetry/archive/writer.py`, `src/telemetry/capture/fanout.py`, `tests/test_archive_writer.py`) and this SUMMARY.md were verified present on disk. All three commits (`fcc9587`, `fbf76a1`, `fb61580`) were verified present in `git log --oneline --all`. `python -m pytest tests/test_archive_writer.py -x -q --tb=short` (13 passed) and `python -m pytest -q -m "not slow"` (188 passed, 7 Wave-0 placeholder skips, 0 failures) were both re-confirmed green before this summary was finalized.
