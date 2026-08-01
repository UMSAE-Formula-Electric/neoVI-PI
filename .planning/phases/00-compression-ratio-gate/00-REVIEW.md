---
phase: 00-compression-ratio-gate
reviewed: 2026-08-01T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - src/telemetry/__init__.py
  - src/telemetry/measure/__init__.py
  - src/telemetry/measure/classify.py
  - src/telemetry/measure/cli.py
  - src/telemetry/measure/config.py
  - src/telemetry/measure/report.py
  - src/telemetry/synth/__init__.py
  - src/telemetry/synth/entropy.py
  - src/telemetry/synth/generator.py
  - src/telemetry/synth/rates.py
  - src/telemetry/wire/__init__.py
  - src/telemetry/wire/decoder.py
  - src/telemetry/wire/dictionary.py
  - src/telemetry/wire/encoder.py
  - src/telemetry/wire/frame_source.py
  - src/telemetry/wire/overhead.py
  - tests/__init__.py
  - tests/conftest.py
  - tests/test_classify.py
  - tests/test_dbc_ground_truth.py
  - tests/test_gate_config.py
  - tests/test_measure_cli_smoke.py
  - tests/test_measure_report.py
  - tests/test_synth_stream.py
  - tests/test_wire_roundtrip.py
findings:
  critical: 0
  warning: 5
  info: 3
  total: 8
status: issues_found
---

# Phase 00: Code Review Report

**Reviewed:** 2026-08-01T00:00:00Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

