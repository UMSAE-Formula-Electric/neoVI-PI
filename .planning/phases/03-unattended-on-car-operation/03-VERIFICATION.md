---
phase: 03-unattended-on-car-operation
verified: 2026-09-30T08:00:00Z
status: gaps_found
score: 2/4 success criteria verified
behavior_unverified: 1
overrides_applied: 0
gaps:
  - truth: "Someone standing at the car can tell the logger is alive and capturing without opening a terminal (Success Criterion 2)"
    status: failed
    reason: "The only implementation of the physical/passive indicator seam (LedIndicator Protocol) that ships in this phase is NullLedIndicator -- a no-op. The concrete MembraneLedIndicator was approved by the user at the 03-03 checkpoint but explicitly deferred to a follow-up plan that does not exist yet (no plan file, no ROADMAP entry). The only way anyone standing at the car can currently check aliveness/capturing state is `python -m telemetry.ops.cli`, which requires a terminal -- the exact thing this criterion says is not required."
    artifacts:
      - path: "src/telemetry/ops/led.py"
        issue: "LedIndicator Protocol + NullLedIndicator only. No concrete hardware-driving implementation exists anywhere in the repository."
      - path: "docs/runbook.md"
        issue: "Line 14-16 states plainly: 'This document also does not describe a physical status LED: none ships in this phase.'"
    missing:
      - "A concrete MembraneLedIndicator (or equivalent) driving a physical indicator visible without opening a terminal, OR an explicit, user-accepted override/rescoping of this success criterion for Phase 3."
deferred: []
behavior_unverified_items:
  - truth: "Applying power to the car is the entire startup procedure -- no screen, no keyboard, no login -- and the logger is capturing within seconds of boot (Success Criterion 1 / OPS-01)"
    test: "Deploy via deploy/install.sh on a real neoVI PI, reboot with the CAN bus unpowered, confirm the unit starts unattended and reaches waiting-for-hardware without intervention, then power the bus and confirm capturing is reached with frames flowing; reboot a second time with the bus already powered and confirm capturing is reached with zero manual steps."
    expected: "The three-step Pi bring-up procedure in docs/runbook.md's 'Pi bring-up' section all pass, as recorded there."
    why_human: "Nothing runnable on this Windows dev box (or any box without the real neoVI PI hardware) can execute a systemd boot sequence, a real bus power-up race, or a real power cycle. The software side (systemd unit, install script, boot-race retry/backoff, terminal heartbeat states) is fully built and unit/e2e tested, and the unit file is independently verified zero-warning against real `systemd-analyze verify` (systemd 259, WSL) -- but a structural proof of the unit's shape is not proof it boots unattended on the actual car. This is the same class of gap this project already tracks openly for ARCH-03 against docs/power-pull-test.md."
human_verification:
  - test: "Run docs/runbook.md's 'Pi bring-up' procedure (three steps) on real neoVI PI hardware."
    expected: "Service starts unattended on power-up; reaches waiting-for-hardware on its own when the bus is unpowered; transitions to capturing with frames flowing once the bus is powered; and reaches capturing on its own on a second reboot with the bus already powered. All three steps pass without keyboard/screen/login."
    why_human: "Requires the actual car and neoVI PI hardware, which is not available on this dev box. This is Phase 3's single hardware-only verification item, by design (mirrors ARCH-03/docs/power-pull-test.md)."
  - test: "Hand docs/runbook.md to a team member who did not build this system. Watch them install (if not already installed), start a session, confirm health via telemetry.ops.cli, and locate/retrieve a completed session's data, using only the document."
    expected: "The team member completes all three actions without asking the author for help or context beyond what the runbook itself says."
    why_human: "tests/test_runbook_coverage.py (25 tests) proves the document mentions every required name/table/heading sourced from the actual code -- it proves content presence, not that a stranger can actually follow the document end to end. This walkthrough was explicitly recorded in 03-07-SUMMARY.md as 'manual, unrun coverage' belonging to this verification step."
---

# Phase 3: Unattended On-Car Operation Verification Report

**Phase Goal:** As a trackside team member, I want to power on the car and see the logger confirm it is capturing with space to spare, so that I can run a session without a laptop or the person who built it.
**Verified:** 2026-09-30T08:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification
**Mode:** mvp — this phase's goal is a User Story (validated: matches `^As a .+, I want to .+, so that .+\.$`)

## User Flow Coverage

User story: «As a trackside team member, I want to power on the car and see the logger confirm it is capturing with space to spare, so that I can run a session without a laptop or the person who built it.»

