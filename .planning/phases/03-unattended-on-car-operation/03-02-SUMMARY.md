---
phase: 03-unattended-on-car-operation
plan: 02
subsystem: infra
tags: [ops, disk-space, heartbeat, config, cli, shutil.disk_usage]

# Dependency graph
requires:
  - phase: 03-unattended-on-car-operation
    provides: "03-01's HeartbeatPublisher/HeartbeatSnapshot/snapshot_fn seam, STATE_BOOTING/STATE_CAPTURING/STATE_DEGRADED/STATE_STOPPED_ERROR, and OpsConfig.disk_warn_free_bytes/disk_critical_free_bytes already validated in config/logger.json"
provides:
  - "src/telemetry/ops/disk_monitor.py: DiskReading, DISK_OK/DISK_WARN/DISK_CRITICAL, check_disk_space (two-stage strictly-less-than banding against a nearest-existing-ancestor path)"
  - "telemetry.logger.cli main() startup gate: refuses a new session below critical, logs the free-space line in every band, publishes a final stopped-error heartbeat on refusal"
  - "telemetry.logger.cli _run_session()'s snapshot_fn closure: mid-run disk recheck attached to the existing 1 Hz heartbeat tick, reporting degraded (never stopping the run) with a rate-limited loud log"
  - "check_disk_space_fn and now_fn injectable keyword parameters on both main() and _run_session(), following the project's established injectable-callable convention"
affects: [03-05-ops-02-marking, 03-07-runbook]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Nearest-existing-ancestor path resolution before an OS free-space call, never creating the missing leaf directory itself"
    - "Rate-limited loud log: log immediately on every band transition, then at most once per a module constant interval while the band persists, tracked as (last_band, last_logged_at) inside the same closure that already ticks at 1 Hz -- no second timer thread"
    - "Injectable now_fn on a closure that is only ever called from one background thread after setup, so a deterministic fake clock needs no lock to drive rate-limiting logic without a real sleep"

key-files:
  created:
    - src/telemetry/ops/disk_monitor.py
    - tests/test_ops_disk_monitor.py
    - tests/test_logger_cli_ops.py
  modified:
    - src/telemetry/logger/cli.py

key-decisions:
  - "check_disk_space compares free_bytes directly against the two configured byte thresholds and never derives a percentage from total -- used+free can be strictly less than total on a real ext4 filesystem (root-reserved blocks), a fact documented in the module docstring rather than asserted away"
  - "The comparison is strictly-less-than at both boundaries: a reading exactly AT critical_free_bytes resolves to warn, and exactly AT warn_free_bytes resolves to ok -- pinned by two dedicated boundary tests"
  - "The startup disk gate runs in main(), not inside _run_session, specifically because _run_session calls new_session() -- after that a session directory already exists and 'refused to start a new session' would no longer be true"
  - "The mid-run recheck attaches to 03-01's existing snapshot_fn tick rather than a second timer thread, per the plan's explicit instruction"
  - "A critical band mid-run degrades the heartbeat but never stops the session -- a partially-written session is worth more than no session, and Phase 1's archive is crash-safe by design; only a critical band AT STARTUP refuses to create a new session"
  - "check_disk_space_fn and now_fn are both keyword-only injectable parameters on _run_session/main with real defaults (check_disk_space, time.monotonic) -- no test-only branch was added inside either production function"

patterns-established:
  - "Pattern: an OS-touching check that must run before a specific downstream side effect (new_session()) is placed in the caller that has not yet triggered that side effect, not inside the function that will trigger it"
  - "Pattern: rate-limiting a per-tick log lives entirely inside the tick's own closure state, keyed on (band, timestamp), not on a class attribute or module global -- so a fresh session's rate limiter never inherits a previous session's state"

requirements-completed: []  # This plan addresses OPS-03 but does NOT mark it -- 03-07 is the sole marker, once the runbook check step (the third of OPS-03's three required surfaces) exists. Plan frontmatter: requirements: [OPS-03], marked here as NOT completed per the plan's own instruction.

