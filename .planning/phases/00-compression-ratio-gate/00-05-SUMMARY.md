---
phase: 00-compression-ratio-gate
plan: 05
subsystem: testing
tags: [cantools, synthetic-generator, rate-model, entropy-brackets, multiplexed-signals, seeded-random]

# Dependency graph
requires:
  - phase: 00-02
    provides: "src/telemetry/wire/{frame_source,dictionary,encoder,decoder}.py, the D-05 CFR encoder/decoder core, plus generator.py's tracer single-behaviour form"
  - phase: 00-03
    provides: "src/telemetry/measure/classify.py — classify_database, classify_message, classify_signal, category_members, CATEGORIES"
  - phase: 00-04
    provides: "config/gate.json and src/telemetry/measure/config.py — GateConfig, EntropyBracket, BusTarget, load_gate_config"
provides:
  - "src/telemetry/synth/rates.py — D-03 rate model: MessageRate, RateModelError, assign_rates, bus_totals"
  - "src/telemetry/synth/entropy.py — D-02 best/typical/worst payload mutation: BRACKET_NAMES, PayloadMutator, derive_seed"
  - "src/telemetry/synth/generator.py — widened SyntheticFrameSource: full-bus, three-bracket, seeded, mux-cycling frame source"
  - "tests/test_synth_stream.py — 29 tests: rate fidelity, entropy separation, mux cycling, full-stream determinism/coverage"
