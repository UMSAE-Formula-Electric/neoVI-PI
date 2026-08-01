---
phase: 00-compression-ratio-gate
plan: 07
subsystem: telemetry-compression
tags: [cantools, compression-gate, go-no-go, bit-rate-analysis]

# Dependency graph
requires:
  - phase: 00-06
    provides: measurement engine (per-ID, per-category, worst-N, ablations, peak windows, bit rate)
  - phase: 00-04
    provides: pre-registered D-13 pass threshold and checked-in D-12 modelling assumptions
provides:
  - Published gate report artifacts (00-REPORT.json, 00-REPORT.csv) at the committed configuration
  - Hand-written go/no-go decision (00-DECISION.md) citing the report and threshold
  - Named D-15 critical-channel subset (12 messages, 74.62 kbit/s) for the live path
  - PROJECT.md Key Decisions row updated from Pending to the no-go verdict
  - Checked-in check_decision.py consistency gate
affects: [phase-1-dual-path-capture, phase-4-wire-protocol-hardening, phase-5-transmit-shaping, phase-6-live-plots]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-artifact decision pattern (D-16): tool-generated report stays reproducible, hand-written decision stays human and citable"
    - "Pre-registered threshold committed before measurement runs, with an explicit no-revision-after-the-fact clause"

key-files:
  created:
    - .planning/phases/00-compression-ratio-gate/00-DECISION.md
    - .planning/phases/00-compression-ratio-gate/check_decision.py
    - .planning/phases/00-compression-ratio-gate/00-REPORT.json
    - .planning/phases/00-compression-ratio-gate/00-REPORT.csv
  modified:
    - .planning/PROJECT.md

key-decisions:
  - "No-go: typical bracket measures 305.13 kbit/s avg / 313.55 kbit/s 1s-peak against pre-registered ceilings of 120 / 170 kbit/s -- both fail, by 2.54x and 1.84x respectively"
  - "Live path carries a named 12-message critical-channel subset (74.62 kbit/s, 24.5% of the typical bracket) instead of the full bus; the full-rate NVMe archive is unaffected"
  - "Worst-case bracket (344.51 kbit/s) exceeds even the 200 kbit/s baseline budget and is carried forward as a Phase 1 real-traffic re-check condition per D-14, not a reason to fail the gate twice"
  - "EMUS BMS _Ext-message modelling error (34 messages don't exist on the real standard-ID-only bus) recorded as a documented arithmetic correction (~261.85 kbit/s), not a re-run -- verdict unchanged since the fixed 6-byte CFR header, not BMS duplication, is the binding constraint"
  - "Critical-channel subset membership must be a data-driven allowlist Phase 1 reads at startup, not code -- a config edit plus restart of both ends, made safe mid-season by Phase 4's dictionary-version negotiation"

requirements-completed: [GATE-01, GATE-02, GATE-03]

coverage:
  - id: D1
    description: "Report produced at the committed configuration (no CLI overrides), tracked by git, both JSON and CSV forms"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "meta.overrides empty / duration_s+seed match config/gate.json assertion in 00-07-PLAN.md Task 1 automated verify"
        status: pass
    human_judgment: false
  - id: D2
    description: "Hand-written go/no-go decision citing the report and the pre-registered threshold, with all nine required sections"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "check_decision.py (all nine sections present, both files cited, typical-bracket figure quoted verbatim, PROJECT.md row updated)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Critical-channel subset named regardless of verdict, with its own measured cost from the report's per-ID table"
    requirement: "GATE-02"
    verification:
      - kind: manual_procedural
        ref: "checkpoint resolution in .continue-here.md, cross-checked against 00-REPORT.csv typical-bracket rows for all 12 subset IDs (sum verified to 74.62 kbit/s)"
        status: pass
    human_judgment: true
    rationale: "D-15 subset priority requires the team's knowledge of what the pit engineer actually watches -- confirmed by the user at the checkpoint, not derivable from the report alone"
  - id: D4
    description: "PROJECT.md Key Decisions row for the compression-ratio gate updated from Pending, scoped single-row edit"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "check_decision.py PROJECT.md row assertion + git diff showing exactly one line changed"
        status: pass
    human_judgment: false

