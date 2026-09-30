---
phase: 03-unattended-on-car-operation
plan: 07
subsystem: docs
tags: [runbook, requirements-marking, ops-01, ops-03, ops-07, honesty-gate]

# Dependency graph
requires:
  - phase: 03-01
    provides: "HEARTBEAT_STATES, HeartbeatReading, the exit-code contract telemetry.ops.cli defines"
  - phase: 03-02
    provides: "OpsConfig.disk_warn_free_bytes/disk_critical_free_bytes, the mid-run degraded/disk_state/disk_free_bytes extras"
  - phase: 03-05
    provides: "telemetry.ops.cli's completed five-state rendering and the corrected stdout/stderr split this runbook describes"
  - phase: 03-06
    provides: "deploy/telemetry-logger.service and deploy/install.sh -- the real install command, unit filename, and the four deployment assumptions carried into the Pi bring-up section"
provides:
  - "docs/runbook.md: the operating document for someone who did not build this system -- install, start, confirm health, read exit codes, check disk space, retrieve data, troubleshoot, and the single Pi bring-up hardware-only verification (OPS-01)"
  - "tests/test_runbook_coverage.py: a content-presence coverage test deriving every expected string from source at test-run time (HEARTBEAT_STATES, OpsConfig fields, the .done marker filename, the deploy/ unit filename) -- never a hardcoded literal"
  - "OPS-03 and OPS-07 marked Complete in .planning/REQUIREMENTS.md; OPS-01 deliberately left Pending with a Notes-on-placement bullet pointing at this runbook's Pi bring-up section"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A documentation-content test derives every expected literal from source at test-run time (imported tuple, dataclasses.fields, a config loader, a directory glob) rather than hand-listing any of them -- the first in-repo example of this pattern; no prior analog existed"

key-files:
  created:
    - docs/runbook.md
    - tests/test_runbook_coverage.py
  modified:
    - .planning/REQUIREMENTS.md

key-decisions:
  - "The status command's copyable literal is `python -m telemetry.ops.cli`, not the informal `telemetry-status` alias telemetry.ops.cli's own docstrings use -- verified directly that no console_scripts/entry_points exist anywhere in this repository (no build pipeline), so `telemetry-status` is not something a reader could actually type and have work"
  - "The runbook's journalctl invocations use the unit's exact filename with the .service suffix (`telemetry-logger.service`), matching what the coverage test derives from deploy/*.service, rather than the shorter `telemetry-logger` form telemetry.ops.cli's own docstring comments use -- both work with journalctl/systemctl, but only one is checkable against a derived-from-source literal"
  - "The disk-space section states plainly that disk_free_bytes/disk_state only populate in --json extras once the logger has reached capturing or degraded (i.e., mid-run) -- verified by reading _run_session's _capturing_snapshot closure directly; at boot before that point the runbook points at the startup journal log line instead of implying the JSON fields are always present"
  - "OPS-01 left Pending -- the honesty gate this plan exists to enforce. 03-06 shipped a version-controlled unit, an install script, and a structural lint, but nothing runnable on this Windows dev box can prove a car boots into it unattended. The Notes-on-placement bullet points at this runbook's Pi bring-up section rather than restating the procedure, mirroring ARCH-03's precedent against docs/power-pull-test.md"

patterns-established:
  - "Source-derived documentation coverage: HEARTBEAT_STATES imported, OpsConfig fields via dataclasses.fields, the completion marker via load_logger_config, the unit name via a deploy/*.service glob -- a rename anywhere in the four sources fails the doc test instead of silently orphaning the document"

requirements-completed: [OPS-03, OPS-07]

