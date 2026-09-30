---
phase: 03-unattended-on-car-operation
plan: 05
subsystem: ops
tags: [heartbeat, cli, stdout-stderr-split, requirements-marking]

# Dependency graph
requires:
  - phase: 03-01
    provides: "telemetry.ops.cli's five-code exit contract, argparse surface, and --json single-line discipline; HEARTBEAT_STATES/HeartbeatReadError/read_heartbeat"
  - phase: 03-03
    provides: "LedIndicator seam (unrelated to this plan's own files, but a fellow OPS-02 contributor whose SUMMARY confirmed 03-05 as the sole marker)"
  - phase: 03-04
    provides: "STATE_STOPPED_ERROR actually driven end to end by telemetry.logger.cli, and the real extras shape the capturing/degraded closure writes (session_name, frames_per_s, frames_submitted, records_written)"
provides:
  - "telemetry.ops.cli's completed operator-facing rendering: a per-state meaning+next-action table, a capturing/degraded evidence line, staleness-leads-the-headline, and an exit_code field in --json output"
  - "OPS-02 marked Complete in .planning/REQUIREMENTS.md"
affects: ["03-07 (runbook must generate its troubleshooting table from the same five HEARTBEAT_STATES names and reference the corrected stdout/stderr split)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A closed per-state info table (_STATE_INFO) validated against the imported state tuple at import time -- a sixth state with no matching entry raises immediately rather than rendering blank"
    - "now_fn injectable seam on a CLI's main(), mirroring check_disk_space_fn/wait_for_hardware_fn's existing convention on telemetry.logger.cli.main"
    - "caplog (not capsys) for asserting on logging.Logger output in-process across repeated main() calls in one pytest session -- logging.basicConfig binds a StreamHandler to a fixed stream object at first call and does not reconfigure on later calls, so capsys's per-test sys.stderr swap is invisible to already-registered handlers"

key-files:
  created:
    - tests/test_ops_cli.py
  modified:
    - src/telemetry/ops/cli.py
    - tests/test_ops_tracer.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "Evidence line built from the ACTUAL extras keys telemetry.logger.cli's capturing closure writes (session_name, frames_per_s, frames_submitted, records_written), not the frames_captured/frames_archived names the plan's own read_first prose guessed at -- those keys do not exist on the wire; verified by reading src/telemetry/logger/cli.py's _capturing_snapshot closure directly rather than trusting the plan text"
  - "Corrected the stdout/stderr split: stdout now carries only the single --json line (nothing otherwise); the plain-text human report moves to stderr, matching every other log line this process emits and this project's fixed stdout-for-machine-output/stderr-for-humans convention. 03-01's original carve-out (report on stdout in both modes, reasoning the report was this CLI's 'whole purpose') is superseded -- the plan's action text states this explicitly and twice, and it aligns the file with the rest of the codebase rather than against it."
  - "main() gained an injectable now_fn seam (default time.monotonic) so staleness is testable deterministically with zero time.sleep, mirroring telemetry.logger.cli.main's existing check_disk_space_fn/wait_for_hardware_fn convention"
  - "OPS-02 marked Complete only after re-grepping every 03-*-PLAN.md's requirements: frontmatter and confirming 03-05 is the last claimant -- see the Requirement Marking Gate section below for the verbatim output"

patterns-established:
  - "A per-state info table's completeness is enforced by set-difference against the source-of-truth tuple at import time, not by a test alone -- the failure mode (silently blank rendering for a new state) is prevented structurally, before any test runs"

requirements-completed: [OPS-02]

coverage:
  - id: D1
    description: "Every one of the five HEARTBEAT_STATES renders a state name, a meaning line, and a next-action line, all pairwise distinct across the five states; parameterised over the imported tuple so a sixth state fails the test rather than rendering blank"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_cli.py::test_every_heartbeat_state_renders_a_meaning_and_next_action"
        status: pass
      - kind: unit
        ref: "tests/test_ops_cli.py::test_all_five_states_have_pairwise_distinct_meaning_and_next_action_lines"
        status: pass
    human_judgment: false
  - id: D2
    description: "A fresh capturing reading renders an evidence line with session name, frames/s, and frames captured vs. archived from extras; a zero frames/s reading still renders capturing and exits 0; a fresh degraded reading names the publisher's detail"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_cli.py::test_fresh_capturing_renders_evidence_line_with_session_rate_and_frame_counts"
        status: pass
      - kind: unit
        ref: "tests/test_ops_cli.py::test_fresh_capturing_with_zero_frames_per_s_still_capturing_and_exits_zero"
        status: pass
      - kind: unit
        ref: "tests/test_ops_cli.py::test_fresh_degraded_names_the_detail_the_publisher_recorded"
        status: pass
    human_judgment: false
  - id: D3
    description: "Staleness leads the headline (not just the exit code) for both a plain stale capturing and a stale degraded reading, both exiting 3; clock-went-backwards renders reboot-boundary wording a non-author can act on"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_cli.py::test_stale_capturing_leads_with_staleness_includes_age_and_exits_three"
        status: pass
      - kind: unit
        ref: "tests/test_ops_cli.py::test_stale_degraded_exits_three_not_two"
        status: pass
      - kind: unit
        ref: "tests/test_ops_cli.py::test_clock_went_backwards_renders_actionable_reboot_message_and_exits_three"
        status: pass
    human_judgment: false
  - id: D4
    description: "Absent, non-JSON, and missing-state-key files each produce an actionable, path-naming message and the correct exit code with no traceback reaching the terminal"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_cli.py::test_absent_status_file_exits_four_names_path_and_points_at_journal"
        status: pass
      - kind: unit
        ref: "tests/test_ops_cli.py::test_non_json_bytes_exits_one_names_path_no_traceback"
        status: pass
      - kind: unit
        ref: "tests/test_ops_cli.py::test_valid_json_missing_state_key_exits_one_names_path_no_traceback"
        status: pass
    human_judgment: false
  - id: D5
    description: "--json emits exactly one parseable stdout line carrying state/stale/staleness_reason/age_s/exit_code, and exit_code reflects staleness precedence"
    requirement: "OPS-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_cli.py::test_json_mode_emits_exactly_one_parseable_stdout_line_with_required_fields"
        status: pass
      - kind: unit
        ref: "tests/test_ops_cli.py::test_json_mode_exit_code_field_reflects_staleness_precedence"
        status: pass
    human_judgment: false
  - id: D6
    description: "The real two-process tracer proof still passes against the corrected stdout/stderr split: human-readable text now on stderr, stdout empty in human mode"
    requirement: "OPS-02"
    verification:
      - kind: e2e
        ref: "tests/test_ops_tracer.py::test_running_logger_reports_capturing_via_a_separate_status_process"
        status: pass
    human_judgment: false

# Metrics
duration: 40min
completed: 2026-09-30
status: complete
---

# Phase 3 Plan 5: Heartbeat Rendering Completion and OPS-02 Marking Summary

**`telemetry.ops.cli` now answers "is it alive and capturing" in a sentence for a reader who has never seen the heartbeat state machine — five states each with a distinct meaning and next action, a `capturing`/`degraded` evidence line built from the exact `extras` keys the publisher actually writes, staleness leading the headline ahead of state, and OPS-02 marked Complete after a recorded re-grep confirmed no later plan claims it.**

## Performance

- **Duration:** ~40 min
- **Tasks:** 2 (Task 1 rendering + tests, Task 2 requirement marking)
- **Files modified:** 3 modified (`src/telemetry/ops/cli.py`, `tests/test_ops_tracer.py`, `.planning/REQUIREMENTS.md`), 1 created (`tests/test_ops_cli.py`)

## Accomplishments

- `_STATE_INFO`, a module-level table of (meaning, next_action) pairs keyed by the exact five names in `HEARTBEAT_STATES`, validated against that tuple at import time — a sixth state landing there with no matching entry raises `RuntimeError` immediately, never a silently blank rendering.
- A `capturing`/`degraded` evidence line built from `session_name`, `frames_per_s`, `frames_submitted`, and `records_written` — the **actual** extras keys `telemetry.logger.cli`'s capturing closure writes, confirmed by reading that closure directly rather than trusting the plan's own `read_first` prose, which named `frames_captured`/`frames_archived` — keys that do not exist on the wire.
- Staleness now leads the rendered headline, not just the exit code (which already resolved staleness first from 03-01): a stale reading states its age and reason before naming the state it was last in. `clock-went-backwards` gets dedicated wording about the reboot-boundary hazard, written for a non-author.
- The absent-file message now names the path and points at the journal for the asymmetric case 03-04 created (a running service with no file at all means its config failed to parse before the heartbeat path was known).
- `--json` output gained an `exit_code` field alongside the existing `state`/`stale`/`staleness_reason`/`age_s` fields.
- **Corrected the two-outputs split**: stdout now carries only the single `--json` line and nothing otherwise; the plain-text human report moves to stderr, matching every other log line this process emits and this project's fixed stdout/stderr convention (`.claude/CLAUDE.md`'s Logging section). 03-01's original carve-out — printing the report to stdout in both modes, reasoning the report was this CLI's "whole purpose" — is superseded; the plan's action text states the corrected discipline explicitly, and twice.
- `main()` gained an injectable `now_fn` seam (default `time.monotonic`), mirroring `telemetry.logger.cli.main`'s existing `check_disk_space_fn`/`wait_for_hardware_fn` convention, so every staleness assertion in the new test file is driven by an injected clock with zero `time.sleep`.
- 19 new unit tests in `tests/test_ops_cli.py`, covering every behavior bullet in the plan: all five states' rendering, the evidence line (including the zero-frames-per-s non-fault case), staleness-leads-the-headline for both `capturing` and `degraded`, the `clock-went-backwards` wording, absent/malformed/missing-key files, and `--json`'s exact single-line contract.
- OPS-02 marked Complete in `.planning/REQUIREMENTS.md` after the required re-grep gate (verbatim output below) confirmed 03-05 is the last plan claiming it.

