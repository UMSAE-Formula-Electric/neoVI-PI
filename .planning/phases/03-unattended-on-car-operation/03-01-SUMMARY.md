---
phase: 03-unattended-on-car-operation
plan: 01
subsystem: infra
tags: [ops, heartbeat, systemd-adjacent, config, cli, os.replace, time.monotonic]

# Dependency graph
requires:
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link
    provides: FanOutCounters, TelemetryPipelineCounters, ArchiveWriter.records_written, the typed fail-closed logger.json loader, the archive session lifecycle telemetry.logger.cli already drives
provides:
  - "src/telemetry/ops package: heartbeat.py (write_heartbeat/read_heartbeat/HeartbeatPublisher/HeartbeatSnapshot) and cli.py (telemetry-status)"
  - "OpsConfig / _parse_ops in telemetry.logger.config, extending the existing typed loader with a validated `ops` block"
  - "telemetry.logger.cli wired to publish a 1 Hz heartbeat (booting -> capturing) and remove it on a clean exit"
  - "The snapshot_fn seam later plans (03-02 disk state, 03-03 hardware-wait/terminal states, 03-04 LED) attach to"
affects: [03-02-disk-space-monitoring, 03-03-hardware-wait-terminal-states, 03-04-led-indicator, 03-05-ops-02-marking, 03-07-runbook]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Atomic status-file write: temp file in the target's own parent directory, fsync, os.replace -- never a fixed temp dir (cross-device rename hazard)"
    - "Reboot-boundary staleness guard: now < written_at_monotonic is checked before the ordinary threshold comparison, named clock-went-backwards, distinct from the ordinary stale reason"
    - "Injectable now_fn/wall_clock_fn seams on every OS-touching heartbeat call, mirroring ground/cli.py's now_fn convention -- no time.sleep anywhere in the new tests"
    - "HeartbeatPublisher.snapshot_fn is a mutable public attribute, not fixed at construction, so the caller can swap booting -> capturing closures without reconstructing the publisher"

key-files:
  created:
    - src/telemetry/ops/__init__.py
    - src/telemetry/ops/heartbeat.py
    - src/telemetry/ops/cli.py
    - tests/test_ops_tracer.py
    - tests/test_ops_heartbeat.py
  modified:
    - src/telemetry/logger/config.py
    - config/logger.json
    - src/telemetry/logger/cli.py
    - tests/test_logger_config.py
    - .gitignore

key-decisions:
  - "OpsConfig/_parse_ops live in telemetry/logger/config.py, not a new telemetry/ops/config.py -- 03-RESEARCH.md's suggested layout would need LoggerConfigError and the _require_* helpers from logger/config.py while logger/config.py would need OpsConfig back, a circular import; 03-CONTEXT.md also forbids a second config mechanism"
  - "disk_warn_free_bytes / disk_critical_free_bytes are defined in OpsConfig now even though nothing consumes them until 03-02 -- the block's shape is architecture, and reopening config/logger.json a second time would be pure churn"
  - "The two disk-threshold byte figures in config/logger.json are CHOSEN round defaults, not measurements -- documented plainly in OpsConfig's docstring rather than implied otherwise"
  - "var/ (ops.heartbeat_path's default location) added to .gitignore, mirroring the existing sessions/ rule for run artifacts"

patterns-established:
  - "Pattern: a second reader process (telemetry-status) never shares state with the writer process -- it only ever reads the status file the writer publishes"
  - "Pattern: HEARTBEAT_STATES is a closed five-state set; the sixth 'state' is the file's absence, never a literal string"

requirements-completed: []  # This plan addresses OPS-02 but does NOT mark it -- 03-05 is the sole marker, after 03-03 and 03-04 also land (plan frontmatter: requirements: [OPS-02], marked here as NOT completed per the plan's own instruction).