coverage:
  - id: D1
    description: "docs/runbook.md exists with all eight required sections, in the order the plan specifies; every heartbeat state has a meaning and next action; the disk-space check step names both threshold config keys and their unmeasured-default caveat; the Pi bring-up section carries the exact required heading and a stated pass condition per step"
    requirement: "OPS-07"
    verification:
      - kind: other
        ref: "docs/runbook.md manually reviewed against every <action> bullet in 03-07-PLAN.md's Task 1"
        status: pass
      - kind: human
        ref: "Task 1's <human-check>: hand the document to a team member who did not build this system"
        status: not_run
    human_judgment: true
    rationale: "The automated coverage test (D2 below) proves the document mentions the right things; it cannot prove a stranger can actually follow it. That proof needs a person, is separate from and additional to the Pi bring-up item, and is explicitly deferred to /gsd-verify-work 3 per the plan's own <human-check> text."
  - id: D2
    description: "Every HEARTBEAT_STATES name, every OpsConfig field name, the .done marker filename, all five exit codes as backticked table rows, the Pi bring-up heading exactly once, all four requirement IDs, the status-command/install-script/journalctl literals, and the derived unit filename are all present in the runbook -- every expected string sourced at test-run time, none hardcoded"
    requirement: "OPS-07"
    verification:
      - kind: unit
        ref: "tests/test_runbook_coverage.py (25 tests, all parameterised or derived from source)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The requirement-marking re-grep gate ran before any REQUIREMENTS.md edit, confirmed 03-07 is the last (and only, for OPS-07) claimant of OPS-03/OPS-07, and no plan above 03-07 claims either -- OPS-03 and OPS-07 flipped Complete, OPS-02 left untouched (already Complete from 03-05), OPS-01 left untouched (still Pending) with a Notes-on-placement bullet added"
    requirement: "OPS-03"
    verification:
      - kind: other
        ref: "git diff .planning/REQUIREMENTS.md reviewed: exactly 2 checkbox lines + 2 Traceability rows changed, 1 bullet added -- see Requirement Marking Gate section below for the verbatim re-grep output"
        status: pass
    human_judgment: false

# Metrics
duration: 50min
completed: 2026-09-30
status: complete
---

# Phase 3 Plan 7: Runbook, Drift-Proof Coverage Test, and Final Requirement Status Summary

**`docs/runbook.md` — eight sections taking a stranger from install through a retrieved session, naming every heartbeat state, every ops threshold key, all five exit codes, and the single Pi bring-up hardware-only verification — proven present (never proven followable) by `tests/test_runbook_coverage.py`, a coverage test that derives every expected string from source at test-run time; OPS-03 and OPS-07 marked Complete after a recorded re-grep gate, OPS-01 deliberately left Pending.**

## Performance

- **Duration:** ~50 min
- **Tasks:** 3 (Task 1 runbook, Task 2 TDD-flavored coverage test, Task 3 requirement marking)
- **Files modified:** 1 modified (`.planning/REQUIREMENTS.md`), 2 created (`docs/runbook.md`, `tests/test_runbook_coverage.py`)

## Accomplishments