| Step | Expected | Evidence | Status |
|------|----------|----------|--------|
| Power on the car | No screen, keyboard, or login step; the logger process starts on its own | `deploy/telemetry-logger.service` (`Restart=always`, `WantedBy=multi-user.target`), `deploy/install.sh` (`enable --now`); `tests/test_deploy_unit_file.py` (20 tests, structural proof); real `systemd-analyze verify` run (zero warnings) recorded in `03-06-SUMMARY.md` | ⚠️ Present, not behaviorally proven on real hardware — see Human Verification |
| See the logger confirm it is capturing | A human standing at the car, with no terminal, can tell it is alive/capturing | `src/telemetry/ops/led.py` — `LedIndicator` Protocol exists, but only `NullLedIndicator` (no-op) ships; no concrete driver exists in the repo | ✗ FAILED — the only current confirmation path is `python -m telemetry.ops.cli`, which requires a terminal |
| ...with space to spare | Remaining NVMe space surfaced with time to act, not discovered on write failure | `src/telemetry/ops/disk_monitor.py::check_disk_space` (two-stage banding), `telemetry.logger.cli`'s startup gate + mid-run degrade, `docs/runbook.md`'s "Checking remaining space" section — all wired and behaviorally tested (`tests/test_ops_disk_monitor.py`, `tests/test_logger_cli_ops.py`) | ✓ VERIFIED |
| Outcome: run a session without a laptop or the person who built it | A non-author can start, confirm health, and retrieve data using only the runbook | `docs/runbook.md` (8 sections), `tests/test_runbook_coverage.py` (25 source-derived content tests) prove the document's completeness; the actual non-author walkthrough has not been run | ⚠️ Present, not behaviorally proven — see Human Verification |

**This user story's outcome is not yet fully achieved.** Criterion 2 (a non-terminal confirmation of aliveness/capturing) is a genuine gap, not merely unverified — the artifact needed to satisfy it (a concrete physical indicator) does not exist in the codebase; only a Protocol seam and a no-op implementation do.

## Goal Achievement

### Observable Truths (Success Criteria, verbatim from ROADMAP.md)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Applying power to the car is the entire startup procedure — no screen, no keyboard, no login — and the logger is capturing within seconds of boot | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | `deploy/telemetry-logger.service` + `deploy/install.sh` fully built, structurally proven (20 tests) and independently `systemd-analyze verify`-clean; `wait_for_hardware` boot-race retry/backoff fully unit-tested (`tests/test_ops_hardware_wait.py`, 10 tests) and wired end to end at the `main()` level (`tests/test_logger_cli_ops.py`). No test on this dev box can execute a real boot sequence. OPS-01 is correctly left Pending in REQUIREMENTS.md pending the Pi bring-up item in `docs/runbook.md`. |
| 2 | Someone standing at the car can tell the logger is alive and capturing without opening a terminal | ✗ FAILED | Only `NullLedIndicator` (`src/telemetry/ops/led.py:87-106`) ships; it is a no-op by construction. The concrete `MembraneLedIndicator` was approved at the 03-03 checkpoint but deferred to an as-yet-unwritten follow-up plan (no plan file exists; not referenced anywhere in ROADMAP.md). `docs/runbook.md:14-16` states this plainly: "This document also does not describe a physical status LED: none ships in this phase." The only current confirmation mechanism is `python -m telemetry.ops.cli`, which requires opening a terminal. |
| 3 | Remaining NVMe space is surfaced while there is still time to act on it, not discovered when a session fails to write | ✓ VERIFIED | `check_disk_space` (`src/telemetry/ops/disk_monitor.py:85`) bands `free_bytes` against two configured thresholds; `telemetry.logger.cli.main()` refuses a new session below critical and logs the free-space line in every band on every start; `_run_session`'s existing heartbeat tick rechecks mid-run and reports `degraded` (never stopping a run) with a rate-limited loud log. Fully behaviorally tested: boundary bands (`tests/test_ops_disk_monitor.py`, 9 tests), startup gate + mid-run degrade + rate-limiting (`tests/test_logger_cli_ops.py`, 9 tests). `docs/runbook.md`'s "Checking remaining space" section documents both thresholds and both guarantees ("never deletes", "never stops a run in progress"). |
| 4 | A team member who did not build the system can start a session, confirm it is healthy, and retrieve the data using only the written runbook | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | `docs/runbook.md` (252 lines, 8 sections) is comprehensive and its content is proven present by `tests/test_runbook_coverage.py` (25 tests, every expected string derived from source — `HEARTBEAT_STATES`, `OpsConfig` fields, the `.done` marker, the deploy unit filename — never hardcoded). This proves the document says the right things; it does not prove a stranger can actually follow it end to end. 03-07-SUMMARY.md explicitly records this walkthrough as "manual, unrun coverage" belonging to this verification step. |

