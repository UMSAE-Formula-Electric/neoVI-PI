---
phase: 03-unattended-on-car-operation
plan: 04
subsystem: infra
tags: [ops, hardware-wait, heartbeat, backoff, ics, boot-race]

# Dependency graph
requires:
  - phase: 03-01
    provides: "HeartbeatPublisher/HeartbeatSnapshot/publish_now, STATE_BOOTING/STATE_WAITING_FOR_HARDWARE/STATE_CAPTURING/STATE_DEGRADED/STATE_STOPPED_ERROR (the waiting-for-hardware and stopped-error states this plan is the first to actually drive)"
  - phase: 03-02
    provides: "check_disk_space_fn injectable-seam convention on main()/_run_session(), the disk gate's ordering precedent (run before _run_session, since _run_session calls new_session())"
  - phase: 01
    provides: "HardwareFrameSource's established SDK-injection/lazy-import pattern and the sdk.RuntimeError-never-the-builtin catch shape this plan copies verbatim"
provides:
  - "src/telemetry/ops/hardware_wait.py: wait_for_hardware(stop_event, on_waiting, sdk, initial_backoff_s, max_backoff_s) -> bool -- indefinite retry with exponential backoff, no timeout, stop_event is the only exit"
  - "telemetry.logger.cli main(): the OPS-01 boot race, run after the disk gate and before _run_session, publishing waiting-for-hardware on every retry and returning cleanly (exit 0, status file removed) if stop_event fires while waiting"
  - "telemetry.logger.cli main(): DBC-load and allowlist-resolution failures now publish a stopped-error snapshot before their raise SystemExit(1)"
  - "telemetry.logger.cli _run_session(): an unconditional terminal heartbeat-state decision after shutdown -- stopped-error naming the failing condition(s) and left in place for any bad ending, file removed only on a genuinely clean finish"