- `docs/runbook.md` written for a reader who did not build this system and has no planning context: First-time install (`sudo bash deploy/install.sh`, its prerequisites and effects named exactly as `deploy/install.sh` and `deploy/telemetry-logger.service` actually behave), Starting a session (apply power — no screen/keyboard/login, said plainly for a reader expecting a "start" step), Confirming it is healthy (`python -m telemetry.ops.cli`, the five-state table with meaning/action per state, `waiting-for-hardware` called out as the normal boot race not a fault), Reading the exit code (0/1/2/3/4, each a table row), Checking remaining space (the two `OpsConfig` threshold keys named, stated plainly as chosen round numbers not measurements, the never-auto-deletes and never-stops-a-run-in-progress guarantees), Retrieving the data (the `.done` completion marker, copy whole session directories, automated retrieval deferred to a later phase), When something is wrong (the config-load-failure/no-status-file asymmetry from 03-04, the reboot-boundary `clock-went-backwards` staleness case from 03-01), and `## Pi bring-up: the one hardware-only verification (OPS-01)` (the exact heading the coverage test asserts, a three-step procedure with a stated pass condition per step, and the four 03-06 deployment assumptions plus the SDK empty-vs-raise open question listed as items to confirm on the same hardware visit).
- `tests/test_runbook_coverage.py` (25 tests): every `HEARTBEAT_STATES` name imported and parameterised, every `OpsConfig` field enumerated via `dataclasses.fields`, the `.done` marker filename read through `load_logger_config` against the real checked-in `config/logger.json`, the systemd unit filename derived from the one `*.service` file actually present in `deploy/`, exit codes matched as backticked table-row cells (not bare digits), the Pi bring-up heading asserted exactly once, all four requirement IDs cited, and the status-command/install-script literals present. Zero hardcoded expected strings anywhere in the test.
- `.planning/REQUIREMENTS.md`: OPS-03 and OPS-07 checked and flipped Complete (checklist + Traceability table); OPS-01 left unchecked and Pending with a new Notes-on-placement bullet pointing at this runbook's Pi bring-up section, mirroring the ARCH-03/`docs/power-pull-test.md` precedent; OPS-02 (already Complete from 03-05) untouched.

## Task Commits

Each task was committed atomically:

1. **Task 1: `docs/runbook.md`** — `e7eca83` (docs)
2. **Task 2: `tests/test_runbook_coverage.py`** — `cd2febe` (test)
3. **Task 3: mark OPS-03/OPS-07, hold OPS-01** — `1d82169` (docs)

## Files Created/Modified

- `docs/runbook.md` — the eight-section operating document (created)
- `tests/test_runbook_coverage.py` — 25-test source-derived coverage scan (created)
- `.planning/REQUIREMENTS.md` — OPS-03/OPS-07 checkboxes and Traceability rows flipped to Complete, one Notes-on-placement bullet added for OPS-01, OPS-01/OPS-02 rows otherwise untouched

## Decisions Made

- **The copyable status-command literal is `python -m telemetry.ops.cli`, not `telemetry-status`.** Verified directly by grepping the whole repository for `console_scripts`/`entry_points` — neither exists anywhere (no build pipeline, per `.claude/CLAUDE.md`). `telemetry-status` is an informal name `telemetry.ops.cli`'s own docstrings use for prose, not something a reader could actually type and have resolve. The runbook uses the real invocation throughout; the coverage test asserts on that literal, not the alias.
- **Journal invocations use the exact unit filename with `.service`** (`journalctl -u telemetry-logger.service`), matching what `tests/test_runbook_coverage.py` derives from a `deploy/*.service` glob, rather than the shorter form some in-code comments use. Both work identically with `journalctl`/`systemctl`; only the filename-derived form is checkable as sourced-not-restated.
- **The disk-space section states the `extras.disk_free_bytes`/`disk_state` fields only populate once the logger reaches `capturing` or `degraded`.** Verified by reading `_run_session`'s `_capturing_snapshot` closure in `src/telemetry/logger/cli.py` directly (03-02's mid-run recheck attaches to that tick) rather than assuming the fields are always present in every JSON reading — they are not present during `booting`/`waiting-for-hardware`, where the startup journal log line is the only source until capturing begins.
- **OPS-01 left Pending, per the plan's own objective.** 03-06's structural lint proves the unit file's shape; it does not and cannot prove a car boots into it unattended with no keyboard, screen, or login. The Notes-on-placement bullet points at this runbook's Pi bring-up section rather than restating the procedure a second time, following the same discipline `ARCH-03` already established against `docs/power-pull-test.md`.

## Requirement Marking Gate (OPS-03, OPS-07)

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

