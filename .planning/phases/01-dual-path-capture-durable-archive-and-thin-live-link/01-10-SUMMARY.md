---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 10
subsystem: telemetry-pipeline
tags: [threading, batching, cfr, cobs, archive, cli, config-driven, subprocess]

# Dependency graph
requires:
  - phase: 01-05
    provides: "telemetry.archive.session (new_session/mark_done), telemetry.archive.reader.recover_session -- the session lifecycle this CLI drives"
  - phase: 01-06
    provides: "telemetry.archive.runner.ArchiveRunner and its STOP sentinel -- the archive queue's non-daemon consumer thread this CLI starts and joins"
  - phase: 01-07
    provides: "FanOutCounters' full CAP-05/CAP-06 accounting (throughput, discard/filter, telemetry-path error counts) -- what this plan's shutdown summary reports"
  - phase: 01-08
    provides: "telemetry.link.udp.UdpLink and the shared Link Protocol -- the second link.kind this CLI can select"
  - phase: 01-09
    provides: "telemetry.capture.hardware_source.HardwareFrameSource -- the hardware frame source this CLI wires in for --source hardware"
provides:
  - "telemetry.logger.pipeline.TelemetryPipeline -- the telemetry-deque consumer thread: drain, batch (count/age/CFR-window), encode, frame, send, with named error counters for every failure mode"
  - "telemetry.logger.cli -- python -m telemetry.logger.cli, the single car-side entry point wiring FanOut/ArchiveRunner/TelemetryPipeline/HardwareFrameSource-or-SyntheticFrameSource together, config-driven end to end"
  - "tests/test_logger_cli_smoke.py filled in from its Wave-0 placeholder: 8 tests driving TelemetryPipeline directly against a real LoopbackLink+Deframer, plus 6 subprocess-level tests exercising the CLI as a real process"
affects: [01-13]

# Tech tracking
tech-stack:
  added: []  # no new dependencies; assembles existing telemetry.* modules
  patterns:
    - "TelemetryPipeline mirrors ArchiveRunner's thread discipline (named thread, poll the shared stop event, flush before returning) but is a daemon -- the live path carries no durability obligation, which is the entire point of the fan-out asymmetry"
    - "Batch closing races three conditions (count, age, CFR delta-t window); the window trigger is realized by catching wire.encoder.BatchWindowExceeded and re-encoding the triggering frame as the first record of a new batch, never by restating MAX_DELTA_T_US as a second literal"
    - "cli.py installs signal handlers before constructing ANY other resource (before even config load), not merely before starting threads -- resolves an internal ordering inconsistency in the plan's own action text (see Deviations)"
    - "cli.py's shutdown always runs (wrapped so a capture-loop exception cannot skip it): stop -> best-effort sentinel push (put_nowait, never blocking put, to avoid a shutdown deadlock on a full queue) -> join both consumer threads -> close link -> close writer -> mark_done only if archive_write_failure is false"
    - "The car-side CLI test suite runs as a real subprocess (python -m telemetry.logger.cli via subprocess.run with PYTHONPATH=src), not an in-process sys.argv monkeypatch -- the plan's literal instruction, and a stronger process-boundary proof than test_measure_cli_smoke.py's in-process shape"

key-files:
  created:
    - src/telemetry/logger/pipeline.py
    - src/telemetry/logger/cli.py
  modified:
    - tests/test_logger_cli_smoke.py

