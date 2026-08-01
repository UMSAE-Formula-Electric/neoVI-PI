---
phase: 00-compression-ratio-gate
fixed_at: 2026-08-01T00:00:00Z
review_path: .planning/phases/00-compression-ratio-gate/00-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 00: Code Review Fix Report

**Fixed at:** 2026-08-01T00:00:00Z
**Source review:** .planning/phases/00-compression-ratio-gate/00-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (0 Critical, 5 Warning; Info findings out of scope per instruction)
- Fixed: 5
- Skipped: 0

All five Warning-severity findings were validation/guard-clause gaps: each
accepted a "just barely valid per the loader" input and then crashed or
silently produced a wrong number deep in the measure/synth layer instead of
raising the named `GateConfigError`/`RateModelError`/`ValueError` the rest of
this codebase promises. None of them are exercised by the checked-in
`config/gate.json` (that is exactly why the review flagged them as latent),
so every fix is additive hardening, not a change to computed output.

**Critical constraint verification:** after applying all five fixes, the
full-matrix CLI was re-run at the committed `config/gate.json`
(`config_hash=1dcefe671220`) into a scratch directory and diffed against the
published `.planning/phases/00-compression-ratio-gate/00-REPORT.json`. The
two report bodies are byte-identical after stripping only the
`generated_at` timestamp and the machine-local `dbc_path` string:
- Published: `typical.aggregate.kbps_all_in = 305.13072`, `worst.aggregate.kbps_all_in = 344.51352`
- Re-run: `typical.aggregate.kbps_all_in = 305.13072`, `worst.aggregate.kbps_all_in = 344.51352`
- `meta.config_hash` matches (`1dcefe671220`) in both.

No arithmetic, rounding, ordering, apportionment, or default value exercised
by the committed config changed.

## Fixed Issues

### WR-01: `assign_rates` can crash with an unhelpful `KeyError` on an unmapped bus

**Files modified:** `src/telemetry/synth/rates.py`, `tests/test_synth_stream.py`
**Commit:** `32c4655`
**Applied fix:** `_resolve_bus` now raises a named `RateModelError` (naming
the unresolved sender) when a message's sender is absent from
`bus_assignment.by_ecu` *and* `bus_assignment.default_bus` is unset, instead
of returning `None` and letting `assign_rates` crash later with a bare
`KeyError: None` against the per-bus fps dictionaries. The committed
`gate.json` always sets `default_bus`, so this path is unreachable at the
checked-in config — verified by the full report re-run reproducing exactly.
Added `test_resolve_bus_raises_rate_model_error_when_default_bus_unset`,
which strips `default_bus` from a copy of the real `gate_config` fixture and
asserts the named exception fires for the DBC's existing no-declared-sender
messages.

### WR-02: `default_period_ms_by_ecu.seed_period_ms_by_ecu` is never validated by the config loader

**Files modified:** `src/telemetry/measure/config.py`, `tests/test_gate_config.py`
**Commit:** `185ba56`
**Applied fix:** Added `_parse_default_period_ms_by_ecu`, mirroring the
existing `_parse_bus_target` pattern: requires `seed_period_ms_by_ecu` to be
a JSON object, requires the `NO_SENDER` fallback key
(`telemetry.synth.rates.NO_SENDER_KEY`'s value, duplicated as a local
constant to avoid a config↔rates import cycle — rates.py already imports
`GateConfig` from config.py) to be present, and validates every value is a
positive number via the existing `_require_positive_number` helper.
`load_gate_config` now calls this validator instead of the previous
bare-dict-type check. The committed `gate.json`'s `seed_period_ms_by_ecu`
has a `NO_SENDER` key and nine positive integer values, so it passes
unchanged. Added four tests covering missing map, missing `NO_SENDER`,
non-numeric value, and non-positive value.

### WR-03: `thresholds.peak_window_s` is never cross-checked against `peak_windows_s`

**Files modified:** `src/telemetry/measure/report.py`, `tests/test_measure_report.py`
**Commit:** `8ee93a7`
**Applied fix:** `_threshold_comparison` now raises `ValueError` (naming
`thresholds.peak_window_s`, the label it produced, and the actual
`peak_windows_s` keys available) when the computed window label is not a
key of `gating["peaks"]["windows"]`, instead of silently defaulting to
`{"peak_bits_per_s": 0.0}` and reporting the peak criterion as trivially
passing. `ValueError` was chosen over a new exception class to match this
module's existing precedent (`overhead_breakdown` raises `ValueError` for
its own internal-invariant violations; `GateConfigError` is reserved for
`config.py`'s load-time checks). The committed `gate.json` has
`peak_windows_s=[0.1, 1.0, 10.0]` and `thresholds.peak_window_s=1.0`, which
already matches, so this path is unreachable at the checked-in config.
Added `test_build_report_raises_when_peak_window_s_not_in_peak_windows_s`.

### WR-04: `peak_windows`' whole-run-average fallback is not independent of the requested window length

**Files modified:** `src/telemetry/measure/report.py`, `tests/test_measure_report.py`
**Commit:** `355e412`
**Applied fix:** For a zero-duration timeline (`run_duration_us <= 0`, e.g.
a single batch), `peak_windows` now computes one
`zero_duration_whole_run_avg = total_bits / min(windows_s)` up front and
reuses that single value for every requested window in that branch, instead
of dividing by whichever `window_s` the loop happens to be on. This is the
one fix in this batch that changes arithmetic on a genuine (if
never-hit-by-the-committed-config) code path rather than only adding a
guard clause — flagged below for human confirmation per the logic-fix
caveat in the fixer's verification strategy, even though it is a Tier
1+Tier 2 verified, test-covered change. The full 100s-duration committed
run spans many batches and never reaches `run_duration_us <= 0`, so the
published report is unaffected (confirmed by the byte-identical report
re-run). Added
`test_peak_windows_zero_duration_timeline_reports_same_average_for_every_window`,
which asserts a single-batch timeline reports one consistent average across
0.1s/1.0s/10.0s windows.

**Note for developer:** this finding's fix is logic-shaped (it changes what
number is computed for the previously-inconsistent edge case), not pure
validation. Recommend a manual read of the new `zero_duration_whole_run_avg`
formula in `src/telemetry/measure/report.py` before relying on it — the
`min(windows_s)` denominator choice is one reasonable convention among a few
possible ones (the review's alternative suggestion was a nominal-duration
fallback or an explicit "undefined duration" flag), and no currently-run
gate configuration exercises this branch to cross-check it against real
data.

### WR-05: `--duration-s` CLI override bypasses `config.py`'s positive-duration validation

**Files modified:** `src/telemetry/measure/cli.py`, `tests/test_measure_cli_smoke.py`
**Commit:** `1417bc5`
**Applied fix:** Added a check immediately after `args = p.parse_args()`
that logs `[ERROR] --duration-s must be a positive number, got ...` and
raises `SystemExit(1)` when `--duration-s` is supplied and is `<= 0`,
mirroring the `DbcLoadError`/`GateConfigError` handling already present a
few lines below. Any run that does not pass `--duration-s` (including every
run at the committed config, which is the default `--duration-s`-unset
path) is unaffected. Added
`test_cli_rejects_non_positive_duration_s` (parametrized over `"0"` and
`"-5"`), asserting `SystemExit(1)` and that no report file is written.

## Skipped Issues

None — all five in-scope Warning findings were fixed.

---

_Fixed: 2026-08-01T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