Confirmed: OPS-03 is listed only by 03-02 and 03-07 — 03-07 is the last and correct sole marker. OPS-07 is listed only by 03-07 — sole marker, no conflict possible. No plan numbered above 03-07 exists in this phase, so the "halt if a later plan still claims it" condition cannot fire. OPS-02 (already marked Complete by 03-05) is not listed by 03-06 or 03-07, confirming it was correctly left untouched. OPS-01 is listed by 03-04, 03-06, and this plan (03-07) — 03-07 is the plan responsible for deciding its final status, and decided it stays Pending (see Decisions above). Gate passed. Edited `.planning/REQUIREMENTS.md`: exactly 2 checkbox lines, 2 Traceability rows, and 1 added Notes-on-placement bullet, confirmed via `git diff .planning/REQUIREMENTS.md`.

## Final Requirement Position (Phase 3)

- **OPS-02: Complete** (marked by 03-05, untouched by this plan)
- **OPS-03: Complete** (marked by this plan)
- **OPS-07: Complete** (marked by this plan)
- **OPS-01: Pending** — intentionally. Its entire content is "starts automatically on power-up with no keyboard, screen, or login," which nothing runnable on this Windows dev box can prove. 03-06 shipped the mechanism (a version-controlled systemd unit, a one-command install script) and a structural lint proving the unit's shape; this plan's own honesty gate declines to treat that as proof of boot behavior. It stays Pending until the single Pi bring-up verification — `docs/runbook.md`'s "Pi bring-up" section — is actually run on real hardware and passes, mirroring exactly how ARCH-03 is held open against `docs/power-pull-test.md`. This is deliberate design, not an oversight, and matches the orchestrator-verified state at dispatch.

## Deviations from Plan

None — plan executed exactly as written. All three tasks matched their `<action>`/`<done>` criteria on first pass; the coverage test's 25 assertions passed against the runbook with no rework needed between writing the two files.

## Manual Coverage Item (not run, recorded per instruction)

Task 1's `<human-check>` — handing `docs/runbook.md` to a team member who did not build this system and watching them start a session, confirm health, and locate a completed session's data using nothing else — is **manual, unrun coverage**, not a checkpoint. This is success criterion 4 for the phase and no automated check stands in for it; `tests/test_runbook_coverage.py` proves the document mentions the right names and tables, not that a stranger can follow it. This item belongs to `/gsd-verify-work 3`, separate from and additional to the single Pi bring-up item.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. This plan writes one document, one test, and one requirements-file edit; nothing is installed and `requirements.txt` is untouched (`git diff --exit-code -- requirements.txt` confirmed clean).

## Next Phase Readiness

- Phase 3 (unattended-on-car operation) is now feature-complete for everything provable without real neoVI PI hardware. Two items remain open, both explicitly out of this plan's own scope to close:
  1. **The single Pi bring-up verification (hardware)** — `docs/runbook.md`'s "Pi bring-up" section, gating OPS-01.
  2. **The runbook walkthrough by a non-author (human, not hardware)** — Task 1's `<human-check>`, gating full confidence in OPS-07's "usable by someone else" claim (OPS-07 itself is marked Complete on the strength of the document's content and the coverage test; the walkthrough is confirmatory, not blocking, per the plan's own success criteria).
  Both belong to `/gsd-verify-work 3`.
- No blockers. Full suite: 435 → 460 passing (+25, all in `tests/test_runbook_coverage.py`). `git diff --exit-code -- requirements.txt` confirmed clean (no new runtime dependency — this plan installs nothing).

## Self-Check: PASSED

- FOUND: docs/runbook.md
- FOUND: tests/test_runbook_coverage.py
- FOUND commit: e7eca83
- FOUND commit: cd2febe
- FOUND commit: 1d82169
- Full test suite: 460 passed (baseline 435 + 25 new)
- `git diff --exit-code -- requirements.txt`: clean (no changes)
- `git diff .planning/REQUIREMENTS.md`: exactly the 2 checkbox lines + 2 Traceability rows + 1 added bullet described above, nothing else

---
*Phase: 03-unattended-on-car-operation*
*Completed: 2026-09-30*
