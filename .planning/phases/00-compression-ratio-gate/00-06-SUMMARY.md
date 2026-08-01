---
phase: 00-compression-ratio-gate
plan: 06
subsystem: testing
tags: [cantools, cfr, framing-overhead, aggregation, ablation, peak-bitrate, cli]

# Dependency graph
requires:
  - phase: 00-02
    provides: "src/telemetry/wire/{frame_source,dictionary,encoder,decoder}.py — the D-05 CFR encoder/decoder core; report.py/cli.py tracer skeleton"
  - phase: 00-03
    provides: "src/telemetry/measure/classify.py — classify_database, classify_message, category_members, CATEGORIES"
  - phase: 00-04
    provides: "config/gate.json and src/telemetry/measure/config.py — GateConfig, Thresholds, load_gate_config"
  - phase: 00-05
    provides: "src/telemetry/synth/{rates,entropy,generator}.py — full-bus, three-bracket SyntheticFrameSource and assign_rates"
provides:
  - "src/telemetry/wire/overhead.py — D-06 analytic framing overhead: BATCH_HEADER_BYTES/CRC16_BYTES/COBS_BLOCK_BYTES, OverheadBreakdown, cobs_worst_case_overhead, all_in_bytes_per_batch, overhead_breakdown"
  - "src/telemetry/measure/report.py — widened aggregation engine: PerIdStats/CategoryStats/StreamMeasurement, ABLATIONS/ablation_options, measure_stream (frame-iterable, all-in apportionment), peak_windows, bitrate_summary, build_report (per-bracket aggregate/per_id/categories/worst_n/ablations/peaks + meta.threshold_comparison), write_report_json/write_report_csv"
  - "src/telemetry/measure/cli.py — full three-bracket, four-ablation run: --brackets/--ablations/--gate-config/--duration-s/--seed/--only-message/--fail-on-roundtrip-mismatch, writes 00-REPORT.json and 00-REPORT.csv"
  - "tests/test_measure_report.py — 23 tests: framing-overhead formulas plus aggregation-engine behavior on hand-computable inputs"