key-decisions:
  - "Signal handlers installed at the very start of main() -- before config load, DBC load, or allowlist resolution, not merely 'before starting any thread' as the plan's action text's first sentence implies. The plan's own two sentences on ordering contradict each other (see Deviations); the more specific, code-grounded instruction ('before starting any thread, following src/new_logger.py's ordering') is followed, and installing at the very top is the strictly safer superset of that requirement."
  - "Synthetic mode tags every frame with the first configured channel (config.channels[0].name) -- SyntheticFrameSource models per-message rate/entropy, not per-bus separation, so there is no principled way to split its single stream across two configured buses. Documented as a known limit in both pipeline.py's module docstring and cli.py's, not silently glossed over."
  - "--duration-s is enforced by an independent threading.Timer, not a per-iteration elapsed-time check in the capture loop's own thread. HardwareFrameSource.captured_frames() blocks internally between polls (stop_event.wait(timeout=poll_interval_s)) and only yields control back to the CLI's for-loop when it has a frame or exits -- a same-thread duration check can never fire while that generator is blocked waiting on a silent bus, so only a separate thread can guarantee the wall-clock bound."
  - "The archive queue's shutdown sentinel is pushed with put_nowait (catching queue.Full), never a blocking put -- a blocking put after the archive runner has already drained and returned (stop_event already set) would deadlock the shutdown sequence with no one left to make room."
  - "mark_done is gated on `not fan_out.counters.archive_write_failure` in addition to writer.close() succeeding -- a write failure inside ArchiveRunner's thread sets this flag and re-raises (crashing only that thread, invisibly to the main thread), so close() succeeding alone is not sufficient evidence the archive is trustworthy; both must hold for a session to be marked done (ARCH-05)."
  - "archive_drops is reported as a literal 0 in the JSON summary, not a derived count -- CAP-03's own structural guarantee is that the archive queue never silently drops a frame; it either accepts every submission or the whole session stops (archive_overflow), so there is no quantity to count that isn't already covered by archive_overflow/archive_write_failure."

requirements-completed: [OPS-04]
# CAP-01 is also claimed by 01-12 (later plan, not yet run) -- not marked here.
# CAP-05/CAP-06 are also claimed by 01-13 (later plan, not yet run) -- not marked here.
# OPS-05 is also claimed by 01-11 and 01-12 (later plans, not yet run) -- not marked here.
# OPS-04 is claimed by 01-03/01-04/01-05/01-10's requirements frontmatter and by no later
# plan -- 01-10 is the last claimant, so it is marked complete here. Its REQUIREMENTS.md
# checkbox was already [x] (set prematurely by 01-04's own requirements-completed list,
# the same pre-existing pattern 01-07-SUMMARY.md documented for CAP-04); this plan's own
# `requirements mark-complete` call is what makes ROADMAP.md's traceability table agree.

coverage:
  - id: D1
    description: "A batch closes at the configured frame count, on age when fewer than the configured count have arrived, and early when the next frame's timestamp would exceed the CFR delta-t window -- with the triggering frame opening the next batch rather than being dropped -- and every case round-trips through a real LoopbackLink and Deframer"
    requirement: "CAP-05"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_smoke.py#test_batch_closes_at_configured_frame_count"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_smoke.py#test_batch_closes_on_age_when_fewer_than_configured_count_have_arrived"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_smoke.py#test_batch_closes_early_on_cfr_window_and_triggering_frame_opens_next_batch"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_smoke.py#test_batch_sequence_numbers_advance_and_wrap_in_order"
        status: pass
    human_judgment: false
  - id: D2
    description: "Encoder rejections (unknown id, over-length payload) are each counted on their own named field, logged with frame context, and skipped without taking the batch or the thread down; a link send failure is counted, logged, and the pipeline continues"
    requirement: "CAP-06"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_smoke.py#test_encoder_rejections_counted_logged_with_context_and_skipped"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_smoke.py#test_link_send_failure_counted_logged_and_pipeline_continues"
        status: pass
    human_judgment: false
  - id: D3
    description: "On the stop event the pipeline flushes the batch already drained from the deque before exiting, and reports frames sent, batches sent, and bytes sent"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_smoke.py#test_stop_event_flushes_batch_in_progress"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_smoke.py#test_pipeline_reports_frames_batches_and_bytes_sent"
        status: pass
    human_judgment: false
  - id: D4
    description: "python -m telemetry.logger.cli, run as a real subprocess with the synthetic source, a loopback link, a bounded duration, and a temporary archive root, exits zero and leaves exactly one session directory containing a non-empty .mcap, a .done marker, and the sidecar, readable back through recover_session"
    requirement: "OPS-05"
    verification:
      - kind: integration
        ref: "tests/test_logger_cli_smoke.py#test_cli_synthetic_run_exits_zero_with_a_complete_session"
        status: pass
    human_judgment: false
  - id: D5
    description: "The CLI's stdout is a single JSON summary reporting zero archive-path drops, non-zero frames captured/archived, and both queues' high-water marks"
    requirement: "CAP-05"
    verification:
      - kind: integration
        ref: "tests/test_logger_cli_smoke.py#test_cli_stdout_summary_parses_as_json_and_reports_expected_fields"
        status: pass
    human_judgment: false
  - id: D6
    description: "Two consecutive CLI runs against the same archive root land in two distinct session directories"
    requirement: "OPS-04"
    verification:
      - kind: integration
        ref: "tests/test_logger_cli_smoke.py#test_cli_two_consecutive_runs_produce_two_distinct_session_directories"
        status: pass
    human_judgment: false
  - id: D7
    description: "An unknown key in a copy of the config makes the CLI exit non-zero naming the key and creates no session directory at all; a missing config path exits non-zero naming the path"
    requirement: "OPS-05"
    verification:
      - kind: integration
        ref: "tests/test_logger_cli_smoke.py#test_cli_unknown_config_key_exits_nonzero_and_creates_no_session"
        status: pass
      - kind: integration
        ref: "tests/test_logger_cli_smoke.py#test_cli_missing_config_path_exits_nonzero_naming_the_path"
        status: pass
    human_judgment: false
  - id: D8
    description: "A CLI flag overriding a single config field (archive root) takes effect while every other field (link kind) stays at its configured value"
    requirement: "OPS-05"
    verification:
      - kind: integration
        ref: "tests/test_logger_cli_smoke.py#test_cli_archive_root_override_takes_effect_other_fields_unchanged"
        status: pass
    human_judgment: false
  - id: D9
    description: "Dual-bus hardware capture through the assembled CLI, real signal handling under a real SIGINT/SIGTERM, and a real UDP link end to end -- not exercisable without the neoVI PI attached, and not part of this plan's own <verify> scope"
    requirement: "CAP-01"
    verification: []
    human_judgment: true
    rationale: "01-VALIDATION.md already lists dual-bus hardware capture as manual-only (established in 01-09); this plan only adds the CLI wiring around an already-manual-only capture layer, and does not introduce a new automatable surface for it."