coverage:
  - id: D1
    description: "check_disk_space bands free_bytes into ok/warn/critical via strictly-less-than comparisons at both thresholds, including both exactly-at-threshold boundary pairs"
    requirement: "OPS-03"
    verification:
      - kind: unit
        ref: "tests/test_ops_disk_monitor.py#test_one_byte_below_critical_is_critical"
        status: pass
      - kind: unit
        ref: "tests/test_ops_disk_monitor.py#test_exactly_at_critical_is_warn_not_critical"
        status: pass
      - kind: unit
        ref: "tests/test_ops_disk_monitor.py#test_one_byte_below_warn_and_above_critical_is_warn"
        status: pass
      - kind: unit
        ref: "tests/test_ops_disk_monitor.py#test_exactly_at_warn_is_ok"
        status: pass
      - kind: unit
        ref: "tests/test_ops_disk_monitor.py#test_far_above_both_is_ok"
        status: pass
    human_judgment: false
  - id: D2
    description: "A non-existent measurement path is resolved to its nearest existing ancestor before calling disk_usage_fn, never raising and never creating a directory"
    requirement: "OPS-03"
    verification:
      - kind: unit
        ref: "tests/test_ops_disk_monitor.py#test_nonexistent_path_measures_nearest_existing_ancestor"
        status: pass
      - kind: unit
        ref: "tests/test_ops_disk_monitor.py#test_nonexistent_single_component_path_falls_back_to_parent"
        status: pass
    human_judgment: false
  - id: D3
    description: "The used+free < total real-ext4 case produces a correct band with no error; nothing derives a percentage from total"
    requirement: "OPS-03"
    verification:
      - kind: unit
        ref: "tests/test_ops_disk_monitor.py#test_used_plus_free_less_than_total_produces_correct_band_no_error"
        status: pass
    human_judgment: false
  - id: D4
    description: "A critical-band start exits 1, creates no session directory, and publishes a final stopped-error heartbeat naming the free bytes and the critical threshold; warn proceeds"
    requirement: "OPS-03"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_critical_band_at_startup_exits_1_creates_no_session_and_publishes_stopped_error"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_warn_band_at_startup_proceeds_to_a_completed_session"
        status: pass
    human_judgment: false
  - id: D5
    description: "Every start logs the free-space line (free bytes, measured path, band) in all three bands, ok included"
    requirement: "OPS-03"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_every_start_logs_the_free_space_line_in_every_band"
        status: pass
    human_judgment: false
  - id: D6
    description: "A mid-run warn or critical band reports degraded (never stopped-error), names the band in detail, and the run still reaches a clean finish with a .done marker and heartbeat-file removal"
    requirement: "OPS-03"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_mid_run_non_ok_band_reports_degraded_never_stops_and_finishes_cleanly"
        status: pass
    human_judgment: false
  - id: D7
    description: "The loud mid-run log does not repeat within the rate-limit interval, and does repeat once the interval elapses while the band persists"
    requirement: "OPS-03"
    verification:
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_mid_run_disk_log_does_not_repeat_within_the_rate_limit_interval"
        status: pass
      - kind: unit
        ref: "tests/test_logger_cli_ops.py#test_mid_run_disk_log_repeats_once_the_rate_limit_interval_elapses"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-09-29
status: complete
---

# Phase 3 Plan 2: Disk-Space Monitoring Summary

**Two-stage `shutil.disk_usage`-backed thresholds against the archive root: `main()` refuses a new session below critical (logging both figures and publishing a final `stopped-error` heartbeat), every start logs the free-space line regardless of band, and `_run_session`'s existing heartbeat tick reports a rate-limited `degraded` state mid-run without ever stopping a session in progress.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 (Task 1 `disk_monitor` module, Task 2 CLI wiring)
- **Files modified:** 1 modified, 3 created

## Accomplishments