affects: ["03-05 (sole OPS-02 marker)", "03-07 (sole OPS-01 marker, and the runbook must document the config-load-failure asymmetry)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Retry-with-backoff seam mirrors hardware_source.py's lazy _default_sdk()/sdk.RuntimeError-never-the-builtin pattern exactly, including the explanatory comment, rather than paraphrasing it"
    - "wait_for_hardware_fn injectable keyword on main() (default: the real wait_for_hardware), following the same convention as 03-02's check_disk_space_fn -- a test's fake receives the real stop_event object by reference and can call .set() on it itself to simulate an operator-initiated stop"
    - "HardwareFrameSource substitution via monkeypatch.setattr on the name imported into telemetry.logger.cli, not a new production-code sdk seam -- keeps the only new production seam scoped to the wait itself, per the plan's own instruction"
    - "Publisher thread stopped (joined) BEFORE the terminal synchronous write, in both the clean and bad-ending branches, so a periodic capturing tick can never race ahead of the terminal state"

key-files:
  created:
    - src/telemetry/ops/hardware_wait.py
    - tests/test_ops_hardware_wait.py
  modified:
    - src/telemetry/logger/cli.py
    - tests/test_logger_cli_ops.py
    - tests/test_ops_tracer.py

key-decisions:
  - "wait_for_hardware runs in main(), strictly after the disk gate and strictly before _run_session -- never inside _run_session, because _run_session calls new_session() first and HardwareFrameSource.captured_frames() lazily calls open(), which fails fast with no retry"
  - "Both a caught sdk.RuntimeError and an empty devices tuple are treated identically as not-present-yet, per 03-RESEARCH.md Pattern 4's own instruction, since only the RuntimeError case is independently verified live and the empty-tuple case is inferred from already-merged code"
  - "No timeout parameter, no maximum attempt count on wait_for_hardware -- stop_event is the only exit, since waiting indefinitely for the bus to power up is correct car behaviour, not a fault"
  - "Terminal-state detail names ALL failing conditions that fired (capture_loop_exception, archive_not_closed_cleanly, archive_write_failure, archive_overflow), not just the first one found, so a human reading the file sees the full picture"
  - "Testing the boot race needed no ics-shaped fake SDK object at all: a wait_for_hardware_fn double plus monkeypatching HardwareFrameSource (not a new production sdk= seam) fully exercises main()'s state machine without touching telemetry.capture.hardware_source"
  - "Rule 1 fix to tests/test_ops_tracer.py (outside this plan's own files_modified): --duration-s 120 against the shipped queue_depth=50000 was measured this session to deterministically overflow the archive queue in under 2 real seconds (SyntheticFrameSource has no per-frame throttle, per 03-02's finding) -- previously invisible because a bad ending left the heartbeat file showing a stale prior state, and now correctly surfaced as stopped-error by this plan's terminal write. Fixed by raising that one test's queue_depth to 2,000,000 so the run takes ~11s to legitimately finish instead of overflowing"

patterns-established:
  - "A hardware-presence probe's retry loop is testable end to end with zero SDK-shaped fakes: a plain wait_for_hardware_fn callable that receives the real stop_event by reference is sufficient to drive and observe every state transition"

requirements-completed: []  # Marks: none, per this plan's own frontmatter. OPS-01's status is decided by 03-07; OPS-02 is marked by 03-05. .planning/REQUIREMENTS.md is untouched by this plan.

coverage:
  - id: D1
    description: "wait_for_hardware retries on both sdk.RuntimeError (caught via the injected SDK's own attribute, never the builtin) and an empty devices tuple, calls on_waiting with the attempt number and backoff before each wait, and returns True once a device is found"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_ops_hardware_wait.py#test_devices_found_on_first_call_returns_true_immediately_and_never_waits"
        status: pass
      - kind: unit
        ref: "tests/test_ops_hardware_wait.py#test_two_empty_tuples_then_devices_returns_true_after_exactly_three_calls"
        status: pass
      - kind: unit
        ref: "tests/test_ops_hardware_wait.py#test_sdk_owned_runtime_error_is_treated_as_not_present_yet_and_retried"
        status: pass
      - kind: unit
        ref: "tests/test_ops_hardware_wait.py#test_on_waiting_receives_attempt_number_and_backoff_about_to_be_waited"
        status: pass
    human_judgment: false
  - id: D2
    description: "A non-SDK-owned exception propagates rather than being swallowed; a stop_event firing mid-wait returns False promptly with backoff bounded and growing, clamped at max_backoff_s"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_ops_hardware_wait.py#test_non_sdk_exception_propagates_rather_than_being_swallowed"
        status: pass
      - kind: unit
        ref: "tests/test_ops_hardware_wait.py#test_stop_event_firing_while_waiting_returns_false_promptly"
        status: pass
      - kind: unit
        ref: "tests/test_ops_hardware_wait.py#test_backoff_grows_from_initial_and_is_clamped_at_max"
        status: pass
      - kind: unit
        ref: "tests/test_ops_hardware_wait.py#test_real_threading_event_is_interrupted_promptly_not_waited_out"
        status: pass
    human_judgment: false
  - id: D3
    description: "main() with --source hardware creates no session directory while waiting-for-hardware, and recovers to capturing once a device is found; stop_event firing while waiting exits 0 and removes the status file; --source synthetic never calls wait_for_hardware"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_hardware_boot_race_waits_then_recovers_to_capturing"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_hardware_boot_race_stop_event_exits_zero_and_removes_status_file"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_synthetic_source_never_calls_wait_for_hardware"
        status: pass
    human_judgment: false
  - id: D4
    description: "A clean finish leaves no status file; an archive overflow or a capture-loop exception each leave a stopped-error file naming the condition and are NOT removed, even when the writer itself closed without error"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_clean_finish_leaves_no_status_file"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_archive_overflow_leaves_stopped_error_status_file_naming_condition"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_capture_loop_exception_leaves_stopped_error_even_if_writer_closed_cleanly"
        status: pass
    human_judgment: false
  - id: D5
    description: "A DBC-load or allowlist-resolution failure publishes stopped-error before SystemExit(1); a config-load failure publishes nothing, since heartbeat_path is not yet known"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_dbc_load_failure_publishes_stopped_error_before_exit"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_allowlist_resolution_failure_publishes_stopped_error_before_exit"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_config_load_failure_publishes_no_status_file"
        status: pass
    human_judgment: false

# Metrics
duration: 45min
completed: 2026-09-30
status: complete
---

# Phase 3 Plan 4: Hardware-Presence Wait and Terminal Heartbeat State Summary

**`telemetry.ops.hardware_wait.wait_for_hardware` (indefinite retry with exponential backoff, catching the SDK's own exception type never the builtin) wired into `telemetry.logger.cli` ahead of session creation, plus an unconditional terminal heartbeat-state write on every exit path — clean finishes remove the status file, every bad ending leaves one naming exactly which condition fired.**

## Performance

- **Duration:** ~45 min
- **Tasks:** 2 (Task 1 `hardware_wait` module, Task 2 wiring + terminal state)
- **Files modified:** 3 modified (`src/telemetry/logger/cli.py`, `tests/test_logger_cli_ops.py`, `tests/test_ops_tracer.py`), 2 created (`src/telemetry/ops/hardware_wait.py`, `tests/test_ops_hardware_wait.py`)

## Accomplishments

- `src/telemetry/ops/hardware_wait.py` built: `wait_for_hardware(*, stop_event, on_waiting, sdk, initial_backoff_s, max_backoff_s) -> bool` — no timeout, no attempt cap, `stop_event` is the only exit. Catches `sdk.RuntimeError` via the injected SDK object's own attribute, copying `hardware_source.py`'s reasoning verbatim (never the builtin — `ics.RuntimeError` does not subclass it, re-verified live in `03-RESEARCH.md`). Both a caught SDK error and an empty devices tuple are treated identically as "not present yet." Backoff doubles from `initial_backoff_s`, clamped at `max_backoff_s`, waited via `stop_event.wait(timeout=...)` so a stop signal interrupts immediately.
- `telemetry.logger.cli main()` wired the boot race: for `--source hardware`, `wait_for_hardware_fn` (injectable, default the real function) runs after the disk gate and before `_run_session`, publishing `waiting-for-hardware` on every retry via `on_waiting`. If `stop_event` fires while waiting, the status file is removed and `main()` returns cleanly (exit 0) with no session ever created. `--source synthetic` never calls it at all.
- `telemetry.logger.cli main()`'s DBC-load and allowlist-resolution failure branches now publish a `stopped-error` snapshot naming the failure before their `raise SystemExit(1)`; the config-load failure branch is deliberately left untouched, since `config.ops.heartbeat_path` is not yet known at that point.
- `telemetry.logger.cli _run_session()` now decides a terminal heartbeat state after its existing shutdown block and `_log_human_summary`: the publisher thread is stopped first (so a periodic `capturing` tick can never race ahead of the terminal write), then a `stopped-error` snapshot naming every failing condition that fired (`capture_loop_exception`, `archive_not_closed_cleanly`, `archive_write_failure`, `archive_overflow`) is published and left in place on any bad ending; a genuinely clean finish removes the file instead.
- 10 new unit tests for `wait_for_hardware` (hand-rolled fake SDK, builtin-shadowing `RuntimeError` included, zero real sleeps) and 9 new tests in `tests/test_logger_cli_ops.py` covering the full boot-race and terminal-state state machine at the `main()` level, using a `wait_for_hardware_fn` double plus a monkeypatched `HardwareFrameSource` rather than a new production `sdk=` seam.

## Task Commits

Each task was committed atomically:

1. **Task 1: `telemetry.ops.hardware_wait`** - `db1d35a` (feat)
2. **Task 2: Wire the boot race and terminal state into `logger/cli.py`** - `397317f` (feat, includes the `tests/test_ops_tracer.py` Rule 1 fix)

**Plan metadata:** (this commit, see below)

## Files Created/Modified

- `src/telemetry/ops/hardware_wait.py` - `wait_for_hardware`, `_default_sdk` (lazy `ics` import, mirroring `hardware_source.py`)
- `tests/test_ops_hardware_wait.py` - 10 unit tests: first-call success, retry-then-success, SDK-owned-error retry, non-SDK-exception propagation, prompt stop, backoff growth/clamp, `on_waiting` payload, no-SDK-import-on-module-import, a real-`threading.Event` end-to-end interruption check
- `src/telemetry/logger/cli.py` - module docstring extended for OPS-01; `main()` gained `wait_for_hardware_fn`, the boot-race call site, and `stopped-error` publishes on DBC-load/allowlist-resolution failure; `_run_session()` gained the `capture_failed` flag and the unconditional terminal-state decision, publisher joined before the terminal write in both branches
- `tests/test_logger_cli_ops.py` - `_write_config_with_short_heartbeat`, `_FakeHardwareFrameSource`, `_ControllableWait` helpers, plus 9 new tests spanning the boot race and every terminal-state path
- `tests/test_ops_tracer.py` - `_write_config_with_large_queue_depth` helper and its use in the one real-subprocess test that was overflowing the default archive queue at `--duration-s 120` (Rule 1 fix, see Deviations)

## Decisions Made

- **`wait_for_hardware` runs in `main()`, strictly after the disk gate and strictly before `_run_session`.** `_run_session` calls `new_session()` first, and `HardwareFrameSource.captured_frames()` lazily calls `open()`, which fails fast with no retry — waiting inside `_run_session` would leave an empty session directory behind on every unpowered boot.
- **Both a caught `sdk.RuntimeError` and an empty devices tuple are treated identically.** `03-RESEARCH.md` Pattern 4 verified the exception case live but only inferred the empty-tuple case from already-merged code; handling both the same way makes that open question harmless regardless of which is actually true on the CM4 — confirm on first real Pi bring-up.
- **No timeout, no attempt cap.** Waiting indefinitely for the bus to power up is correct car behaviour, not a fault; `stop_event` is the only exit, per `03-CONTEXT.md`'s locked decision D.
- **The terminal-state detail names every failing condition that fired, not just the first.** A human reading the file after the fact should see the full picture (capture exception AND an archive overflow, if both happened) rather than a truncated guess.
- **No new `sdk=` seam was added to `HardwareFrameSource`'s call site in `_run_session`.** The plan's action text only calls for an injectable seam on "the wait." Testing the full boot-race state machine (waiting → capturing) needed no `ics`-shaped fake SDK at all: a `wait_for_hardware_fn` double (which receives the real `stop_event` by reference and can call `.set()` on it itself) plus `monkeypatch.setattr` on the `HardwareFrameSource` name imported into `telemetry.logger.cli` fully exercises the state machine without touching `telemetry.capture.hardware_source` or adding a production-code seam beyond what the plan specified.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `tests/test_ops_tracer.py`'s `--duration-s 120` deterministically overflowed the archive queue**
- **Found during:** Task 2's full-suite verification run (`python -m pytest -q`), after Task 2's terminal-state write was committed
- **Issue:** `test_running_logger_reports_capturing_via_a_separate_status_process` (a real two-process subprocess test from 03-01) started intermittently/consistently failing its second, human-readable status check. Measured directly this session: running `python -m telemetry.logger.cli --source synthetic --duration-s 120` against the shipped `archive.queue_depth=50000` produces `archive_overflow=True` in under 2 real seconds, every time — `telemetry.synth.generator.SyntheticFrameSource` has no per-frame real-time throttle (an already-recorded 03-02 finding), so `--duration-s 120` generates its full ~450,000-frame burst essentially as fast as Python can loop, far outrunning what a queue depth of 50,000 can absorb before the archive consumer thread (doing real fsync'd disk I/O) drains it. This race existed before this plan too, but was invisible: the old shutdown path left the heartbeat file showing whatever state its last periodic tick had written (a stale `capturing`), so the test's second check kept passing by accident. This plan's new unconditional terminal write correctly overwrites that stale state with `stopped-error`, which is what surfaced the test's latent assumption as false.
- **Fix:** Added `_write_config_with_large_queue_depth` to `tests/test_ops_tracer.py`, writing a copy of the shipped config with `archive.queue_depth` raised to 2,000,000. Measured this session: the same `--duration-s 120` run against that config takes ~11.4 real seconds to legitimately archive its full 447,652-frame burst and exit cleanly (no overflow) — comfortably long enough for the test's 30-second poll budget to observe `capturing`, and comfortably longer than the brief window between that observation and the immediate follow-up human-readable check.
- **Files modified:** `tests/test_ops_tracer.py` (not in this plan's own `files_modified:` list, but directly caused by this plan's own change — the terminal write is doing exactly what it should, and the test's assumption needed correcting to match)
- **Verification:** `tests/test_ops_tracer.py` run 3 times in a row after the fix, all green; full suite `python -m pytest -q` green at 397 passing
- **Committed in:** `397317f` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 bug fix, test-only, no production behavior change)
**Impact on plan:** No scope creep in production code. The fix is a test-infrastructure correction made necessary by this plan's own (intended) correctness improvement — the plan's terminal-state write is exactly what surfaced a pre-existing latent test race.

## Issues Encountered

- The plan's `<read_first>` and `<action>` text for Task 2 could be read as needing a new `hardware_sdk=` seam threaded into `_run_session`'s `HardwareFrameSource` construction, to let a single fake SDK object drive both the wait and the subsequent real capture in one test. Investigated by tracing exactly what `main()`'s existing `wait_for_hardware_fn` seam can already do (it receives the real `stop_event` by reference, so a test double can control it directly) and concluded no such SDK-shaped seam was needed — `monkeypatch.setattr` on the `HardwareFrameSource` name imported into `telemetry.logger.cli` achieves the same effect at zero production-code cost, keeping the only new seam scoped to exactly what the plan's action text specifies ("Accept an injectable seam for the wait").

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `waiting-for-hardware` and `stopped-error` are now genuinely driven by `telemetry.logger.cli`, not just defined as constants in `telemetry.ops.heartbeat` — both are exercised end to end.
- 03-05 remains the sole owner of marking OPS-02 Complete in `.planning/REQUIREMENTS.md`; 03-07 remains the sole owner of OPS-01 (and must document the config-load-failure asymmetry — a service running with no status file at all means the config failed to parse, and the journal is where the reason is).
- The empty-tuple-vs-exception open question (`sdk.find_devices()`'s exact behaviour on Linux with the driver present but zero devices attached) is carried forward unresolved from `03-RESEARCH.md` — this plan's `wait_for_hardware` handles both identically on purpose, so the gap does not block anything, but it should still be confirmed on first real Pi bring-up (the same UAT item that already covers dual-bus hardware capture and the `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED` constant).
- No blockers. Full suite: 378 → 397 passing (+19: 10 `hardware_wait` unit tests, 9 `logger_cli_ops` tests). `git diff --exit-code -- requirements.txt` confirmed clean (no new runtime dependency).

---
*Phase: 03-unattended-on-car-operation*
*Completed: 2026-09-30*