# Metrics
duration: 55min
completed: 2026-08-02
status: complete
---

# Phase 1 Plan 10: The Car-Side Logger Assembly -- Pipeline Thread and CLI Summary

**`python -m telemetry.logger.cli` runs a complete, config-driven session end to end (capture, dual-queue fan-out, durable MCAP archive, and a batching/framing/sending TelemetryPipeline thread over a swappable link), with a JSON shutdown report surfacing every CAP-05/CAP-06 counter -- runnable and subprocess-testable with no hardware attached via a synthetic frame source.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-08-02 (approx., immediately following 01-09's completion)
- **Completed:** 2026-08-02
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 rewritten from its Wave-0 placeholder)

## Accomplishments

- `src/telemetry/logger/pipeline.py`'s `TelemetryPipeline` is the telemetry deque's consumer thread: it drains, batches, CFR-encodes, frames (CRC-16+COBS), and sends over the configured `Link`, closing each batch on whichever of frame count, max age, or the CFR delta-t window comes first. The window trigger is realized by catching `wire.encoder.BatchWindowExceeded` and re-encoding the triggering frame as the first record of a fresh batch -- a correctness requirement per `01-CONTEXT.md`'s critical constraint #2, proven directly by constructing two frames separated by more than `MAX_DELTA_T_US` and confirming both arrive across two batches.
- Every encode/frame/send failure is caught by its specific type (`PayloadTooLong`, `UnknownFrameId`, any other `CfrError`, `FramingError`, or a bare `Link.send()` exception), counted on its own named `TelemetryPipelineCounters` field, and logged with frame or batch context -- none of them can terminate the thread or reach the archive path (T-01-26), proven by a fake link whose `send()` always raises and a pair of deliberately unencodable frames mixed into an otherwise-good stream.
- On the stop event, the batch already drained from the deque is flushed before the thread returns -- proven by starting a pipeline with one queued frame, letting it drain into an open (not-yet-closed) batch, then confirming it still arrives after `stop_event.set()`.
- `src/telemetry/logger/cli.py`'s `main()` is the single car-side entry point: it loads and validates `config/logger.json` (or `--config`), resolves the allowlist against the DBC, creates the session, opens the archive writer, builds the configured `Link`/`FanOut`/`ArchiveRunner`/`TelemetryPipeline`, and runs the capture loop with either `HardwareFrameSource` (CAP-01's dual-bus, one-device-handle capture from 01-09) or `SyntheticFrameSource` (`--source synthetic`) -- the latter making the whole process runnable and subprocess-testable with no neoVI PI attached.
- Signal handlers for `SIGINT`/`SIGTERM` are installed before any other resource is constructed -- before config is even loaded -- so a signal mid-startup can never leave a half-built process with an open archive. This resolves an internal contradiction in the plan's own action text (see Deviations).
- Shutdown is strict order and always runs, even if the capture loop raised: stop the capture (`stop_event`), best-effort-push the archive runner's `STOP` sentinel (`put_nowait`, never a blocking `put`, to avoid a shutdown deadlock on a full queue with no one left to drain it), join the archive runner and the telemetry pipeline, close the link, close the writer, then call `mark_done` **only if** the writer closed cleanly **and** `FanOutCounters.archive_write_failure` is false -- an interrupted or failed session is left without its `.done` marker on purpose (ARCH-05).
- The CLI emits two outputs at shutdown from the same counters: a human-readable report to stderr (`_log_human_summary`) and one line of JSON to stdout (`_build_summary`) -- frames captured/archived/sent, both queues' high-water marks, telemetry discards/filtered/error counts, and every pipeline error counter. Stdout carries nothing else.
- `tests/test_logger_cli_smoke.py` replaces 01-02's placeholder skip with 14 tests: 8 driving `TelemetryPipeline` directly against a real `LoopbackLink`+`Deframer` (Task 1), and 6 running the CLI as a real subprocess (`python -m telemetry.logger.cli` via `subprocess.run`, `PYTHONPATH=src`) per the plan's literal instruction -- a complete synthetic run, the JSON summary's fields, two consecutive runs landing in distinct sessions (OPS-04), a rejected unknown config key creating no session directory at all, a config-field override leaving every other field configured, and a missing config path naming itself in the error.