- `src/telemetry/ops/disk_monitor.py` built: `check_disk_space` resolves a possibly-non-existent path to its nearest existing ancestor, measures it exactly once via an injectable `disk_usage_fn` (default: stdlib `shutil.disk_usage`), and bands `free_bytes` strictly-less-than each threshold — pinned at both exact-boundary pairs (`test_exactly_at_critical_is_warn_not_critical`, `test_exactly_at_warn_is_ok`) plus the real ext4 `used + free < total` case, with 9 assertions passing on first write (no implementation churn needed after the design settled).
- `telemetry.logger.cli main()` gained the OPS-03 startup gate: runs `check_disk_space_fn` right after the `booting` heartbeat publish and strictly before `_run_session` (which calls `new_session()`), logs one INFO line naming free bytes/measured path/band on every start in every band, and on `critical` logs CRITICAL, publishes a final `stopped-error` heartbeat naming both figures, and exits 1 with no session directory ever created.
- `_run_session`'s existing `snapshot_fn` closure (03-01's seam) now also re-runs the disk check every 1 Hz tick, puts `disk_free_bytes`/`disk_state` into the snapshot's `extras`, and reports `state=degraded` (never `stopped-error`) with the band named in `detail` whenever the band is `warn` or `critical` — the run is never stopped by this check, matching the locked decision that a partially-written session outweighs no session at all.
- The loud WARNING/CRITICAL log during a run is rate-limited: fires immediately on every band transition, then at most once per `_DISK_WARN_LOG_INTERVAL_S` (60s) while the band persists — pinned by two dedicated tests using an injected deterministic `now_fn` counter (`step=0.5` never crosses the interval in the test window; `step=100.0` always crosses it), so a 1 Hz check provably cannot produce a 1 Hz log.
- `check_disk_space_fn` and `now_fn` are both keyword-only injectable parameters on `_run_session`/`main`, mirroring this project's existing `now_fn: Callable[[], float] = time.monotonic` convention (`telemetry.ground.cli`) — no test-only branch was added inside either production function.

## Task Commits

1. **Task 1: `telemetry.ops.disk_monitor`** - `9768277` (feat)
2. **Task 2: Startup gate + mid-run degrade in `telemetry.logger.cli`** - `aefd5de` (feat)

**Plan metadata:** commit pending (this docs commit)

## Files Created/Modified

- `src/telemetry/ops/disk_monitor.py` - `DiskReading`, `DISK_OK`/`DISK_WARN`/`DISK_CRITICAL`, `check_disk_space`, `_nearest_existing_ancestor`
- `tests/test_ops_disk_monitor.py` - 9 boundary/ancestor-resolution/used-plus-free unit tests, all against a fake `disk_usage_fn`
- `src/telemetry/logger/cli.py` - `main()`'s startup gate (`check_disk_space_fn` param, critical refusal, per-band startup log), `_run_session`'s extended `_capturing_snapshot` closure (mid-run recheck, `degraded` mapping, rate-limited loud log), both functions' new `check_disk_space_fn`/`now_fn` keyword parameters, module docstring update, new `DISK_*`/`STATE_DEGRADED`/`STATE_STOPPED_ERROR` imports
- `tests/test_logger_cli_ops.py` - 9 in-process tests: 3 `main()`-level (critical refuses, warn proceeds, every band logs — parametrized) + 4 `_run_session()`-level (mid-run degrade for warn and critical, parametrized; rate-limit lower and upper bound) using a background thread plus heartbeat-file polling for the mid-run assertions (a clean finish removes the file, so the only way to observe a mid-run `degraded` snapshot is to catch it while the session is still running)

## Decisions Made