coverage:
  - id: D1
    description: "A running logger publishes a status file at 1 Hz; a separate telemetry-status process renders it as 'capturing' with an age under the stale threshold"
    requirement: "OPS-02"
    verification:
      - kind: e2e
        ref: "tests/test_ops_tracer.py#test_running_logger_reports_capturing_via_a_separate_status_process"
        status: pass
    human_judgment: false
  - id: D2
    description: "A cleanly-exited logger leaves no status file; telemetry-status against that path exits 4"
    requirement: "OPS-02"
    verification:
      - kind: e2e
        ref: "tests/test_ops_tracer.py#test_clean_exit_leaves_no_status_file_and_status_cli_exits_four"
        status: pass
    human_judgment: false
  - id: D3
    description: "The status file is never observed half-written by a concurrent reader; no .tmp-* sibling survives a write; the temp file is created in the target's own directory"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_heartbeat.py#test_concurrent_reader_never_observes_torn_or_incomplete_json"
        status: pass
      - kind: unit
        ref: "tests/test_ops_heartbeat.py#test_write_heartbeat_leaves_no_tmp_sibling"
        status: pass
      - kind: unit
        ref: "tests/test_ops_heartbeat.py#test_temp_file_is_created_in_the_targets_own_directory"
        status: pass
    human_judgment: false
  - id: D4
    description: "A status file whose written_at_monotonic is ahead of the reader's clock (reboot-boundary case) reports stale=True, reason clock-went-backwards -- never fresh"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_heartbeat.py#test_written_at_greater_than_now_is_stale_clock_went_backwards"
        status: pass
    human_judgment: false
  - id: D5
    description: "read_heartbeat raises HeartbeatReadError, never guessing, for missing file / non-JSON / missing state / missing written_at_monotonic"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_heartbeat.py#test_read_heartbeat_missing_file_raises"
        status: pass
      - kind: unit
        ref: "tests/test_ops_heartbeat.py#test_read_heartbeat_non_json_bytes_raises"
        status: pass
      - kind: unit
        ref: "tests/test_ops_heartbeat.py#test_read_heartbeat_missing_state_key_raises"
        status: pass
      - kind: unit
        ref: "tests/test_ops_heartbeat.py#test_read_heartbeat_missing_written_at_monotonic_key_raises"
        status: pass
    human_judgment: false
  - id: D6
    description: "A malformed or incomplete ops config block raises LoggerConfigError naming the offending key -- absent block, unknown key, invalid heartbeat_interval_s, an inverted heartbeat/disk threshold pair"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_logger_config.py#TestOpsConfig (11 tests)"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-09-29
status: complete
---

# Phase 3 Plan 1: Heartbeat Tracer Summary

**Atomic 1 Hz heartbeat status file (temp-write + os.replace, monotonic-clock reboot-boundary guard) plus a separate `telemetry-status` reader CLI with a five-code exit contract, wired into the existing logger process's existing counters — no capture/archive/telemetry code touched.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 (Task 1 tracer, Task 2 hardening)
- **Files modified:** 5 modified, 5 created

## Accomplishments

- `telemetry.ops` package built: `heartbeat.py` (atomic writer/reader, `HeartbeatPublisher`) and `cli.py` (`telemetry-status`, the five-code exit contract: `0`/`2`/`3`/`4`/`1`)
- `config/logger.json` gains a validated `ops` block; `telemetry.logger.config.OpsConfig`/`_parse_ops` extend the existing typed, fail-closed loader in place (no second config mechanism)
- `telemetry.logger.cli` publishes `booting` immediately after config load (the earliest point the heartbeat path is known — a config failure now produces no status file at all, which is deliberate and honest), then reassigns the publisher's `snapshot_fn` to a real `capturing` closure once the archive runner and telemetry pipeline are running, reading `FanOutCounters`/`ArchiveWriter.records_written`/`TelemetryPipelineCounters` directly rather than re-deriving anything
- Proven end to end by a real two-process test (`tests/test_ops_tracer.py`): a `Popen`'d logger subprocess and a polling `telemetry.ops.cli` subprocess, asserting the JSON exit code, the human-readable stdout containing the state name, and the clean-exit "no file, exit 4" contract
- Task 2 pinned every failure mode named in the plan's behavior block: concurrent-write atomicity, the reboot-boundary `clock-went-backwards` staleness reason (distinct from the ordinary `stale` reason and from `implausible-age`), and every malformed/absent `ops` config key — 23 new unit tests, all against injected clocks, no `time.sleep` anywhere

## Task Commits

1. **Task 1: End-to-end tracer (OPS-02)** - `9dfd563` (feat)
2. **Task 2: Pin heartbeat failure modes** - `e014fa2` (test — behavior-first; no RED failures observed, see Deviations)

**Plan metadata:** commit pending (this docs commit)

## Files Created/Modified