duration: ~25min (Task 2 only -- Task 1 and the checkpoint completed in a prior session)
completed: 2026-08-01
status: complete
---

# Phase 0 Plan 07: Compression Ratio Gate — Report and Decision Summary

**No-go verdict: the modelled typical bracket measures 305.13/313.55 kbit/s avg/peak against pre-registered 120/170 kbit/s ceilings; the live path carries a named 12-message, 74.62 kbit/s critical-channel subset instead of the full bus.**

## Performance

- **Duration:** ~25 min for Task 2 (this session). Task 1 (report generation, `7d13a77`/`051694b`) and the checkpoint decision were completed in a prior session.
- **Started:** 2026-08-01T16:11:00Z (this session, resuming mid-plan)
- **Completed:** 2026-08-01T16:16:40Z
- **Tasks:** 3 total in plan (Task 1 + checkpoint completed previously; Task 2 completed this session)
- **Files modified:** 3 (00-DECISION.md created, check_decision.py created, PROJECT.md scoped edit)

## Accomplishments

- Authored `00-DECISION.md`: a hand-written, dated, cited go/no-go decision covering all nine required sections (Verdict, the bar it was judged against, the measured result, the worst-case bracket, worst-case IDs, what the ablations say, critical channels, what this decision rests on, what later phases should build against). Every numeric figure names the JSON path or threshold key it was quoted from.
- Recorded the **no-go verdict**: typical bracket 305.13072 kbit/s average (-154.3% headroom against the 120 kbit/s ceiling) and 313.552 kbit/s 1-second peak (-84.4% headroom against the 170 kbit/s ceiling) — both fail the pre-registered D-13 bar, which was locked (commit `6acbbd5`) before any measurement existed.
- Recorded the worst-case bracket (344.51352 kbit/s, +72.3% over even the 200 kbit/s baseline budget) as a Phase 1 real-traffic re-check condition per D-14 — informing, not gating.
- Named the D-15 critical-channel subset confirmed at the checkpoint: 12 standard-ID messages totalling 74.62 kbit/s (24.5% of the typical bracket), independently re-summed from `00-REPORT.csv` to confirm the checkpoint's arithmetic.
- Documented the EMUS BMS `_Ext`-message modelling correction (34 non-existent duplicate messages inflating the modelled bus) as a recorded arithmetic estimate (~261.85 kbit/s), explicitly not a config edit or a re-run, per the checkpoint resolution.
- Wrote `check_decision.py`, a checked-in, re-runnable consistency gate asserting the decision's structure, citations, quoted figures, and the PROJECT.md row all agree — passes (`ok`, exit 0).
- Updated the single PROJECT.md Key Decisions row for the compression-ratio gate from `— Pending` to the no-go verdict with a link to `00-DECISION.md`; every other row in the table is byte-identical (`git diff` shows exactly one changed line).

## Task Commits

Task 1 and the checkpoint were completed in a prior session (see `.planning/phases/00-compression-ratio-gate/.continue-here.md`):