- **The startup gate lives in `main()`, not inside `_run_session`.** `_run_session` calls `new_session()` early; placing the gate there would mean a session directory could already exist by the time the critical check fires, breaking "refused to start a new session." This was explicit in the plan and confirmed correct during implementation.
- **The mid-run recheck attaches to 03-01's existing `snapshot_fn` tick, not a second timer thread.** The heartbeat publisher already ticks at `config.ops.heartbeat_interval_s`; reusing it is both the plan's explicit instruction and avoids a second thread with its own lifecycle to manage/join.
- **Strictly-less-than at both boundaries, exactly as specified.** A reading exactly at `critical_free_bytes` resolves to `warn`; exactly at `warn_free_bytes` resolves to `ok`. This is a deliberate asymmetry (the better band wins at an exact boundary), pinned by two dedicated tests rather than left to whatever `<` vs `<=` happened to fall out of a first draft.
- **Rate-limiter state lives in the tick closure's own local dict, not a class attribute.** `_heartbeat_tick_state["disk_last_logged_band"]`/`["disk_last_logged_at"]` are reset to `None` whenever the band returns to `ok`, so re-entering a non-ok band later in the same run always logs immediately rather than silently inheriting an old timestamp.
- **Test timing control for the rate-limit tests uses a large `--duration-s` (30s of synthetic frames) plus the test setting `stop_event` itself after a short real sleep**, rather than relying on `--duration-s` to bound real wall-clock time. `SyntheticFrameSource` has no per-frame real-time throttle (confirmed empirically this session), so a small `--duration-s` value finishes almost instantly regardless of the number requested — real wall-clock control had to come from the test's own `stop_event.set()`, not the CLI's duration flag.

## Deviations from Plan

None — plan executed exactly as written. The one implementation detail requiring empirical verification during execution (how much real wall-clock time a given `--duration-s` synthetic run actually takes, needed to design the rate-limit tests) was investigated live via a throwaway diagnostic script before writing the final tests, not assumed from the plan text; this confirmed `SyntheticFrameSource` produces its modelled frame count immediately with no real-time pacing, which is why the two rate-limit tests control real elapsed time via an external `stop_event.set()` rather than `--duration-s` alone. This is test-design discovery, not a code deviation — no production behavior differs from the plan's `<action>` block.

## Issues Encountered

- Initial draft of the `used_bytes + free_bytes < total_bytes` disk-boundary test had an arithmetic sign error in its own precondition assertion (added instead of subtracted the deliberately-inconsistent margin), caught immediately by the test's own self-check assertion failing before the real assertion under test ever ran. Fixed and re-verified; no production code was affected.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- OPS-03 is deliberately left **Pending** in `.planning/REQUIREMENTS.md` — untouched by this plan. The decision requires the free-space figure be surfaced in **three** places (heartbeat state, startup log line, and an explicit runbook check step); this plan delivers the first two. **03-07 is the sole marker for OPS-03**, once `docs/runbook.md`'s check step exists.
- `disk_monitor.check_disk_space` and both CLI-level injection seams (`check_disk_space_fn`, `now_fn`) are ready for 03-03 (hardware-wait/terminal states) and 03-04 (LED indicator) to read the same `disk_state`/`disk_free_bytes` extras already flowing through the heartbeat snapshot, without touching this plan's files.
- No blockers. Full suite: 348 → 366 passing (+18: 9 `disk_monitor` unit, 9 `logger_cli_ops` in-process).
- `git diff --exit-code -- requirements.txt` confirmed clean (no new runtime dependency); `git grep -n "shutil.rmtree\|\.unlink(" -- src/telemetry/ops src/telemetry/logger` confirmed the only removal call anywhere in the ops/logger path is `HeartbeatPublisher.remove()`'s `.unlink()` on the heartbeat status file — never on a session directory, in this plan's new code or anywhere pre-existing.

## Self-Check: PASSED

All 4 created/modified files confirmed present on disk (`src/telemetry/ops/disk_monitor.py`,
`tests/test_ops_disk_monitor.py`, `src/telemetry/logger/cli.py`, `tests/test_logger_cli_ops.py`);
both task commits (`9768277`, `aefd5de`) confirmed present in `git log --oneline --all`. No
missing items.

---
*Phase: 03-unattended-on-car-operation*
*Completed: 2026-09-29*