**Score:** 2/4 success criteria fully resolved (1 FAILED, 2 PRESENT_BEHAVIOR_UNVERIFIED routed to human verification, 1 VERIFIED). Per the decision tree, a single FAILED truth is sufficient to set `status: gaps_found` regardless of the other three.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/telemetry/ops/heartbeat.py` | Atomic status-file writer/reader, reboot-boundary staleness guard, publisher thread | ✓ VERIFIED | 380 lines; `write_heartbeat`/`read_heartbeat`/`HeartbeatPublisher`; wired into `telemetry.logger.cli`; 23+ unit tests |
| `src/telemetry/ops/cli.py` | `telemetry-status` reader CLI, five-state rendering, exit-code contract | ✓ VERIFIED | 390 lines; imports all five `HEARTBEAT_STATES` constants (WR-04 fix confirmed applied, commit `11c70dc`); import-time completeness guards on both `_STATE_INFO` and `_FRESH_OK_STATES`/`_FRESH_BAD_STATES`; 19+ tests in `tests/test_ops_cli.py` |
| `src/telemetry/ops/disk_monitor.py` | Two-stage disk-space banding against the archive root | ✓ VERIFIED | 117 lines; `check_disk_space`; wired into `telemetry.logger.cli` startup gate and mid-run tick; 9 unit + 9 integration tests |
| `src/telemetry/ops/hardware_wait.py` | Indefinite retry/backoff for the boot power-sequencing race | ✓ VERIFIED | 156 lines; `wait_for_hardware`; wired into `main()`, wrapped in try/except publishing `stopped-error` on an unowned exception (WR-01 fix confirmed, commit `2ec3a4e`); 10 unit tests |
| `src/telemetry/ops/led.py` | `LedIndicator` Protocol + `NullLedIndicator` seam | ⚠️ ORPHANED FOR PURPOSE | 106 lines; Protocol exists and is wired into `HeartbeatPublisher`'s write loop, but the seam has no concrete implementation that drives a real physical indicator — it is structurally complete and behaviorally inert. This is the artifact behind Success Criterion 2's FAILED status. |
| `deploy/telemetry-logger.service` | systemd unit, correct rate-limit placement, non-root user | ✓ VERIFIED | 29 lines; `StartLimitIntervalSec`/`StartLimitBurst` in `[Unit]`; `User=telemetry`; verified zero-warning against real `systemd-analyze verify` (systemd 259) |
| `deploy/install.sh` | One-command idempotent installer | ✓ VERIFIED | 93 lines; CR-01 ordering fix confirmed applied (directories created/chowned before `enable --now`, commit `f6537b9`); `tests/test_deploy_unit_file.py::test_install_script_creates_directories_before_enabling` pins the fix |
| `docs/runbook.md` | Operating document for a non-author | ✓ VERIFIED (content) / ⚠️ UNVERIFIED (followability) | 252 lines, 8 sections; content proven present by 25 source-derived tests; followability by a stranger not yet tested (see Human Verification) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `telemetry.logger.cli` main() | `src/telemetry/ops/heartbeat.py` | `HeartbeatPublisher` construction + `publish_now`/`start()` | ✓ WIRED | Confirmed by reading `src/telemetry/logger/cli.py` lines ~798-935; two-process e2e test (`tests/test_ops_tracer.py`) proves it live |
| `src/telemetry/ops/cli.py` | status file on disk | `read_heartbeat` against `config.ops.heartbeat_path` | ✓ WIRED | `tests/test_ops_tracer.py` real subprocess round-trip |
| `telemetry.logger.cli._run_session` | `src/telemetry/ops/disk_monitor.py` | mid-run `snapshot_fn` tick re-invokes `check_disk_space_fn` | ✓ WIRED | `tests/test_logger_cli_ops.py::test_mid_run_non_ok_band_reports_degraded_never_stops_and_finishes_cleanly` |
| `telemetry.logger.cli.main` | `src/telemetry/ops/hardware_wait.py` | `wait_for_hardware_fn` call before `_run_session` | ✓ WIRED | `tests/test_logger_cli_ops.py::test_hardware_boot_race_waits_then_recovers_to_capturing` |
| `HeartbeatPublisher` write loop | `src/telemetry/ops/led.py` | `led.set_state(...)` called on every tick/`publish_now` | ✓ WIRED (to a no-op) | `tests/test_ops_heartbeat.py` confirms call-count and raise-survival against a recording/raising double, not against real hardware — there is nothing downstream of the wiring that produces a physical signal |
| `deploy/install.sh` | `/opt/telemetry/sessions`, `/opt/telemetry/var` | `mkdir`+`chown` before `enable --now` | ✓ WIRED (post-fix) | CR-01 fix confirmed in file; regression test present and passing |

### Data-Flow Trace (Level 4)

Not applicable in the dashboard/UI sense — this phase ships no rendered UI. The equivalent trace for the heartbeat/CLI path (config → publisher → status file → reader → rendered text/JSON) was walked at Key Link Verification above and confirmed to carry real counter values (`frames_submitted`, `records_written`, `disk_free_bytes`, `disk_state`), not static/hardcoded data — confirmed by reading `_capturing_snapshot` in `src/telemetry/logger/cli.py` directly.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full phase-relevant test files pass | `python -m pytest tests/test_runbook_coverage.py tests/test_ops_cli.py tests/test_ops_tracer.py tests/test_logger_cli_ops.py tests/test_ops_hardware_wait.py tests/test_ops_disk_monitor.py tests/test_ops_heartbeat.py tests/test_ops_led.py -q` | 109 passed | ✓ PASS |
| Full workspace suite (run once) | `python -m pytest -q` | 463 passed | ✓ PASS |
| Deploy unit-file structural lint | `python -m pytest tests/test_deploy_unit_file.py -q` | 20 passed | ✓ PASS |
| CR-01 regression test specifically | `python -m pytest tests/test_deploy_unit_file.py -k test_install_script_creates_directories_before_enabling -q` | present and passing (confirmed via full-suite run above) | ✓ PASS |
| Previously-flaky rate-limit test in isolation | `python -m pytest tests/test_logger_cli_ops.py -k test_mid_run_disk_log_repeats_once_the_rate_limit_interval_elapses -q` | 1 passed | ✓ PASS (known load-sensitive under full-suite contention; tracked as open WINDOWS.md id=4, not a blocker) |
| `git diff --exit-code -- requirements.txt` | — | clean | ✓ PASS — no dependency drift across the whole phase |

### Probe Execution

No `scripts/*/tests/probe-*.sh` convention exists in this repository, and no plan/SUMMARY for this phase references a probe script. `bash -n deploy/install.sh` (a shell syntax check, not a probe) was already run by the executor and reconfirmed structurally sound. `systemd-analyze verify` against the real unit file (via WSL, not available in this verifier's sandbox) is recorded as independently reproduced in `03-06-SUMMARY.md` — not re-run here since it requires a Linux systemd binary this Windows verification environment lacks; the claim is corroborated by the unit file's own comments citing the exact systemd version (259) and result (zero warnings, exit 0), and by 21 structural tests that assert the same shape.

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|--------------|----------------|--------------|--------|----------|
| OPS-01 | 03-04, 03-06, 03-07 | Logger starts automatically on power-up with no keyboard, screen, or login | Pending (correctly) | Software fully built and tested; boot behavior on real hardware unproven. REQUIREMENTS.md correctly holds this Pending, consistent with the ARCH-03 precedent. |
| OPS-02 | 03-01, 03-03, 03-04, 03-05 | Logger exposes a heartbeat indicating it is alive and capturing | Complete (marked by 03-05) | Satisfied on its literal text (a heartbeat exists and is exposed via a reader CLI). Note: the phase-level success criterion goes further ("without opening a terminal") than OPS-02's own text requires — see Success Criterion 2 above, which is FAILED despite OPS-02 being correctly marked Complete against its own narrower wording. |
| OPS-03 | 03-02, 03-07 | Remaining disk space monitored and surfaced before critical | Complete | Fully verified — see Success Criterion 3 above. |
| OPS-07 | 03-07 | Written runbook covers starting, health-checking, and retrieving data | Complete | Content verified present and correct by source-derived tests. The "usable by someone else" half of this requirement's spirit is unconfirmed by an actual walkthrough — see Human Verification. Requirement text itself ("covers...") is satisfied; the phase-level success criterion 4 additionally requires that a non-author *can actually do it*, which remains open. |

No orphaned requirements: `.planning/REQUIREMENTS.md`'s Phase 3 row set (OPS-01, OPS-02, OPS-03, OPS-07) exactly matches the union of every `03-*-PLAN.md`'s `requirements:` frontmatter field, confirmed by grep.

### Anti-Patterns Found

No `TBD`/`FIXME`/`XXX` debt markers found in any file modified by this phase (`src/telemetry/ops/*.py`, `src/telemetry/logger/cli.py`, `deploy/*.sh`, `deploy/*.service`). No `TODO`/`HACK`/`PLACEHOLDER` found either. The code review (`03-REVIEW.md`) already surfaced the substantive issues; three of the ten (1 critical + 2 warnings) are confirmed fixed by direct commit inspection (`f6537b9` CR-01, `2ec3a4e` WR-01, `11c70dc` WR-04); four remain deferred by explicit user decision and are recorded in `03-REVIEW.md` (WR-02, WR-03, WR-05, WR-06) plus three Info items — none of these deferred items block the phase goal on their own, but WR-06 (LED never closed on the hardware-wait clean-stop path) will matter the moment a real LED driver ships.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/telemetry/ops/led.py` | 87-106 | `NullLedIndicator` — deliberate no-op stub, documented as such | ℹ️ Info (by design) | This is the direct cause of Success Criterion 2's FAILED status — not a code-quality issue but a scope gap |
| `deploy/install.sh` | — | (fixed) | — | CR-01 confirmed resolved |
| `src/telemetry/ops/cli.py` | — | (fixed) | — | WR-04 confirmed resolved |
| `src/telemetry/logger/cli.py` | — | (fixed) | — | WR-01 confirmed resolved |
| `tests/test_logger_cli_ops.py` | — | Load-sensitive flaky assertion (WINDOWS.md id=4) | ⚠️ Warning (tracked, open) | Not a functional gap; test-only, deferred to a future gap pass |

### Human Verification Required

1. **Pi bring-up (OPS-01, Success Criterion 1)**
   **Test:** Run `docs/runbook.md`'s "Pi bring-up" three-step procedure on real neoVI PI hardware.
   **Expected:** Service starts unattended; reaches `waiting-for-hardware` on its own when the bus is unpowered; transitions to `capturing` with frames flowing once the bus is powered; reaches `capturing` unattended on a second reboot with the bus already powered.
   **Why human:** Requires the actual car; no software test can execute a real boot/power sequence.

2. **Runbook walkthrough by a non-author (OPS-07, Success Criterion 4)**
   **Test:** Hand `docs/runbook.md` to a team member who did not build this system; watch them install (if needed), start a session, confirm health, and retrieve data using only the document.
   **Expected:** They complete all three actions without needing help beyond the document.
   **Why human:** The coverage test proves the document mentions the right things, not that a stranger can follow it end to end. Recorded in `03-07-SUMMARY.md` as explicitly unrun.

### Gaps Summary

**One success criterion out of four is a genuine, actionable gap: Success Criterion 2 ("someone standing at the car can tell the logger is alive and capturing without opening a terminal").** This is not a hardware-availability problem like OPS-01 — it is a scope gap. The `LedIndicator` Protocol seam is fully built and wired into `HeartbeatPublisher`, but the only implementation that ships is `NullLedIndicator`, a no-op. The user approved a real `MembraneLedIndicator` at the 03-03 checkpoint ("approve-and-replan"), but the follow-up plan to actually build it was never created — it does not appear anywhere in `ROADMAP.md`, and no later phase's goal or success criteria mention it. Today, the only way anyone standing at the car can check aliveness/capturing is running `python -m telemetry.ops.cli`, which requires opening a terminal — the literal condition this success criterion says is not required.

The other three criteria resolve as: Criterion 3 (disk space) is fully verified with no caveats. Criteria 1 and 4 are both correctly and honestly held open pending real-world verification the team has already scheduled (the single Pi bring-up item and the runbook walkthrough), following the established ARCH-03/`docs/power-pull-test.md` precedent — these are not code defects, and the software behind both is unusually thoroughly tested for what can be tested without the missing hardware/human step.

On the code-review side, the critical finding (CR-01, a real installer ordering bug that would have caused a guaranteed spurious failed start on every fresh install) and two of six warnings (WR-01, WR-04) are confirmed fixed by direct inspection of the referenced commits. Four warnings and three info items remain deferred by explicit, recorded user decision and do not block this phase's goal.

**Recommended path forward:** either (a) write the follow-up `MembraneLedIndicator` plan now, before closing this phase, so Success Criterion 2 can actually be met, or (b) have the user explicitly accept a scope reduction for this phase (an override in this VERIFICATION.md's frontmatter) acknowledging that "without opening a terminal" will not be true until that follow-up plan lands, and track the follow-up plan as a named, scheduled gap rather than an implicit one.

---

_Verified: 2026-09-30T08:00:00Z_
_Verifier: Claude (gsd-verifier)_