1. **Task 1: Run the gate and publish report artifacts** — `7d13a77` (fix: raise `gate.json` `duration_s` 5→100 so the 10s peak window is a real peak), `051694b` (feat: publish full-matrix compression-ratio gate report, config_hash `1dcefe671220`)
2. **Checkpoint: one-way go/no-go verdict** — answered by the user (no commit; resolution recorded in `.continue-here.md`'s `<checkpoint_resolved>` block, `option-no-go` selected)

This session:

3. **Task 2: Author the decision document and record the verdict in PROJECT.md** — `b365e14` (docs: author go/no-go decision (no-go) and record verdict in PROJECT.md)

**Plan metadata:** (this commit, see below)

## Files Created/Modified

- `.planning/phases/00-compression-ratio-gate/00-DECISION.md` — the D-16 hand-written go/no-go decision, all nine required sections, citing `00-REPORT.json` and `00-THRESHOLD.md` throughout
- `.planning/phases/00-compression-ratio-gate/check_decision.py` — checked-in consistency gate (structure, citations, figure match, PROJECT.md row)
- `.planning/PROJECT.md` — scoped single-row edit to the compression-ratio-gate Key Decisions entry
- `.planning/phases/00-compression-ratio-gate/00-REPORT.json`, `00-REPORT.csv` — published in the prior session's Task 1, unmodified this session; cited extensively as the decision's source of truth

## Decisions Made

- **No-go, not conditional go.** The typical bracket misses both pre-registered ceilings by wide margins (2.54x average, 1.84x peak) — this is not a marginal result where a conditional-go with a re-check obligation would fit; per `00-THRESHOLD.md`'s Amendment rule, the bar was not revised to accommodate it.
- **The `_Ext`-message correction is recorded, not acted on.** The user's real-bus correction (EMUS BMS is standard-ID only) is documented as an arithmetic estimate over the published per-ID table, explicitly not a fresh measurement or a `config/gate.json` edit — preserving `00-REPORT.json` as the single measured-and-committed artifact this decision cites, while still surfacing the correction for anyone reading the decision.
- **Subset membership is a config-time concern, not a code-time one.** Recorded in "what later phases should build against" per the user's explicit question at the checkpoint: the 12-message allowlist must be data the Phase 1 telemetry consumer reads at startup, changeable via config edit + restart, with Phase 4's dictionary-version negotiation making a mid-season swap safe.

## Deviations from Plan

None — plan executed exactly as written for Task 2. The `check_decision.py` script, the nine-section `00-DECISION.md`, and the scoped PROJECT.md edit all match the plan's `<action>` and `<acceptance_criteria>` verbatim. Task 1 and the checkpoint (completed in the prior session) are documented in `.continue-here.md` and are outside this session's scope by design — the `<resume_state>` explicitly instructed not to repeat them.

## Issues Encountered

None. All required source figures (`00-REPORT.json`, `00-REPORT.csv`, `00-THRESHOLD.md`) were internally consistent, and the independent re-sum of the 12-message critical-channel subset against `00-REPORT.csv` (74.6236 kbit/s) matched the checkpoint's recorded total (74.62 kbit/s) to within rounding.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

**Phase 0 is complete.** The no-go verdict, the critical-channel subset, and the Phase 1 real-traffic re-check condition are all recorded in `00-DECISION.md` and linked from `PROJECT.md`. Phase 1's telemetry consumer has a single sentence to build against: the live path carries the named 12-message subset (data-driven allowlist, not hardcoded), the full-rate NVMe archive is untouched by this verdict, and a real-traffic re-measurement against the deferred D-08 real-log reader is an open Phase 1 obligation.

Carried-forward items for later phases (see `00-DECISION.md` "What this decision rests on" and STATE.md blockers):
- Phase 1 must implement the D-08 real-log frame-source reader to run the D-14 re-check condition against actual captured bus traffic.
- Phase 1's telemetry consumer must read the 12-message subset as data (allowlist), not bake it into code.
- `00-VALIDATION.md` remains an unfilled template — non-blocking since every task in this phase carried an automated verify, but `/gsd-validate-phase 0` should be run before considering Phase 0 fully audited.
- `.planning/config.json`'s `workflow.test_command` remains uncommitted from a prior session; still load-bearing for the post-merge/regression gates.

---
*Phase: 00-compression-ratio-gate*
*Completed: 2026-08-01*

## Self-Check: PASSED

- FOUND: `.planning/phases/00-compression-ratio-gate/00-DECISION.md`
- FOUND: `.planning/phases/00-compression-ratio-gate/check_decision.py`
- FOUND: `.planning/phases/00-compression-ratio-gate/00-07-SUMMARY.md`
- FOUND: `.planning/PROJECT.md`
- FOUND commit: `7d13a77`
- FOUND commit: `051694b`
- FOUND commit: `b365e14`