## Task Commits

1. **Task 1: The telemetry pipeline thread -- drain, batch, encode, frame, send** - `526cf61` (feat)
2. **Task 2: The car-side CLI entry point and its shutdown report** - `cae1998` (feat)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `src/telemetry/logger/pipeline.py` -- `TelemetryPipeline`, `TelemetryPipelineCounters`; the telemetry deque's consumer thread
- `src/telemetry/logger/cli.py` -- `main()` and its helpers; the car-side entry point
- `tests/test_logger_cli_smoke.py` -- replaces 01-02's placeholder skip; 14 tests across both tasks

## Decisions Made

- **Signal handlers installed at the very top of `main()`**, before config load -- stricter than "before starting any thread" (see Deviations for why the plan's own text needed this resolution).
- **Synthetic mode tags every frame with `config.channels[0].name`.** `SyntheticFrameSource` models per-message rate and entropy, not per-bus separation, so there is no principled way to split its single generated stream across two configured buses; documented as a known limit in both new modules' docstrings rather than silently assumed.
- **`--duration-s` is enforced by an independent `threading.Timer`**, not a same-thread elapsed-time check. `HardwareFrameSource.captured_frames()` blocks internally between polls; a same-thread check can never fire while that generator is blocked waiting on a silent bus, so only a separate thread guarantees the wall-clock bound.
- **The archive queue's shutdown sentinel uses `put_nowait`/catch-`queue.Full`, never a blocking `put`.** A blocking put issued after the archive runner has already drained and returned (because `stop_event` was already set) would deadlock the shutdown sequence.
- **`mark_done` requires both `writer.close()` to succeed AND `archive_write_failure` to be false.** A write failure inside `ArchiveRunner`'s own thread sets the flag and re-raises there (invisible to the main thread); `writer.close()` succeeding alone is not sufficient evidence the archive is trustworthy.
- **`archive_drops` is reported as a literal `0`, not a derived count** -- CAP-03's structural guarantee (the archive queue never silently drops) means there is no quantity to count that `archive_overflow`/`archive_write_failure` don't already cover.
- **The car-side CLI tests run as real subprocesses** (`subprocess.run([sys.executable, "-m", "telemetry.logger.cli", ...])`), per the plan's literal instruction, rather than `test_measure_cli_smoke.py`'s in-process `sys.argv` monkeypatch shape -- a stronger process-boundary proof, at the cost of ~4s of subprocess overhead across the six CLI tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Resolved a self-contradicting instruction in the plan's own Task 2 action text**
- **Found during:** Task 2, writing `cli.py`'s startup sequence
- **Issue:** The action text's first sentence lists signal-handler installation *after* "start the archive runner and the telemetry pipeline" in the wiring order; its very next sentence says "Install the signal handlers before starting any thread, following `src/new_logger.py`'s ordering." These two sentences describe different orderings and cannot both be followed literally.
- **Fix:** Followed the more specific, code-grounded instruction (matching `src/new_logger.py` lines 329-332's actual, verified ordering) and went one step further: signal handlers are installed at the very start of `main()`, before config load, DBC load, or allowlist resolution -- a strict superset of "before starting any thread" that also covers a signal arriving during those earlier steps, none of which construct anything that needs unwinding.
- **Files modified:** `src/telemetry/logger/cli.py`
- **Verification:** No test exercises real signal delivery (out of this plan's `<verify>` scope, matching how `01-09` left real-hardware dual-bus capture manual-only); the ordering itself is a direct code read, not a behavioral claim needing a test.
- **Committed in:** `cae1998` (Task 2 commit)

**2. [Rule 1 - Bug] Fixed a delimiter-stripping bug in a test, not the implementation**
- **Found during:** Task 1, `test_batch_sequence_numbers_advance_and_wrap_in_order`
- **Issue:** The test called `unframe(received)` directly on what `LoopbackLink.recv()` returned -- but `unframe`'s documented contract expects the trailing `0x00` COBS delimiter already stripped (normally `Deframer.feed`'s job), and `link.recv()` returns exactly what `TelemetryPipeline` sent, delimiter included. `cobs.decode` raised `zero byte found in input`.
- **Fix:** Stripped the trailing delimiter byte before calling `unframe` (`unframe(received[:-1])`), with a comment explaining why -- a test-only correction, not a production code change.
- **Files modified:** `tests/test_logger_cli_smoke.py`
- **Verification:** Test passes; the fix follows `unframe`'s own docstring contract exactly.
- **Committed in:** `526cf61` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs -- one a plan-text ordering contradiction resolved in code, one a self-caught test bug)
**Impact on plan:** No scope creep. Both fixes are correctness-preserving; neither changed any tested behavior's shape.

## Issues Encountered

None beyond the two deviations above, both caught and fixed within the same session before either task's commit.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- `01-13`'s soak test (CAP-02, CAP-03, CAP-05, CAP-06) is the next plan to depend on this one -- it drives real code through this same CLI/pipeline assembly at sustained full-combined-bus rate.
- `01-11` (the headless ground-station CLI) and `01-12` (the replay source) both also claim `OPS-05` and, for `01-12`, `CAP-01` -- neither is marked complete here; per this plan's own success criteria and the invoking prompt's explicit instruction, only `OPS-04` (whose last claimant is this plan) was marked complete in `REQUIREMENTS.md`.
- Real hardware dual-bus capture through the assembled CLI, and a real UDP link end to end between two separate processes, remain manual-only per `01-VALIDATION.md`'s existing scope (established in `01-09`) -- this plan adds CLI wiring around an already-manual-only capture layer and a link `01-08` already proved against a shared test suite; it does not introduce new automatable surface for either.
- No blockers.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-02*

## Self-Check: PASSED

`src/telemetry/logger/pipeline.py`, `src/telemetry/logger/cli.py`, and this SUMMARY.md were verified present on disk. Both task commits (`526cf61`, `cae1998`) were verified present in `git log --oneline --all`. `python -m pytest tests/test_logger_cli_smoke.py -x -q --tb=short` (14 passed) and `python -m pytest -q -m "not slow"` (263 passed, 2 skipped -- both remaining skips are placeholders explicitly owned by 01-12/01-13) were both re-confirmed green before this summary was finalized.