affects: ["00-07"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Batch-level overhead apportioned to per-ID stats proportional to each ID's share of the batch's clean bytes — D-06's framing cost is paid by the batch as a whole, not by any one CAN ID, so per-ID all-in figures are a fair allocation rather than a literal per-frame formula"
    - "measure_stream widened to accept any frame iterable (not a FrameSource object) so a materialized frame list (list(source.frames())) is built once per bracket and reused across all four D-10 ablations with fresh Encoder/Decoder pairs"
    - "Two-pointer sliding-window sweep over batch-granularity (timestamp_us, bits) pairs for peak_windows; a window at or beyond the run's total duration returns the whole-run average flagged is_whole_run_average=True rather than silently reporting an average as a peak"
    - "meta.threshold_comparison computed only for thresholds.gating_bracket, as a list of {criterion, measured, threshold, headroom_pct, within_threshold} — numbers and a boolean, no verdict string, verified by a test that walks every string value in the emitted report and asserts none matches a verdict-word set"

key-files:
  created:
    - src/telemetry/wire/overhead.py
    - tests/test_measure_report.py
  modified:
    - src/telemetry/measure/report.py
    - src/telemetry/measure/cli.py
    - tests/test_measure_cli_smoke.py

key-decisions:
  - "measure_stream's first parameter was changed from a FrameSource-like `source` object (calling source.frames() internally) to a plain frame iterable. This lets cli.py materialize list(source.frames()) exactly once per bracket and pass that same list to measure_stream four times (once per ablation) without a wrapper class. No existing test locked the old signature (only cli.py called it, which this same plan rewrites), so this was a same-plan interface simplification, not a cross-plan break."
  - "Per-ID all-in bytes/frame is computed by apportioning each batch's overhead_breakdown(...).all_in_bytes back to the IDs in that batch, weighted by each ID's share of the batch's clean bytes. The interface contract specifies the batch-level formula but not how to attribute it per ID; this is the plan author's (executor's) modelling choice, documented here per D-06's own spirit of making every formula auditable rather than opaque."
  - "meta.threshold_comparison holds exactly two criteria — average_kbps and peak_kbps — matching 00-THRESHOLD.md's pre-registered 'pass requires BOTH' condition, computed only for the gating bracket (typical), never for best/worst. peak_kbps is read from peak_windows' output at the label matching thresholds.peak_window_s (1.0 -> \"1s\"), so the threshold window and the reported peak-window band can never silently disagree about which window is meant."
  - "cli.py's --fail-on-roundtrip-mismatch flag cannot actually disable round-trip enforcement: measure_stream always decodes and byte-compares every frame (GATE-01/T-00-23 forbid a path that skips this). Passing --no-fail-on-roundtrip-mismatch only logs a warning and continues enforcing. This satisfies the plan's literal flag requirement without opening the exact hole the plan's own anti-pattern list calls out as the thing 00-06 must never do."
  - "The checksum category's note carries an explicit RESEARCH.md Assumption A2 manual-review caveat (structural detection likely includes false positives — heartbeats, fault codes, SOH values) in addition to the detection-method string, surfaced in every report this tool produces rather than only in RESEARCH.md prose a reader might not open."
  - "The categories block is computed from classify_database(db) over the WHOLE DBC (128 messages), independent of --only-message filtering — a category's message_count always reflects true DBC composition; only frame_count/bytes reflect what was actually emitted in the current run. Confirmed empirically: none of this DBC's five structural categories are genuinely empty (rolling_counter 46, checksum 12, multiplexed 3, high_entropy_analog 58, other 59), so the 'empty bucket carries a note' behavior was tested against a hand-built empty classifications={} input rather than the real DBC."

patterns-established:
  - "Hand-computable test fixtures (_make_measurement helper building StreamMeasurement/PerIdStats directly with known numbers) for report-structure tests (worst_n, categories, threshold_comparison), reserving the real DBC/generator path for tests whose whole point is proving the real encoder/decoder/classifier pipeline agrees with itself (aggregate-sum, round-trip-mismatch, ablation ordering)."

requirements-completed: [GATE-01, GATE-02]

coverage:
  - id: D1
    description: "D-06 analytic framing overhead: cobs_worst_case_overhead's closed form, all_in_bytes_per_batch's strict monotonicity, and overhead_breakdown's clean-vs-all-in split, zero-frames guard, and sanity band (100 frames/batch, 8 clean bytes/frame -> 0.1-0.3 byte/frame additive overhead) — no COBS or CRC implementation written, no import from telemetry.synth/measure"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_cobs_worst_case_overhead_closed_form, test_all_in_bytes_per_batch_zero_payload_matches_header_plus_crc_plus_cobs, test_all_in_bytes_per_batch_strictly_increasing, test_overhead_breakdown_all_in_bytes_matches_batch_formula, test_overhead_breakdown_clean_bytes_per_frame_reconstructs_total, test_overhead_breakdown_overhead_pct_formula, test_overhead_breakdown_zero_frames_raises_value_error_naming_parameter, test_overhead_breakdown_at_100_frames_8_bytes_clean_overhead_is_small_additive_term, test_overhead_breakdown_exposes_all_nine_fields"
        status: pass
    human_judgment: false
  - id: D2
    description: "measure_stream's own round-trip byte-identity check raises RuntimeError (never silently excludes) when a decoded frame does not match the source frame, proven with a decoder poisoned to always return a corrupted payload"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_measure_stream_raises_on_roundtrip_mismatch"
        status: pass
    human_judgment: false
  - id: D3
    description: "Aggregate clean bytes equals the sum of per-ID clean byte totals over a real multi-message synthetic stream"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_aggregate_clean_bytes_equals_sum_over_per_id"
        status: pass
    human_judgment: false
  - id: D4
    description: "peak_windows resolves the arithmetically exact sliding-window peak for a hand-built timeline with a deliberate burst, and reports a window longer than the run's total duration as the whole-run average flagged is_whole_run_average=True rather than silently as a peak"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_peak_windows_exact_value_for_a_deliberate_burst, test_peak_windows_longer_than_run_returns_whole_run_average"
        status: pass
    human_judgment: false
  - id: D5
    description: "bitrate_summary converts a known byte total over a known duration to the arithmetically exact kbit/s figure"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_bitrate_summary_exact_kbps"
        status: pass
    human_judgment: false
  - id: D6
    description: "Each of the three non-full D-10 ablations (no_sequence_byte, raw_payload, no_dictionary) differs from full in exactly one EncoderOptions field, and over the same materialized frame list no_sequence_byte yields strictly fewer total bytes than full while raw_payload and no_dictionary both yield strictly more"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_ablation_options_differs_from_full_in_exactly_one_field, test_ablation_byte_totals_ordering_over_same_frame_list"
        status: pass
    human_judgment: false
  - id: D7
    description: "The categories block's key set is exactly CATEGORIES, and every empty bucket carries a non-empty note naming the detection method (proven with a hand-built empty classification map, since no category is genuinely empty on the real DBC)"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_category_rollup_key_set_and_empty_bucket_notes"
        status: pass
    human_judgment: false
  - id: D8
    description: "worst_n is computed independent of the categorical buckets, has min(worst_n, id_count) entries sorted descending by clean_bytes_per_frame; every ablations entry carries roundtrip_verified=true; meta.threshold_comparison entries carry exactly {criterion, measured, threshold, headroom_pct, within_threshold} with no verdict string anywhere in the emitted report (proven by walking every string value in the document); meta.input_provenance and meta.known_limitation pass through non-empty"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_build_report_worst_n_independent_of_categories_and_threshold_comparison_shape"
        status: pass
    human_judgment: false
  - id: D9
    description: "write_report_csv emits a header row plus exactly one row per (bracket, frame_id, is_extended) combination, with clean_bytes_per_frame and all_in_bytes_per_frame columns present"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_measure_report.py::test_write_report_csv_one_row_per_bracket_and_id"
        status: pass
    human_judgment: false
  - id: D10
    description: "python -m telemetry.measure.cli --duration-s 3 --out-dir <dir> exits 0, writes both 00-REPORT.json and 00-REPORT.csv, with exactly the three bracket keys each carrying >=120 per-ID entries, all four ablations (every one roundtrip_verified=true), a non-empty peaks block, and a worst_n list of the configured length; the generator is constructed exactly once per bracket (grep-confirmed one SyntheticFrameSource( call site); stdout carries exactly one summary line, all progress on stderr; a deliberate round-trip mismatch (isolated unit reproduction) raises rather than being silently counted"
    requirement: "GATE-01"
    verification:
      - kind: integration
        ref: "manual invocation: PYTHONPATH=src python -m telemetry.measure.cli --duration-s 3 --out-dir <tmp>, plus tests/test_measure_cli_smoke.py (8 tests)"
        status: pass
    human_judgment: false
  - id: D11
    description: "Three assumption caveats (bus_assignment.confirmed, bus_targets.confirmed, default_period_ms_by_ecu.confirmed all false) surface in the emitted report's meta, not just in 00-THRESHOLD.md prose a reader might not open"
    requirement: "GATE-01"
    verification:
      - kind: manual_procedural
        ref: "meta.bus_assignment_confirmed, meta.bus_assignment_caveat, meta.bus_targets_caveat, meta.default_period_confirmed fields inspected in a live 00-REPORT.json"
        status: pass
    human_judgment: false

duration: ~70min
completed: 2026-07-31
status: complete
---

# Phase 0 Plan 6: Full-Matrix Report — Per-ID, Per-Category, Worst-N, Ablations, Peak Bit Rate Summary

**Widened the tracer's single-ID, single-ablation report into the full three-bracket x four-ablation matrix report GATE-01/GATE-02 are actually read against: a D-06 analytic clean-vs-all-in overhead split with no COBS/CRC implementation, per-ID/per-category/worst-10 aggregation, sliding-window peak bit rate at batch granularity, and a numbers-only threshold comparison that never emits a verdict — measured typical-bracket all-in average came in at 306.08 kbit/s against the pre-registered 120 kbit/s ceiling, confirming the pre-registered known risk that fixed per-frame header overhead alone can fail this gate before any payload byte is counted.**

## Performance

- **Duration:** ~70 min
- **Tasks:** 3 (all `auto`, Tasks 1-2 `tdd="true"`)
- **Files created:** 2 (`src/telemetry/wire/overhead.py`, `tests/test_measure_report.py`)
- **Files modified:** 3 (`src/telemetry/measure/report.py`, `src/telemetry/measure/cli.py`, `tests/test_measure_cli_smoke.py`)

## Accomplishments

- `src/telemetry/wire/overhead.py` computes the D-06 clean-vs-all-in split as pure arithmetic (`BATCH_HEADER_BYTES=13`, `CRC16_BYTES=2`, `COBS_BLOCK_BYTES=254`, `OverheadBreakdown` dataclass) — no COBS or CRC implementation exists anywhere in this phase, verified by grep against both the module and `requirements-dev.txt`'s unchanged two-package manifest.
- `src/telemetry/measure/report.py` widened into the full aggregation engine: `PerIdStats` enriched post-measurement with `name`/`sender`/`bus`/`rate_source`/`rate_hz`/`categories` from the D-03 rate model and D-04 classifier; `CategoryStats`/`_category_rollup` gives every one of the five `CATEGORIES` an explicit bucket with a note (including a manual-review caveat on `checksum`'s 12 structural candidates); `ABLATIONS`/`ablation_options` implement the four D-10 encoder ablations; `peak_windows` sweeps batch-granularity `(timestamp_us, bits)` pairs with a two-pointer algorithm proven exact against a hand-built burst timeline; `build_report` assembles `brackets.{best,typical,worst}.{aggregate,per_id,categories,worst_n,ablations,peaks}` plus `meta.threshold_comparison` (numbers and a boolean per criterion, no verdict string — proven by a test that walks every string value in the emitted document).
- `src/telemetry/measure/cli.py` now runs the full matrix in one invocation: `--brackets`/`--ablations` (repeatable, default all), the generator materialized exactly once per bracket and reused across all four ablations (grep-confirmed single `SyntheticFrameSource(` call site), `--seed`/`--duration-s` overrides recorded in `meta.seed_source`/`meta.duration_s_source` so an overridden run can never be mistaken for the committed configuration, and both `00-REPORT.json` and `00-REPORT.csv` written per run.
- End-to-end verification (`PYTHONPATH=src python -m telemetry.measure.cli --duration-s 3 --out-dir <tmp>`) confirms all three brackets present with >=120 per-ID entries each, all four ablations `roundtrip_verified=true`, 384 CSV rows, and the pre-registered known risk materializing exactly as 00-THRESHOLD.md predicted: typical-bracket all-in average measured at 306.08 kbit/s against the 120 kbit/s ceiling (`within_threshold: false`, `headroom_pct: -155.1`), and peak at 314.43 kbit/s against 170 kbit/s (`within_threshold: false`, `headroom_pct: -85.0`) — reported as numbers and booleans only, with the go/no-go judgment explicitly left to 00-07's decision document.
- `python -m pytest -q` — 118 tests passing (95 baseline + 13 overhead + 10 aggregation-engine, 0 regressions), including the 8 CLI smoke tests rewritten to the new report shape.

## Task Commits

Each task was committed atomically:

1. **Task 1: Analytic framing overhead and the clean-versus-all-in split** - `a847c92` (test)
2. **Task 2: Aggregation engine — per-ID, per-category, worst-N, ablations, peak windows, bit rate** - `ac44c24` (feat)
3. **Task 3: Full-run CLI and report artifacts on disk** - `fa22930` (feat)

**Plan metadata:** pending (this commit)

_Note: Task 1 is `tdd="true"` — its test/impl split lands as separate content within a single commit here since the RED state (tests failing against the not-yet-created module) was verified interactively before the GREEN implementation was written, matching this plan's tracer/TDD convention of one commit per completed task rather than a strict test-then-feat commit pair. Task 2 followed the same RED-verified-before-GREEN discipline._

## Files Created/Modified

- `src/telemetry/wire/overhead.py` - `BATCH_HEADER_BYTES`/`CRC16_BYTES`/`COBS_BLOCK_BYTES`, `OverheadBreakdown`, `cobs_worst_case_overhead`, `all_in_bytes_per_batch`, `overhead_breakdown`. Module docstring names all four 13-byte header fields. Zero imports from `telemetry.synth`/`telemetry.measure` (grep-verified).
- `src/telemetry/measure/report.py` - `PerIdStats` (widened), `CategoryStats` (new), `StreamMeasurement` (widened with `total_all_in_bytes`/`batch_timeline`), `ABLATIONS`/`ablation_options`, `measure_stream` (widened to accept any frame iterable, apportions batch all-in overhead per-ID), `peak_windows`, `bitrate_summary`, `build_report` (full matrix document + threshold comparison), `write_report_json`, `write_report_csv` (new).
- `src/telemetry/measure/cli.py` - `main()` widened to the three-bracket, four-ablation matrix; `--gate-config`/`--brackets`/`--ablations`/`--duration-s`/`--seed`/`--only-message`/`--fail-on-roundtrip-mismatch`; writes both report artifacts; one-line stdout summary.
- `tests/test_measure_report.py` - 23 tests: 13 for `overhead.py` (Task 1), 10 for the aggregation engine (Task 2) — hand-computable fixtures for structure/formula tests, real DBC/generator fixtures for round-trip and ordering proofs.
- `tests/test_measure_cli_smoke.py` - rewritten (same 8 tests, same intent) for the new `brackets`-keyed report shape, `--brackets` in place of `--bracket`, and the one-line (not empty) stdout contract.

## Decisions Made

- `measure_stream`'s first parameter changed from a `FrameSource`-shaped `source` object to a plain frame iterable, so `cli.py` can materialize `list(source.frames())` once per bracket and pass that same list to `measure_stream` four times (once per ablation) without a wrapper class. No test locked the old signature going in (only `cli.py` called it, itself rewritten in this same plan), so this is a same-plan simplification, not a cross-plan interface break.
- Per-ID all-in bytes/frame is computed by apportioning each batch's `overhead_breakdown(...).all_in_bytes` back to the IDs present in that batch, weighted by each ID's share of the batch's clean bytes — the interface contract specifies the batch-level formula but leaves per-ID attribution unspecified; this proportional-share allocation is the executor's documented modelling choice.
- `meta.threshold_comparison` holds exactly two criteria (`average_kbps`, `peak_kbps`), matching 00-THRESHOLD.md's "pass requires BOTH" condition, computed only for `thresholds.gating_bracket` ("typical") — never for best/worst, which are reported for context only per 00-THRESHOLD.md.
- `--fail-on-roundtrip-mismatch` cannot actually disable round-trip verification: `measure_stream` always decodes and byte-compares every frame regardless of the flag (GATE-01/T-00-23 forbid a path that skips this). Passing `--no-fail-on-roundtrip-mismatch` logs a warning and continues enforcing rather than opening exactly the hole this plan's own anti-pattern list warns against.
- The `checksum` category's note carries an explicit RESEARCH.md Assumption A2 manual-review caveat (its 12 structural candidates are suspected false positives — heartbeats, fault codes, SOH values) in every report this tool produces, not only in RESEARCH.md prose.
- Categories are rolled up from `classify_database(db)` over the whole 128-message DBC, independent of `--only-message` filtering, so `message_count` always reflects true DBC composition even when a narrowed run's `frame_count`/bytes are zero for an unfiltered-out category.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Rewrote `tests/test_measure_cli_smoke.py` for the widened CLI's report shape**
- **Found during:** Task 3, immediately after widening `cli.py`'s `main()` per the interface contract (replacing the single-value `--bracket` flag and flat `{meta, aggregate, per_id}` report shape with `--brackets`/`--ablations` and the nested `{meta, brackets: {best, typical, worst}}` shape).
- **Issue:** All 8 existing smoke tests asserted the old flat report schema and the old single-bracket CLI flags — a direct, unavoidable consequence of this plan's own interface contract (Task 3's action block explicitly requires replacing `--bracket` with repeatable `--brackets`/`--ablations`). The orchestrator's pre-flight note for this plan explicitly anticipated this and pre-authorized the rewrite as a documented Rule 3 deviation.
- **Fix:** Rewrote all 8 tests against the new shape, preserving each test's original intent: end-to-end wiring, gate.json defaulting (seed AND duration, since both now come from config), `--seed` override with `seed_source` distinguishability, cross-run determinism (compared on `report["brackets"]` rather than the whole document, since `meta.generated_at` differs run to run), stdout cleanliness (now "exactly one summary line" rather than "empty," per Task 3's explicit stdout contract), and all-three-bracket coverage via the new `--brackets` flag.
- **Files modified:** `tests/test_measure_cli_smoke.py`.
- **Verification:** `python -m pytest tests/test_measure_cli_smoke.py -q` — all 8 tests pass against the new interface; `python -m pytest -q` — 118 tests passing, zero regressions elsewhere.
- **Committed in:** `fa22930` (Task 3 commit)

