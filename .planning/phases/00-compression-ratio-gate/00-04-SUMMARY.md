---
phase: 00-compression-ratio-gate
plan: 04
subsystem: config
tags: [gate-config, threshold, dbc, d-12, d-13, d-14]

# Dependency graph
requires:
  - phase: 00-01
    provides: "pytest framework, src/telemetry/{wire,synth,measure} package skeleton, tests/conftest.py dbc fixture, corrected DBC ground-truth facts (19 cycle-time messages, 109 undeclared)"
provides:
  - "config/gate.json -- D-12 checked-in modelling assumptions: option-a threshold, entropy brackets, bus assignment (confirmed: false), bus_targets (confirmed: false), default_period_ms_by_ecu (confirmed: false), batch size, worst-N, peak windows"
  - "src/telemetry/measure/config.py -- GateConfig, EntropyBracket, BusTarget, Thresholds, load_gate_config, GateConfigError; validates rather than defaults"
  - "00-THRESHOLD.md -- D-13 pre-registered pass condition, committed before any aggregate report exists"
affects: ["00-05", "00-06", "00-07"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Validate-don't-default config loading: every malformed-input path (unknown/missing top-level key, unknown bracket name, out-of-range probability, non-positive numeric, unmapped bus reference) raises GateConfigError naming the offending key and value -- no bare except, no silent fallback"
    - "Measured-vs-modelled provenance carried as a sibling `_note` + `confirmed` boolean inside every config block whose values are a human-authored model rather than a DBC-derived fact (bus_assignment, bus_targets, default_period_ms_by_ecu, entropy_brackets)"
    - "config_hash: short SHA-256 over the canonicalised (sorted-key) raw JSON, stored on GateConfig for later reports to record which assumptions produced a number (T-00-15)"

key-files:
  created:
    - .planning/phases/00-compression-ratio-gate/config/gate.json
    - src/telemetry/measure/config.py
    - tests/test_gate_config.py
    - .planning/phases/00-compression-ratio-gate/00-THRESHOLD.md
  modified: []

key-decisions:
  - "Checkpoint selection: option-a (conservative floor) -- 200 kbit/s baseline radio budget, typical-bracket all-in average <= 120 kbit/s (40% headroom), 1-second sliding-window peak <= 170 kbit/s (15% headroom)."
  - "Checkpoint items 1-4 accepted exactly as proposed: batch_frames=100, ECU-sender bus_assignment placeholder (confirmed: false), worst_n=10, entropy bracket definitions (best/typical/worst dither probabilities)."
  - "User-added item 5: total bus frame rate is now an explicit, unconfirmed assumption in config/gate.json (bus_targets.confirmed: false), because it dominates the verdict and is not derivable from the DBC. Verified against cantools before writing: 19 of 128 messages declare GenMsgCycleTime summing to ~1,690.67 fps; 109 declare none; the prose-cited ~3,730-4,000 fps combined figure (telemetry_conversation.md) is not DBC-derivable."
  - "The 6-byte/frame CFR header-floor risk (179-192 kbit/s at the prose-cited rate vs. 81 kbit/s at the DBC-derivable floor) is recorded in 00-THRESHOLD.md as a pre-registered known risk, explicitly not grounds to revise the bar if it fires."
  - "bus_assignment and default_period_ms_by_ecu are exposed on GateConfig as plain dicts (not further-typed dataclasses), since their shape is a free-form audit record (method, confirmed, _note, measured_basis) rather than a fixed field set -- only entropy_brackets (-> EntropyBracket) and bus_targets (-> BusTarget) values are dataclass-typed, matching the plan's exports list exactly (no BusAssignment/DefaultPeriod dataclass was specified)."

patterns-established:
  - "Ground-truth-by-measurement carried forward from 00-01/00-02/00-03: every DBC-derived figure written into gate.json and 00-THRESHOLD.md (19 cycle-time messages, 1,690.67 fps sum, 109 undeclared, 8 BU_ nodes) was independently re-measured against cantools before being written down, not copied from RESEARCH.md prose."

requirements-completed: [GATE-03]

coverage:
  - id: D1
    description: "Every modelling assumption the gate's numbers depend on is readable from one checked-in JSON file without opening any source file"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "tests/test_gate_config.py::test_default_config_loads_clean, test_bus_assignment_confirmed_flag_is_boolean_and_note_is_nonempty, test_default_period_ms_by_ecu_note_is_nonempty"
        status: pass
    human_judgment: false
  - id: D2
    description: "The pass threshold is written down in 00-THRESHOLD.md, committed and dated, before any measurement has been run, stating a bit-rate ceiling plus required headroom against a named radio budget"
    requirement: "GATE-03"
    verification:
      - kind: manual
        ref: "00-THRESHOLD.md 'Pre-registered pass condition' section, dated 2026-07-31; commit 6acbbd5 precedes any aggregate 00-REPORT.* artifact (the only 00-REPORT.json on disk is plan 00-02's single-ID tracer output, last touched by 5588bfd, no thresholds block)"
        status: pass
    human_judgment: true
  - id: D3
    description: "00-THRESHOLD.md records that the typical bracket gates the verdict and worst-case only informs it"
    requirement: "GATE-03"
    verification:
      - kind: manual
        ref: "00-THRESHOLD.md 'Which bracket decides' section; config/gate.json thresholds.gating_bracket == 'typical' (tests/test_gate_config.py::test_thresholds_gating_bracket_is_typical)"
        status: pass
    human_judgment: false
  - id: D4
    description: "The bus assignment carries an explicit confirmed flag"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "config/gate.json bus_assignment.confirmed == false; tests/test_gate_config.py::test_bus_assignment_confirmed_flag_is_boolean_and_note_is_nonempty"
        status: pass
    human_judgment: false
  - id: D5
    description: "Loading a config with an unknown key, a missing required key, or an entropy bracket name outside best/typical/worst raises a named error rather than silently falling back to a default"
    requirement: "GATE-03"
    verification:
      - kind: unit
        ref: "tests/test_gate_config.py::test_unknown_top_level_key_raises, test_missing_required_top_level_key_raises, test_unknown_entropy_bracket_name_raises, test_out_of_range_probability_raises, test_non_positive_batch_frames_raises, test_non_positive_duration_raises, test_non_positive_peak_window_raises, test_by_ecu_value_not_in_bus_targets_raises, test_unknown_threshold_gating_bracket_raises, test_malformed_json_raises, test_missing_file_raises"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-07-31
status: complete
---

# Phase 0 Plan 4: Pre-Registered Pass Threshold and Checked-In Modelling Assumptions Summary

**D-13 pass threshold (option-a: 200 kbit/s baseline, 120/170 kbit/s average/peak caps, 40%/15% headroom) pre-registered in `00-THRESHOLD.md`, and every modelling assumption the gate depends on -- including a user-added fifth assumption on total bus frame rate -- checked into `config/gate.json` behind a typed loader that refuses to guess.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2 (both auto; the plan's leading checkpoint was answered by the user before this session)
- **Files created:** 4 (`config/gate.json`, `src/telemetry/measure/config.py`, `tests/test_gate_config.py`, `00-THRESHOLD.md`)

## Accomplishments

- `config/gate.json` carries all eleven required top-level keys (`schema_version`, `seed`, `duration_s`, `batch_frames`, `worst_n`, `peak_windows_s`, `entropy_brackets`, `bus_targets`, `bus_assignment`, `default_period_ms_by_ecu`, `thresholds`), each modelled block stating measured-vs-modelled provenance in a sibling `_note` and, where applicable, a `confirmed: false` flag.
- The checkpoint's option-a threshold (200/120/170 kbit/s, 40%/15% headroom, typical bracket gates) is encoded exactly in `thresholds`, and the user's added fifth assumption (total bus frame rate, `confirmed: false`) is recorded in `bus_targets` and `default_period_ms_by_ecu`, backed by a fresh `cantools` measurement (19/128 messages declare `cycle_time`, summing to ~1,690.67 fps; 109 undeclared) rather than the prose-cited ~3,730-4,000 fps figure.
- `src/telemetry/measure/config.py` exposes `GateConfig`, `EntropyBracket`, `BusTarget`, `Thresholds`, `load_gate_config`, `GateConfigError`, and a `config_hash` property (short SHA-256 over the canonicalised raw JSON). The loader validates every field named in the plan's action block and raises `GateConfigError` naming the offending key/value on any malformed input -- no bare `except`, no silent default.
- `tests/test_gate_config.py` (21 tests) pins the checked-in file's internal consistency (every DBC `BU_:` node read from the `dbc` fixture appears in `bus_assignment.by_ecu`, `peak_windows_s` contains the three required scales, `config_hash` is stable across loads and changes after any byte-level edit) and one malformed-input case per validation rule.
- `00-THRESHOLD.md` (82 lines) records all six required sections -- pre-registered pass condition, which bracket decides, what "all-in" means, what this threshold is not, the amendment rule, and the assumptions this threshold rides on -- quoting the literal `thresholds` key names from `config/gate.json`, plus the pre-registered 6-byte/frame CFR header-floor risk (179-192 kbit/s at the prose-cited rate vs. 81 kbit/s at the DBC-derivable floor) that the checkpoint explicitly directed be recorded as a known risk, not grounds to move the bar.
- Full suite: `python -m pytest -q` -- 58 tests, all passing (37 pre-existing + 21 new), zero regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Checked-in modelling assumptions and a typed loader that refuses to guess** - `40a639a` (feat)
2. **Task 2: Write and commit the pre-registered threshold document** - `6acbbd5` (docs)

**Plan metadata:** pending (this commit)

## Files Created/Modified

- `.planning/phases/00-compression-ratio-gate/config/gate.json` - the D-12 checked-in config: option-a thresholds, entropy brackets, ECU-sender bus assignment (`confirmed: false`), bus load targets (`confirmed: false`), default periods for the 109 undeclared-cycle-time messages (`confirmed: false`), batch size 100, worst-N 10, peak windows [0.1, 1.0, 10.0].
- `src/telemetry/measure/config.py` - `GateConfig`, `EntropyBracket`, `BusTarget`, `Thresholds`, `load_gate_config`, `GateConfigError`. Does not import `telemetry.wire` (verified by grep, consistent with the plan's package-boundary rule).
- `tests/test_gate_config.py` - 21 tests: checked-in file loads clean, internal consistency (bus assignment vs. bus targets, all 8 DBC ECU nodes present, three entropy brackets, `typical` gating bracket), `config_hash` stability/change-detection, and 11 malformed-input cases each asserting a `GateConfigError` naming the offending key.
- `.planning/phases/00-compression-ratio-gate/00-THRESHOLD.md` - the D-13 pre-registered pass condition, dated 2026-07-31, committed before any aggregate report exists.

## Decisions Made

- Selected option-a (conservative floor, 40% headroom) at the checkpoint, with all four planner-proposed items (batch size, bus assignment, worst-N, entropy brackets) accepted verbatim, plus a fifth user-added assumption (total bus frame rate, `confirmed: false`) — see key-decisions above and 00-THRESHOLD.md's "Assumptions this threshold rides on" § item 4 for the full measured basis.
- Verified the checkpoint's cited DBC facts directly against `cantools` before writing them into `config/gate.json` and `00-THRESHOLD.md` (8 `BU_:` nodes, 19/128 cycle-time-bearing messages summing to 1690.67 fps, 109 undeclared) rather than trusting the checkpoint prose uncritically, per this plan's own anti-pattern warning. All figures matched.
- Chose to expose `bus_assignment` and `default_period_ms_by_ecu` on `GateConfig` as plain dicts rather than inventing new dataclasses for them, since the plan's artifact export list (`EntropyBracket`, `BusTarget`, `Thresholds`, `GateConfig`, `load_gate_config`, `GateConfigError`) names no such types and their shape (method/confirmed/`_note`/measured_basis) is a free-form audit record rather than a fixed field set.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 2's acceptance-criteria verification bullet assumes no `00-REPORT.json` exists yet; one already does (from plan 00-02's tracer)**
- **Found during:** Task 2, while checking the commit-ordering acceptance criterion ("`ls 00-REPORT.json` fails at that point in history").
- **Issue:** The plan's Task 2 acceptance criteria state the threshold commit should precede any `00-REPORT.json` existing in the repository. `00-REPORT.json` was already committed in plan 00-02 (`5588bfd`, before this plan even started) as the tracer's single-CAN-ID output (`M192_Command_Message`, 8.129 bytes/frame). This is a legitimate, intentional artifact from an earlier plan (documented in `00-02-SUMMARY.md`), not an aggregate go/no-go report -- it has no `thresholds` comparison block. The plan's own automated `<verify>` block does not include this literal file-existence check (only the acceptance-criteria prose does), and that prose's premise -- "no `00-REPORT.json` exists yet" -- does not hold in this repository's actual history, because 00-02 legitimately wrote to that filename first for an unrelated, narrower purpose that plan 00-06 will later overwrite with the real aggregate report.
- **Fix:** Verified the property the criterion actually protects against (T-00-13: no full aggregate report has been produced and committed *after* the threshold, which would mean the threshold was written to fit a known result) by checking that `00-REPORT.json`'s last touching commit (`5588bfd`) predates `00-THRESHOLD.md`'s commit (`6acbbd5`), and that its content has no `thresholds` block and is scoped to one message (`only_message: ["M192_Command_Message"]`). Documented the actual state of `00-REPORT.json` explicitly in `00-THRESHOLD.md`'s new "Status at the time of writing" paragraph so a future reader is not confused by the same false premise. No file was renamed or moved (out of scope for this plan; would touch 00-02/00-03's already-committed history).
- **Files modified:** `.planning/phases/00-compression-ratio-gate/00-THRESHOLD.md` (added the "Status at the time of writing" paragraph).
- **Verification:** `git log -1 --format=%h -- .planning/phases/00-compression-ratio-gate/00-REPORT.json` → `5588bfd`, which predates `6acbbd5` (THRESHOLD.md's commit); `python -c "import json; r=json.load(open('...00-REPORT.json')); print('thresholds' in r)"` → `False`.
- **Committed in:** `6acbbd5` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 -- a false premise inherited into the plan's acceptance-criteria prose, corrected by verifying and documenting the actual property the criterion protects rather than a literal file-existence check that this repository's real history could never satisfy)
**Impact on plan:** No scope creep -- no new files beyond the four the plan specified, no change to the threshold numbers or the config schema. Only the threshold document's own text was extended to state the true state of `00-REPORT.json` at commit time, which strengthens rather than weakens the transparency property T-00-13 exists to protect.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 00-05 (full-bus synthetic stream) can read `bus_targets`, `bus_assignment`, and `default_period_ms_by_ecu` directly from `load_gate_config(GateConfig.default_path())` rather than hardcoding any rate-model constant, including the newly-named `default_period_ms_by_ecu.seed_period_ms_by_ecu` knob for the 109 undeclared-cycle-time messages.
- Plan 00-06's report can call `GateConfig.config_hash` to stamp every reported figure with the exact assumptions that produced it (T-00-15).
- Plan 00-06/00-07 will overwrite `.planning/phases/00-compression-ratio-gate/00-REPORT.json` with the real aggregate report; at that point the file will finally carry a `thresholds` comparison block, and `00-THRESHOLD.md`'s "Status at the time of writing" paragraph will describe a state that has since changed -- this is expected and does not require an amendment to the threshold numbers themselves (only the status paragraph is a snapshot; the numbers are covered by the separate amendment rule).
- No blockers.

---
*Phase: 00-compression-ratio-gate*
*Completed: 2026-07-31*

## Self-Check: PASSED

All 4 created files (`config/gate.json`, `src/telemetry/measure/config.py`, `tests/test_gate_config.py`, `00-THRESHOLD.md`) found on disk; both task commits (`40a639a`, `6acbbd5`) found in git history; full suite (58 tests) passes with zero regressions.