- `src/telemetry/ops/__init__.py` - package docstring only, matching this repo's `__init__.py` convention (no re-exports)
- `src/telemetry/ops/heartbeat.py` - `write_heartbeat`/`read_heartbeat`, `HeartbeatSnapshot`/`HeartbeatReading`, `HeartbeatPublisher`, `HeartbeatReadError`, the five `HEARTBEAT_STATES`
- `src/telemetry/ops/cli.py` - `telemetry-status` entry point, exit-code contract, human/`--json` rendering
- `src/telemetry/logger/config.py` - `OpsConfig` dataclass, `REQUIRED_OPS_KEYS`, `_parse_ops`, wired into `LoggerConfig`/`load_logger_config`
- `config/logger.json` - new `ops` block (heartbeat path/cadence, disk thresholds)
- `src/telemetry/logger/cli.py` - `--heartbeat-path` override, `HeartbeatPublisher` construction/booting publish in `main()`, capturing-state wiring and shutdown join/remove in `_run_session`
- `tests/test_ops_tracer.py` - the end-to-end two-process proof
- `tests/test_ops_heartbeat.py` - the 12 isolated failure-mode unit tests
- `tests/test_logger_config.py` - `TestOpsConfig` class, 11 tests
- `.gitignore` - `var/` (the heartbeat status file's default location) added as a runtime artifact

## Decisions Made

- **`OpsConfig`/`_parse_ops` live in `telemetry/logger/config.py`, not a new `telemetry/ops/config.py`.** 03-RESEARCH.md's suggested file layout would need `LoggerConfigError` and the `_require_*` helpers from `logger/config.py`, while `logger/config.py` would need `OpsConfig` back — a circular import. 03-CONTEXT.md also forbids a second config mechanism. This was flagged as an expected deviation in the plan itself (see the `<action>` block's own note), not discovered mid-execution.
- **Both disk-threshold fields are defined now even though 03-02 is the first consumer.** The block's shape is architecture; reopening `config/logger.json` a second time to add two fields later would be pure churn. `OpsConfig`'s docstring states plainly that the two byte figures are chosen round defaults, not measurements (no real archive-growth-rate measurement exists on this car yet).
- **`var/` added to `.gitignore`.** Running the logger CLI with the default (non-overridden) `--heartbeat-path` writes into the repo-relative `var/status.json`; several pre-existing `test_logger_cli_smoke.py` subprocess tests do exactly this and now leave that file behind on an unclean exit (the intentional archive-overflow test). Mirrors the existing `sessions/` rule for run artifacts.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Windows-only `os.replace` retry in `write_heartbeat`**
- **Found during:** Task 2, writing the concurrent-reader atomicity test
- **Issue:** Under real concurrent read/write on this Windows dev box, `os.replace(tmp, path)` transiently raised `PermissionError` when a reader thread had the destination briefly open — an NTFS-specific rename-lock race with no POSIX equivalent (the module docstring already scopes the atomicity guarantee to Linux). Observed live, not assumed.
- **Fix:** Added `_replace_with_windows_retry`, a short bounded retry (50 attempts, 1ms apart) around `os.replace`, scoped strictly to `sys.platform == "win32"`. On Linux — the deployment target — the function is a single unguarded `os.replace` call, byte-identical to before.
- **Files modified:** `src/telemetry/ops/heartbeat.py`
- **Verification:** `tests/test_ops_heartbeat.py::test_concurrent_reader_never_observes_torn_or_incomplete_json` passes cleanly with zero thread-exception warnings under `-W error::pytest.PytestUnhandledThreadExceptionWarning`
- **Committed in:** `e014fa2` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug fix, Windows-only, no production behavior change on Linux)
**Impact on plan:** No scope creep. The fix is strictly additive testability hardening for the one platform this project develops on but never deploys to.

## Issues Encountered

- Task 2's behavior-first pass (write assertions first, fix only if they fail) found the concurrent-write race described above via the reader's own `PermissionError` propagating out of the writer thread — not a torn-JSON read, which the atomicity guarantee under test was actually about, but a real, previously-unobserved Windows-specific rename race that needed its own fix rather than a weakened assertion. Every other behavior in the plan's list (reboot-boundary staleness, implausible-age, malformed-config rejection) passed against the untouched Task 1 implementation with no code changes, consistent with this project's established precedent (Phase 0's 00-03: "hardening required no code changes... verified by writing assertions first and observing them pass").

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The `snapshot_fn` seam (`HeartbeatPublisher.snapshot_fn`, a mutable attribute) is ready for 03-02 (disk state) and 03-03 (hardware-wait/terminal states) to extend without touching this plan's files.
- `OpsConfig.disk_warn_free_bytes`/`disk_critical_free_bytes` are already validated and available for 03-02 to consume; no config reopening needed.
- 03-05 remains the sole owner of marking `OPS-02` complete in `REQUIREMENTS.md` — deliberately left untouched here, per the plan's own instruction and the project's fixed requirement-ownership rule.
- No blockers. Full suite: 323 → 348 passing (+25: 2 tracer, 12 heartbeat unit, 11 ops-config unit).

## Self-Check: PASSED

All 10 created/modified files confirmed present on disk; both task commits
(`9dfd563`, `e014fa2`) confirmed present in `git log --oneline --all`. No
missing items.

---
*Phase: 03-unattended-on-car-operation*
*Completed: 2026-09-29*