**2. [Rule 1 - Bug] Fixed `cli.py` crashing on a `--brackets` selection that excludes the configured gating bracket**
- **Found during:** Task 3, running `tests/test_measure_cli_smoke.py::test_cli_accepts_every_entropy_bracket[best]`/`[worst]` after the initial `main()` implementation.
- **Issue:** The final one-line stdout summary unconditionally indexed `report["brackets"][config.thresholds.gating_bracket]` ("typical"), which raised `KeyError` for any `--brackets` invocation that ran only `best` or `worst`.
- **Fix:** Falls back to summarizing whichever bracket actually ran (with a stderr warning naming the substitution) when the gating bracket wasn't requested, so a narrowed run never crashes and the substitution is never silently mistaken for the real gating figure.
- **Files modified:** `src/telemetry/measure/cli.py`.
- **Verification:** `python -m pytest tests/test_measure_cli_smoke.py -q` — all 8 pass, including both previously-failing parametrized cases.
- **Committed in:** `fa22930` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 3 — an anticipated, pre-authorized test rewrite driven by this plan's own interface contract; 1 Rule 1 — a bug in the new code introduced within this same plan, caught before commit)
**Impact on plan:** No scope creep. Both fixes are confined to files this plan already owns (`cli.py`, `test_measure_cli_smoke.py`), and both were necessary for the plan's own stated success criteria ("no regression to the existing 95 tests, including the 8 CLI smoke tests" and "the CLI actually runs end to end").