## Task Commits

1. **Task 1: Render all five states, staleness first, with evidence behind `capturing`** — `dba2b80` (feat)
2. **Task 2: Mark OPS-02 Complete** — `89ed32a` (docs)

## Files Created/Modified

- `src/telemetry/ops/cli.py` — `_STATE_INFO` table + import-time validation, `_render_evidence_line`, `_render_stale`, `_render_fresh`, rewritten `_render_human` (now takes the `HeartbeatReading` directly), `now_fn` seam on `main()`, `exit_code` added to `--json` output, human report moved from stdout to stderr, module docstring rewritten to describe the corrected two-outputs split and the five-state completeness invariant
- `tests/test_ops_cli.py` — 19 new tests, all driven through `main()` with fixture files built via the real `write_heartbeat` and an injected `now_fn`
- `tests/test_ops_tracer.py` — one assertion updated from `human_result.stdout` to `human_result.stderr` (Rule 1 fix, see Deviations)
- `.planning/REQUIREMENTS.md` — OPS-02 checkbox flipped to `[x]`; OPS-02's Traceability row changed from Pending to Complete; nothing else touched

## Decisions Made

- **Evidence line reads the real extras keys, not the plan's guessed names.** `src/telemetry/logger/cli.py`'s `_capturing_snapshot` closure writes `session_name`, `frames_per_s`, `frames_submitted`, and `records_written` — not `frames_captured`/`frames_archived`, which the plan's own `read_first` text named but which do not exist anywhere in the codebase. Verified directly by reading the closure rather than trusting the prose, per this project's own recorded anti-pattern ("a prose figure disagreeing with measured reality").
- **The two-outputs split is corrected, not merely re-affirmed.** The plan's action text states twice, explicitly, that stdout must carry only the `--json` line and nothing otherwise, with every human-readable line — including the plain-text report — going to stderr. This is a genuine behavior change from 03-01 (which printed the report to stdout in both modes by deliberate original design). Implemented as stated; the one downstream consumer of the old behavior (`tests/test_ops_tracer.py`) was updated to match (see Deviations).
- **`now_fn` added to `main()`.** Needed to test staleness deterministically at the CLI level without `time.sleep`; mirrors the exact convention already established by `check_disk_space_fn`/`wait_for_hardware_fn` on `telemetry.logger.cli.main`, so this is not a new pattern, just the same one applied to the reader side.
- **`caplog`, not `capsys`, for asserting on `logging.Logger` messages.** `logging.basicConfig` binds a `StreamHandler` to whatever `sys.stderr` object is current at its *first* call in a process; because `_configure_logging` calls `basicConfig` (without `force=True`) on every `main()` invocation, and pytest's `capsys` swaps `sys.stderr` fresh per test, a handler registered during an earlier test's `capsys` context keeps writing to that now-stale stream object on later calls within the same pytest session — invisible to the current test's `capsys.readouterr()`. `tests/test_logger_cli_ops.py` already established `caplog` as this project's answer to exactly this gotcha; `tests/test_ops_cli.py`'s three `logger.error`-message assertions (absent file, non-JSON, missing `state` key) follow that same precedent. The `print(..., file=sys.stderr)` calls that carry the actual rendered report are unaffected — `print` resolves `sys.stderr` fresh at each call, so `capsys` works correctly for all rendering assertions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `tests/test_ops_tracer.py`'s human-readable assertion broke under the corrected stdout/stderr split**
- **Found during:** Full-suite verification after Task 1's implementation
- **Issue:** `test_running_logger_reports_capturing_via_a_separate_status_process` asserted `"capturing" in human_result.stdout`. Once the plain-text report moved to stderr (this plan's own intentional, explicitly-specified correction), that assertion failed — the real subprocess's stdout was empty, and the report was on stderr instead.
- **Fix:** Updated the assertion to `human_result.stdout == ""` and `"capturing" in human_result.stderr`, which is exactly the corrected contract this plan implements.
- **Files modified:** `tests/test_ops_tracer.py` (not in this plan's own `files_modified:` list, but directly caused by this plan's own intended behavior change — matches the precedent 03-04 set for the same file)
- **Verification:** `tests/test_ops_tracer.py` green (2/2); full suite green
- **Committed in:** `dba2b80` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1, test-only, caused directly by this plan's own specified behavior correction)
**Impact on plan:** No scope creep. The fix keeps a pre-existing real e2e test aligned with the intentional, plan-specified stdout/stderr correction.

## Requirement Marking Gate (OPS-02)

Re-grep run before editing `.planning/REQUIREMENTS.md`, verbatim:

```
$ grep -n "^requirements:" .planning/phases/03-unattended-on-car-operation/03-*-PLAN.md
.planning/phases/03-unattended-on-car-operation/03-01-PLAN.md:18:requirements: [OPS-02]
.planning/phases/03-unattended-on-car-operation/03-02-PLAN.md:13:requirements: [OPS-03]
.planning/phases/03-unattended-on-car-operation/03-03-PLAN.md:13:requirements: [OPS-02]
.planning/phases/03-unattended-on-car-operation/03-04-PLAN.md:13:requirements: [OPS-01, OPS-02]
.planning/phases/03-unattended-on-car-operation/03-05-PLAN.md:12:requirements: [OPS-02]
.planning/phases/03-unattended-on-car-operation/03-06-PLAN.md:12:requirements: [OPS-01]
.planning/phases/03-unattended-on-car-operation/03-07-PLAN.md:12:requirements: [OPS-01, OPS-03, OPS-07]
```

Confirmed: 03-01, 03-03, 03-04, and 03-05 list OPS-02; no plan numbered above 03-05 lists it (03-06 lists OPS-01 only; 03-07 lists OPS-01, OPS-03, OPS-07). Gate passed — 03-05 is the correct, sole, and last claimant. Edited `.planning/REQUIREMENTS.md`: exactly two lines changed (the OPS-02 checkbox and its Traceability row), confirmed via `git diff .planning/REQUIREMENTS.md`. OPS-01, OPS-03, and OPS-07 were not touched and remain Pending.

## Issues Encountered

None beyond the one documented deviation above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- OPS-02 is now Complete. `telemetry.ops.cli` fully answers the operator-facing half of the heartbeat: five states, each legible and actionable to a reader who has never seen the state machine; staleness that can never be mistaken for health; concrete evidence behind `capturing`.
- 03-07's runbook must generate its troubleshooting table from the same five `HEARTBEAT_STATES` names this plan's `_STATE_INFO` table uses, and must document the corrected stdout/stderr split (`--json` on stdout only; the human report on stderr) so its own examples pipe correctly.
- 03-06 remains the next plan; it claims OPS-01 only. 03-07 remains the sole owner of OPS-01, OPS-03, and OPS-07.
- No blockers. Full suite: 397 → 416 passing (+19, all in `tests/test_ops_cli.py`). `git diff --exit-code -- requirements.txt` confirmed clean (no new runtime dependency). `python -m telemetry.ops.cli --help` exits 0.

## Self-Check: PASSED

- FOUND: src/telemetry/ops/cli.py
- FOUND: tests/test_ops_cli.py
- FOUND: tests/test_ops_tracer.py
- FOUND: .planning/REQUIREMENTS.md
- FOUND commit: dba2b80
- FOUND commit: 89ed32a
- Full test suite: 416 passed (baseline 397 + 19 new)
- `git diff --exit-code -- requirements.txt`: clean (no changes)

---
*Phase: 03-unattended-on-car-operation*
*Completed: 2026-09-30*