I read every file in `src/telemetry/{wire,synth,measure}` and every test that
exercises them, with the encoder/decoder round-trip as the highest-scrutiny
target per the phase's own D-05/D-09 framing. I traced the CFR header pack
order (`encoder.py`) against the unpack order (`decoder.py`) field-by-field,
the XOR-delta/trim/restore path, the keyframe-forcing-on-DLC-change logic,
and both the dictionary and no-dictionary ablation branches. I could not
find an asymmetry between the two — the extensive round-trip test suite
(`test_wire_roundtrip.py`) genuinely covers the cases that would expose one
(DLC change, sequence wraparound, both ID kinds, all four ablations). The
known past defect class named in the task context (a signature drift between
`SyntheticFrameSource.__init__` and `cli.py`'s call site) is also not present
today — `cli.py`'s keyword arguments match the current constructor exactly.

What I did find is a cluster of **validation gaps in the measure/synth
layer**: several places accept a "just barely valid per the loader" config
or CLI input and then crash with an unhelpful raw `KeyError`/produce a
silently-inconsistent number instead of the named, loud `GateConfigError`
the rest of `config.py` promises. None of these manifest with the
checked-in `config/gate.json` today (that's exactly why they're latent),
but they contradict this codebase's own stated design philosophy
("never a silent default... every failure raises GateConfigError naming
the offending key and value") closely enough that a future config edit
(e.g. removing `bus_assignment.default_bus`, or trimming
`peak_windows_s`) would reintroduce it without any test currently guarding
against it. None of these are in `telemetry.wire` (the D-05 load-bearing
core Phase 1/4 import), so none are BLOCKER-severity by the phase's own
criteria — but they are exactly the kind of "test suite stayed green
because nothing exercised the wiring" gap the task context asked me to
look for, just in the config/rate layer rather than the CLI layer this
time.

## Warnings

### WR-01: `assign_rates` can crash with an unhelpful `KeyError` on an unmapped bus

**File:** `src/telemetry/synth/rates.py:83-91, 133-139`
**Issue:** `_resolve_bus` returns `None` whenever a message's sender is not
in `bus_assignment.by_ecu` *and* `bus_assignment.default_bus` is absent
(`config.py` only validates `default_bus` when it is present — see
`config.py:349-354` — it is never required). `assign_rates` then does
`declared_fps_by_bus[record["bus"]] += ...` / `seed_fps_by_bus[record["bus"]] += ...`
(rates.py:135, 139) against dictionaries that were only pre-seeded with the
real `bus_targets` keys (rates.py:133, 137). A `None` bus key raises a bare
`KeyError: None` from deep inside the rate model instead of the
`RateModelError`/`GateConfigError`-style named exception every other
failure path in this module and `config.py` produces. The checked-in
`gate.json` always sets `default_bus`, so this is latent, not live — but
nothing prevents a future edit from dropping it.
**Fix:** Either require `default_bus` in `config.py`'s loader (add it to
the equivalent of a required sub-key check the way `by_ecu` is required),
or have `_resolve_bus` raise a named `RateModelError` when it cannot
resolve a bus, e.g.:
```python
def _resolve_bus(sender, config):
    by_ecu = config.bus_assignment.get("by_ecu", {})
    default_bus = config.bus_assignment.get("default_bus")
    if sender is not None and sender in by_ecu:
        return by_ecu[sender]
    if default_bus is not None:
        return default_bus
    raise RateModelError(
        f"no bus resolvable for sender={sender!r}: not in by_ecu and "
        f"bus_assignment.default_bus is unset"
    )
```

### WR-02: `default_period_ms_by_ecu.seed_period_ms_by_ecu` is never validated by the config loader

**File:** `src/telemetry/measure/config.py:356-360` (loader) vs.
`src/telemetry/synth/rates.py:94-101` (consumer)
**Issue:** `load_gate_config` checks only that `default_period_ms_by_ecu`
is a JSON object (config.py:356-360) — it never validates that the nested
`seed_period_ms_by_ecu` map exists, that it carries the `NO_SENDER`
fallback key `rates.py`'s `_seed_period_ms` unconditionally falls back to
(`NO_SENDER_KEY`, rates.py:100-101), or that its values are numeric. A
malformed or trimmed `seed_period_ms_by_ecu` (missing `NO_SENDER`, missing
an ECU that has no `GenMsgCycleTime`, or a non-numeric value) raises a raw
`KeyError`/`TypeError`/`ValueError` from `float(seed_map[key])`
(rates.py:101) at measurement time, not a `GateConfigError` naming the
offending key at load time — the exact class of failure `config.py`'s own
module docstring says this loader exists to prevent ("an unknown top-level
key, a missing required key... each raise `GateConfigError`... never a
silent default").
**Fix:** Add a `_parse_default_period_ms_by_ecu` validator (mirroring
`_parse_bus_target`) that requires `seed_period_ms_by_ecu` to be a dict,
requires `NO_SENDER` to be present, and validates every value is a
positive number.

### WR-03: `thresholds.peak_window_s` is never cross-checked against `peak_windows_s`, and the lookup silently defaults to 0.0 on a miss

**File:** `src/telemetry/measure/report.py:382-384`
**Issue:** `_threshold_comparison` does
`gating["peaks"]["windows"].get(peak_label, {"peak_bits_per_s": 0.0})`. If
`thresholds.peak_window_s` (from `gate.json`) is not also a member of
`peak_windows_s` (a separate list in the same file, and independently
overridable — `peak_windows_s` has no relationship enforced with
`thresholds.peak_window_s` anywhere in `config.py`), the peak criterion
silently reports `measured=0.0 kbit/s`, `within_threshold=True` — a gate
that should be evaluated on the real peak rate instead reports the peak
criterion as trivially passing. This is exactly the kind of silently-wrong
number GATE-01/D-16 (per this same module's docstring) is designed to
prevent everywhere else in the report. Currently harmless only because the
checked-in `gate.json`'s `peak_windows_s` happens to include `1.0` (the
value of `thresholds.peak_window_s`).
**Fix:** Either validate in `config.py` that `thresholds.peak_window_s` is
a member of `peak_windows_s` (`_parse_thresholds` already has access to
enough context to be extended, or do it as a whole-document post-check in
`load_gate_config`), or raise instead of defaulting in
`_threshold_comparison` when the window is missing:
```python
peak_window = gating["peaks"]["windows"].get(peak_label)
if peak_window is None:
    raise KeyError(
        f"thresholds.peak_window_s={thresholds.peak_window_s} produced "
        f"label {peak_label!r}, which is not in peak_windows_s={sorted(gating['peaks']['windows'])}"
    )
```

### WR-04: `peak_windows`' whole-run-average fallback is not actually independent of the requested window length

**File:** `src/telemetry/measure/report.py:225-274`, specifically the
`run_duration_us <= 0` branch at lines 256-259
**Issue:** When a batch timeline spans zero elapsed time (e.g. a single
batch — easily reached via `--only-message` combined with a short
`--duration-s`, both of which `cli.py` exposes), `peak_windows` falls back
to `avg = total_bits / window_s` for every requested window (since
`run_duration_s` is also `0`). Every one of these values is labelled
`is_whole_run_average: True` and presented as *the* whole-run average bit
rate, but the number returned actually varies with the requested window
length (`total_bits / 0.1` vs. `total_bits / 10.0` differ by 100x for the
same run) — a single run produces a different "whole run average" per
`peak_windows_s` entry, which is internally inconsistent for a quantity
whose name implies it should be one number.
**Fix:** When `run_duration_us <= 0`, compute one whole-run average
(e.g. treat the single batch as spanning some minimum nominal duration, or
simply return `total_bits` alone with an explicit "undefined duration"
flag) rather than dividing by whatever `window_s` happens to be requested,
so the same run never reports two different "average" figures depending on
`peak_windows_s`.

### WR-05: `--duration-s` CLI override bypasses `config.py`'s positive-duration validation

**File:** `src/telemetry/measure/cli.py:98-103, 162-163`
**Issue:** `load_gate_config` enforces `duration_s > 0` for the checked-in
config (`config.py:291`, `_require_positive_number`). `cli.py`'s
`--duration-s` flag (`type=float`, no `choices`/validation) bypasses that
check entirely — `--duration-s 0` or a negative value silently produces an
empty-frame run (`SyntheticFrameSource`'s `while t < duration_us:` loop at
`generator.py:89` never executes) and a report full of zeros
(`bitrate_summary` explicitly returns `0.0` for `duration_s <= 0` rather
than raising), instead of the loud, named failure every other malformed
input in this phase produces.
**Fix:** Validate `args.duration_s > 0` immediately after parsing and
`raise SystemExit(1)` with a clear message, mirroring the
`DbcLoadError`/`GateConfigError` handling already present a few lines
above for `--dbc`/`--gate-config`.

## Info

### IN-01: `all_in_bytes_per_batch` and `overhead_breakdown` independently reimplement the same formula

**File:** `src/telemetry/wire/overhead.py:39-50` vs. `:70-102`
**Issue:** Both functions compute `BATCH_HEADER_BYTES + framed +
cobs_worst_case_overhead(framed)` from scratch. A test
(`test_overhead_breakdown_all_in_bytes_matches_batch_formula`) currently
pins them together, but nothing in the source itself prevents the two from
drifting if one is edited and the other isn't.
**Fix:** Have `overhead_breakdown` call `all_in_bytes_per_batch(clean_payload_bytes)`
instead of recomputing `all_in_bytes` inline.

### IN-02: `IdDictionary.dbc_path` is typed as non-Optional `Path` but is routinely `None`

**File:** `src/telemetry/wire/dictionary.py:66, 113`
**Issue:** The dataclass field is annotated `dbc_path: Path` (line 66), but
`build_id_dictionary` sets it to `None` whenever `dbc_path` isn't supplied
(line 113: `Path(dbc_path) if dbc_path is not None else None`). Every
current caller happens to supply a path, so this doesn't crash today, but
the type hint promises a guarantee the code doesn't provide, and
`index_of`/`key_of`'s error messages (`f"...built from {self.dbc_path!s}"`)
would print `"None"` rather than failing loudly if a future caller omits
it.
**Fix:** Annotate as `Optional[Path]`.

### IN-03: The CFR sequence byte is parsed but never used or validated by the decoder

**File:** `src/telemetry/wire/decoder.py:65`
**Issue:** `seq = fields.pop(0) if self.options.sequence_byte else None` is
read off the wire and then never referenced again in `decode()` — there is
no continuity/gap check anywhere in this codebase today, even though the
encoder's docstring describes the byte's purpose as "per-CAN-ID sequence"
(implying gap detection is part of its intended job). Not a correctness
bug for Phase 0 (nothing here claims to detect drops), but worth flagging
now since Phase 4 is named as the owner of hardening this module, and a
future implementer of gap detection should know this capability doesn't
exist yet, not assume it's silently broken.
**Fix:** No action needed for Phase 0; note for Phase 4 hardening.

---

_Reviewed: 2026-08-01T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