## Issues Encountered

None beyond the deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `.planning/phases/00-compression-ratio-gate/00-REPORT.json` and `00-REPORT.csv` are producible on demand via `PYTHONPATH=src python -m telemetry.measure.cli --out-dir .planning/phases/00-compression-ratio-gate` (not committed by this plan — this plan proves the tool works end to end; committing the actual gate-decision artifacts is 00-07's job per the phase's `<output>` spec).
- The measured typical-bracket figures (306.08 kbit/s average, 314.43 kbit/s peak, both over their respective ceilings) are ready for 00-07's decision document. This is the pre-registered known risk from 00-THRESHOLD.md materializing as measured fact, not a surprise — 00-07 should read it against that document's own framing (fixed per-frame header cost at the assumed ~3,700+ fps combined rate, not a flaw in the encoder itself) and against the three still-`confirmed: false` assumption caveats this report's `meta` surfaces (`bus_assignment_confirmed`, `bus_targets` caveat, `default_period_confirmed`).
- No blockers. All three tasks' acceptance criteria and the plan's own `<verification>` block (whole-suite pass, live CLI run, artifacts appear in `git status --porcelain` when written under the phase directory, no verdict string anywhere in `report.py`) are satisfied.

---
*Phase: 00-compression-ratio-gate*
*Completed: 2026-07-31*

## Self-Check: PASSED

All 6 files (2 created, 4 modified — counting this SUMMARY) found on disk; all 4 commits (`a847c92`, `ac44c24`, `fa22930`, `0a7cbe8`) found in git history. `python -m pytest -q` — 118 tests passing, zero regressions.