affects: ["00-06", "00-07"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-bus scale-factor solve: declared_fps + scale * seed_fps == target_fps, applied only to undeclared-rate messages on that bus — never clamps or drops a message to make the arithmetic work"
    - "Per-message, per-bracket deterministic seed derivation via SHA-256 (derive_seed) instead of Python's salted hash() — stable across interpreter runs so adding a DBC message never shifts another message's stream"
    - "Raw-integer payload mutation (message.encode(scaling=False, padding=True, strict=False)) with mutation domain computed from bit-width (2**length), not declared physical min/max — confirmed empirically that strict=False disables the declared-range check but cantools still enforces the bit-width range"
    - "Round-robin multiplexer selector cycling keyed on sorted(set(multiplexer_ids)) — the entropy layer's structural answer to RESEARCH.md Pitfall 1 (holding a mux ID's selector constant flatters its measured bytes/frame)"

key-files:
  created:
    - src/telemetry/synth/rates.py
    - src/telemetry/synth/entropy.py
    - tests/test_synth_stream.py
  modified:
    - src/telemetry/synth/generator.py
    - tests/conftest.py
    - tests/test_wire_roundtrip.py

key-decisions:
  - "Resolved the interface contract's abbreviated `config.default_period_ms_by_ecu[sender]` lookup against the actual gate.json shape, which nests the per-ECU seed periods one level deeper at `default_period_ms_by_ecu.seed_period_ms_by_ecu`, with `NO_SENDER` (not `_default`) as the no-sender fallback key. Implemented against the real, checked-in JSON structure rather than the plan's shorthand prose."
  - "A message's sender is resolved from `message.senders[0]`, treating both an empty senders list and the DBC's `Vector__XXX` placeholder as 'no declared sender' (falls back to `bus_assignment.default_bus` / `NO_SENDER` seed period). Verified via direct cantools measurement that this DBC uses the empty-list form (16 of 128 messages), not the Vector__XXX placeholder, but both are handled identically per the interface contract's stated intent."
  - "Payload mutation works in the signal's full representable bit range (`2**length` for unsigned, `-(2**(length-1))..2**(length-1)-1` for signed), not its declared physical min/max — confirmed empirically before relying on it that `message.encode(..., strict=False)` disables the declared-range check but still enforces the bit-width range, so a mutation domain wider than the declared range would raise rather than silently wrap."
  - "The entropy classifier reuses `telemetry.measure.classify.classify_signal` unmodified. Because that classifier collapses every signal in a multiplexed message to the single `multiplexed` category (by cantools' own `is_multiplexed()` check), multiplexed-message signals fall through to the mutator's 'every other signal' branch (discrete_change_prob redraw) rather than the rolling_counter/checksum/high_entropy_analog branches — this is a direct, correct consequence of not re-deriving the classification, not a gap."
  - "SyntheticFrameSource.rates is always computed from the *full*, unfiltered message set (via assign_rates(db, config)) regardless of only_message_names — filtering happens only when walking events in frames(). This is what makes a full-bus run and a narrowed run agree byte-for-byte on a shared ID's schedule, and is what the plan's key_link 'assign_rates produces the per-message emission schedule the generator walks' requires."

patterns-established:
  - "Session-scoped `gate_config` fixture in tests/conftest.py (parallel to the existing `dbc` fixture) — loads config/gate.json exactly once per test session via the typed loader, for every test file that needs the checked-in assumptions rather than a hand-rolled GateConfig literal."

requirements-completed: [GATE-01, GATE-02]

coverage:
  - id: D1
    description: "All 128 messages get exactly one MessageRate; 19 declared-cycle-time messages keep their exact GenMsgCycleTime period; the remaining 109 get a seed period scaled per bus so bus1/bus2 totals land within 2% of gate.json's target_fps (measured: bus1 2900.0005 vs target 2900, bus2 830.0050 vs target 830), combined ~3,730 fps within the 3,500-4,100 documented bracket"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_synth_stream.py::test_assign_rates_covers_every_message, test_declared_cycle_time_rate_source_and_period, test_bus_totals_within_two_percent_of_targets, test_combined_bus_totals_bracket_documented_range, test_rate_source_count_matches_measured_cycle_time_count"
        status: pass
    human_judgment: false
  - id: D2
    description: "A bus whose declared-cycle-time messages alone already meet or exceed its target_fps raises RateModelError naming the bus, the declared total, and the target, rather than silently clamping or dropping a message"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_synth_stream.py::test_impossible_bus_target_raises_rate_model_error"
        status: pass
    human_judgment: false
  - id: D3
    description: "Three entropy brackets (best/typical/worst) genuinely differ: strictly increasing analog-signal change-count and strictly increasing mean Hamming distance between consecutive payloads across best < typical < worst, for a message containing both a rolling counter and a high_entropy_analog signal; rolling-counter signals increment by exactly 1 modulo 2**length every call"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_synth_stream.py::test_high_entropy_analog_bracket_change_count_increases, test_hamming_distance_increases_strictly_across_brackets, test_payload_mutator_rolling_counter_increments_by_one_modulo_length"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every multiplexed message cycles its full declared selector set round-robin, never repeats a selector on consecutive calls, and CAN_ENERGY_METER_TEMPERATURE reaches at least 7 distinct selector values — no message is held at a constant mux selector to flatter its measured bytes/frame"
    requirement: "GATE-02"
    verification:
      - kind: unit
        ref: "tests/test_synth_stream.py::test_multiplexed_selector_cycles_through_full_set, test_multiplexed_selector_never_repeats_consecutively, test_energy_meter_temperature_reaches_at_least_seven_selectors"
        status: pass
    human_judgment: false
  - id: D5
    description: "The full-bus SyntheticFrameSource merges all 128 messages' schedules into one non-decreasing-timestamp stream whose combined rate lands between 3,400-4,200 fps for each of the three brackets over a 2-second run; the same seed+config reproduces a byte-identical frame list, a different seed diverges, and only_message_names narrows the stream without changing the schedule of any surviving message"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_synth_stream.py::test_full_bus_run_combined_rate_within_range, test_full_bus_run_timestamps_non_decreasing, test_full_bus_run_covers_all_message_ids_over_sufficient_duration, test_full_bus_run_deterministic_same_seed_identical_frames, test_full_bus_run_different_seed_diverges, test_only_message_names_matches_full_bus_subset_timestamps, test_generator_rates_attribute_has_one_entry_per_message"
        status: pass
    human_judgment: false
  - id: D6
    description: "The multiplexed category's measured bytes/frame is not better than the high-entropy-analog category's (backstop truth) — deferred: this compares measured per-category numbers that only exist once plan 00-06 runs the report over the full-bus stream this plan produces"
    requirement: "GATE-02"
    verification: []
    human_judgment: true
    rationale: "This plan's own must_haves.truths block authors this as a backstop verification because it requires measured per-category bytes/frame numbers that do not exist until plan 00-06's report runs against the generator this plan built. Structural correctness of mux cycling (D4) is independently proven here; the comparative measurement itself is 00-06's job."

duration: 35min
completed: 2026-07-31
status: complete
---

# Phase 0 Plan 5: Full-Bus Synthetic Frame Source (Rate Model, Entropy Brackets, Mux Cycling) Summary

**Widened the tracer's single-behaviour synthetic generator to all 128 DBC messages: a D-03 rate model that honours 19 declared `GenMsgCycleTime` periods exactly and scales the other 109 to hit `config/gate.json`'s documented ~2,900/830 fps bus loads, three D-02 entropy brackets whose Hamming-distance separation is asserted (not assumed), and round-robin multiplexer selector cycling that proves `CAN_ENERGY_METER_TEMPERATURE`'s 7 mux values are never held constant.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3 (all `auto`, Tasks 1-2 `tdd="true"`)
- **Files created:** 3 (`src/telemetry/synth/rates.py`, `src/telemetry/synth/entropy.py`, `tests/test_synth_stream.py`)
- **Files modified:** 3 (`src/telemetry/synth/generator.py`, `tests/conftest.py`, `tests/test_wire_roundtrip.py`)

## Accomplishments

- `assign_rates(db, config)` gives every one of the 128 messages exactly one `MessageRate`; the 19 messages measured to declare a `GenMsgCycleTime` (re-verified against `cantools`, never hardcoded) keep that exact period, and the other 109 get a scaled seed period so bus1 lands at 2900.0005 fps (target 2900) and bus2 at 830.0050 fps (target 830) — both within 0.001% of `gate.json`'s documented targets, combined ~3,733 fps within the 3,500-4,100 bracket the plan required.
- An impossible bus target (declared-cycle-time total alone meeting or exceeding `target_fps`) raises `RateModelError` naming the bus, the declared total, and the target — proven by constructing a deliberately-broken config via `dataclasses.replace`, never by editing the checked-in `gate.json`.
- `PayloadMutator` proves the three entropy brackets genuinely differ: mean Hamming distance between consecutive payloads is strictly increasing (best 5.95 < typical 6.99 < worst 10.84 bits, measured on `M192_Command_Message`), and the count of analog-signal value changes over 1,000 calls is strictly increasing (27 < 387 < 938) — the honesty gate the plan's `<action>` block called for.
- Multiplexed messages cycle their full declared selector set round-robin and never repeat a selector on consecutive calls; `CAN_ENERGY_METER_TEMPERATURE` reaches all 7 of its declared selector values within 7 consecutive calls — the structural mitigation for RESEARCH.md Pitfall 1 (T-00-18 in this plan's threat register).
- `SyntheticFrameSource` now yields a full-bus, three-bracket, seeded stream: 7,466 frames over a 2-second run for every bracket (3,733 fps), non-decreasing timestamps, byte-identical output for the same seed+config, a different stream for a different seed, and an `only_message_names`-narrowed run whose selected ID's timestamps exactly match the corresponding subset of a full-bus run.
- `python -m pytest -q` — 87 tests passing (58 pre-existing + 29 new), zero regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Rate model — declared cycle times honoured, the rest scaled to the documented bus loads** - `a95fa8b` (feat)
2. **Task 2: Entropy brackets — three genuinely different payload-mutation models** - `cffd22a` (feat)
3. **Task 3: Full-bus generator — merge the schedules and prove the stream matches the model** - `7514e74` (feat)

**Plan metadata:** pending (this commit)

## Files Created/Modified

- `src/telemetry/synth/rates.py` - `MessageRate`, `RateModelError`, `assign_rates`, `bus_totals`. Module docstring names D-03 and states bus assignment/default periods are modelled, not DBC-derived. No DBC-count literal (128/109/19) appears anywhere in the file (asserted by test).
- `src/telemetry/synth/entropy.py` - `BRACKET_NAMES`, `PayloadMutator`, `derive_seed`. Reuses `telemetry.measure.classify.classify_signal` for the rolling_counter/checksum/high_entropy_analog split rather than re-deriving it. Every random draw goes through the caller-supplied `random.Random` instance; grep confirms zero global `random.*` calls.
- `src/telemetry/synth/generator.py` - `SyntheticFrameSource` widened to `(db, dictionary, config, bracket_name, duration_s=None, only_message_names=None)`. Builds one `PayloadMutator` per message from `entropy.derive_seed`, merges `assign_rates`' per-message schedules into one ordered stream, exposes `.rates` (the full, unfiltered `MessageRate` list) as an attribute. Still zero threading/queue imports.
- `tests/test_synth_stream.py` - 29 new tests across three sections: rate model (11), entropy brackets (10), full-bus generator (8).
- `tests/conftest.py` - added session-scoped `gate_config` fixture (loads `config/gate.json` once per session via `load_gate_config(GateConfig.default_path())`), shared by this plan's tests and the `test_wire_roundtrip.py` fix below.
- `tests/test_wire_roundtrip.py` - both `SyntheticFrameSource(...)` call sites updated from the old `seed=42` keyword to the new `(dbc, dictionary, gate_config, "typical", duration_s=..., only_message_names=...)` signature (see Deviations).

## Decisions Made

- Resolved the interface contract's shorthand `config.default_period_ms_by_ecu[sender]` against the actual `gate.json` shape, which nests the per-ECU seed periods one level deeper at `default_period_ms_by_ecu.seed_period_ms_by_ecu` with `NO_SENDER` (not `_default`) as the no-sender fallback key — implemented against the real, checked-in JSON rather than the plan's abbreviated prose.
- Payload mutation operates on each signal's full representable bit range (`2**length` unsigned / signed two's-complement range), not its declared physical min/max, after confirming empirically that `message.encode(..., strict=False)` disables the *declared-range* check but still enforces the *bit-width* range (an out-of-bit-range raw value raises `Unsigned integer value ... out of range`).
- Left `src/telemetry/measure/cli.py`'s existing `SyntheticFrameSource(...)` call site untouched even though it now targets the old signature — `00-06-PLAN.md` already owns widening `cli.py`'s `main()` to the new signature as part of running the full three-bracket, four-ablation matrix, and no test in the suite exercises `cli.py` directly (verified via grep), so this is not a regression to the 87 passing tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated `tests/test_wire_roundtrip.py`'s two `SyntheticFrameSource` call sites to the new constructor signature**
- **Found during:** Task 3, immediately after widening `SyntheticFrameSource`'s constructor per the interface contract (removing the standalone `seed` parameter in favor of `config`/`bracket_name`).
- **Issue:** `tests/test_wire_roundtrip.py::test_traced_message_roundtrip_byte_identical` and `test_ablation_roundtrip_byte_identical` both called `SyntheticFrameSource(dbc, dictionary, seed=42, duration_s=..., only_message_names=...)` — the old signature. This is a direct, mechanical consequence of implementing this plan's own interface contract exactly as specified; leaving it unfixed would break 9 of the existing 58 tests (the `test_ablation_roundtrip_byte_identical` parametrization has 8 cases, plus the 1 traced-message test), violating this plan's own "no regression to the existing 58 tests" success criterion.
- **Fix:** Added a session-scoped `gate_config` fixture to `tests/conftest.py` and updated both call sites to `SyntheticFrameSource(dbc, dictionary, gate_config, "typical", duration_s=..., only_message_names=...)`, preserving each test's original `duration_s` and `only_message_names` values exactly.
- **Files modified:** `tests/conftest.py`, `tests/test_wire_roundtrip.py`.
- **Verification:** `python -m pytest -q` — all 87 tests pass, including all 9 previously-affected round-trip tests (still asserting byte-identical round-trip and, for the traced-message test, at least one CFR shorter than the 14-byte full-header-plus-payload size).
- **Committed in:** `7514e74` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — a call-site break directly and unavoidably caused by implementing this plan's own interface contract)
**Impact on plan:** No scope creep beyond the plan's own files_modified list in spirit — the fix is confined to adapting two existing call sites and one shared test fixture to a signature change this plan's interface contract explicitly mandated, not new functionality. `src/telemetry/measure/cli.py`'s equivalent call site was deliberately left for `00-06-PLAN.md`, which already owns that file.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 00-06 can call `SyntheticFrameSource(db, dictionary, config, bracket_name, only_message_names=...)` directly for its three-bracket, four-ablation report matrix, and can read `source.rates` for per-message `bus`/`rate_source` alongside per-ID bytes without recomputing the rate model.
- Plan 00-06 owns widening `src/telemetry/measure/cli.py`'s `main()` to the new `SyntheticFrameSource` signature (already its own plan scope) — until then, `python -m telemetry.measure.cli` will raise a `TypeError` on the old `seed=` keyword; this is expected and does not affect the 87-test suite (no test invokes `cli.py` directly).
- The "multiplexed category's measured bytes/frame is not better than high-entropy-analog's" backstop truth (D6 above) is intentionally deferred to plan 00-06's report — this plan proves the structural mechanism (real selector cycling, no held-constant mux ID) but the comparative measurement itself requires 00-06's per-category aggregation.
- No blockers.

---
*Phase: 00-compression-ratio-gate*
*Completed: 2026-07-31*

## Self-Check: PASSED

All 7 files (3 created, 4 modified) found on disk; all 4 commits (`a95fa8b`, `cffd22a`, `7514e74`, `6f36dcc`) found in git history. Full suite `python -m pytest -q` — 87 tests passing, zero regressions.
