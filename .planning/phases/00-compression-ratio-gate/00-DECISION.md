# Phase 0 Go/No-Go Decision: Compression Ratio Gate

**Date:** 2026-08-01
**Decided at:** the `00-07-PLAN.md` checkpoint (`type="checkpoint:decision"`, gate `blocking`)

This document is hand-written prose that cites `00-REPORT.json` and `00-THRESHOLD.md` — it is not
a rendering of either. Every numeric figure below names the file and path it was quoted from.

---

## Verdict

**No-go.** As of 2026-08-01, full-bus streaming over the radio link is **not** viable at the
committed configuration; the live path carries a named critical-channel subset instead
(`option-no-go` selected at the `00-07-PLAN.md` checkpoint).

---

## The bar it was judged against

Quoted verbatim from `00-THRESHOLD.md`, pre-registered 2026-07-31 (commit `6acbbd5`,
`docs(00-04): pre-register the pass threshold (D-13)`) — before any full-bus measurement existed:

- `thresholds.baseline_budget_kbps` = **200 kbit/s**
- `thresholds.max_average_kbps` = **120 kbit/s** (`thresholds.required_average_headroom_pct` = 40)
- `thresholds.max_peak_kbps` = **170 kbit/s** at `thresholds.peak_window_s` = **1.0 s**
  (`thresholds.required_peak_headroom_pct` = 15)
- `thresholds.gating_bracket` = **typical**

`git log --oneline --diff-filter=A -- .planning/phases/00-compression-ratio-gate/00-THRESHOLD.md .planning/phases/00-compression-ratio-gate/00-REPORT.json`
shows `00-THRESHOLD.md` added in `6acbbd5` and `00-REPORT.json` added later in `051694b` — the bar
demonstrably predates the numbers. Per `00-THRESHOLD.md`'s Amendment rule, this bar was **not**
revised to accommodate the result below.

---

## The measured result

Per D-14, the **typical** bracket gates this verdict; the worst-case bracket (next section)
informs it and does not gate.

- **Average:** `brackets.typical.aggregate.kbps_all_in` in `00-REPORT.json` = **305.13072 kbit/s**
  (rounds to **305.1 kbit/s**). Against the 120 kbit/s ceiling, `meta.threshold_comparison[0]`
  records `headroom_pct: -154.2756` — a **-154.3%** headroom, i.e. the average is 2.54x the ceiling.
- **1-second peak:** `brackets.typical.peaks.windows["1s"].peak_bits_per_s` in `00-REPORT.json` =
  313552.0 bits/s = **313.552 kbit/s**, identical to `meta.threshold_comparison[1].measured`.
  Against the 170 kbit/s ceiling, `meta.threshold_comparison[1].headroom_pct` = **-84.44235...%**
  (**-84.4%**) — the 1-second peak is 1.84x the ceiling.
- Both entries in `meta.threshold_comparison` in `00-REPORT.json` carry `within_threshold: false`.

Both criteria in the pre-registered "pass requires BOTH" bar fail. This is not a marginal result —
`00-THRESHOLD.md`'s own pre-registered known risk anticipated it: the CFR header is a fixed
6 bytes/frame paid on every frame, and at the assumed combined bus rate that alone is close to the
120 kbit/s ceiling before any payload byte is counted.

---

## The worst-case bracket

`brackets.worst.aggregate.kbps_all_in` in `00-REPORT.json` = **344.51352 kbit/s** all-in average.
Against `thresholds.baseline_budget_kbps` = 200 kbit/s (the RFD900x's own usable ceiling, not just
the pass bar), the worst bracket exceeds it by **+72.3%** — it does not fit even the optimistic
radio budget, let alone the conservative pass bar.

Per D-14, a worst-bracket exceedance does not by itself fail the gate — the typical bracket already
failed on its own, so this is confirmatory rather than the deciding factor. It is still carried
forward as a **documented condition for Phase 1**: **re-run this gate against real captured bus
traffic at Phase 1's first bench or track session**, using the deferred real-log reader for the
D-08 frame-source interface (the pluggable frame source built in Phase 0 but deliberately left
without a real-log implementation, per `00-CONTEXT.md`'s Deferred Ideas). Given the typical bracket
already misses the pass bar by 2.5x, this re-check is unlikely to reverse the no-go, but it is the
mechanism by which a materially different real-traffic entropy profile would be caught.

---

## Worst-case IDs

Four categorical buckets, typical bracket, from `brackets.typical.categories` in `00-REPORT.json`,
each against the typical bracket's aggregate (`brackets.typical.aggregate.clean_bytes_per_frame` =
10.030102477088075, `all_in_bytes_per_frame` = 10.22394312963901):

| Category | Messages | Clean B/frame | All-in B/frame | vs. aggregate (all-in) |
|---|---|---|---|---|
| `rolling_counter` | 46 | 11.237821738081541 | 11.455237450877577 | +12.0% |
| `checksum` | 12 | 11.880142248759714 | 12.110387527910145 | +18.4% |
| `multiplexed` | 3 | 13.409718585485516 | 13.668192483963859 | +33.7% |
| `high_entropy_analog` | 58 | 10.375491893593578 | 10.575895805071573 | +3.4% |
| `other` | 59 | 8.922309043552001 | 9.094765055560007 | -11.0% |

(Message counts sum above 128 because a message can belong to more than one category — see D-04.)

The `multiplexed` bucket costs **+33.7%** over the aggregate despite having only 3 members — this
is the mux-transition cost `RESEARCH.md` Pitfall 1 exists to make visible: switching multiplexors
defeats payload-delta compression on every transition, and this DBC's multiplexed messages pay
that cost disproportionately to their count.

Worst 10 individual IDs, typical bracket, from `brackets.typical.worst_n` in `00-REPORT.json`
(`worst_n: 10` per `meta.worst_n`):

| Frame ID | Message | Categories | Rate (Hz) | All-in B/frame |
|---|---|---|---|---|
| 0xA4 | M164_Digital_Input_Status | rolling_counter | 100.0 | 14.269759540516516 |
| 0xAA | M170_Internal_States | other, rolling_counter | 10.0 | 14.269443916905185 |
| 0x100 | Overall_Parameters_Std | checksum, other, rolling_counter | 12.98 | 14.270863565877155 |
| 0x105 | State_Of_Charge_Param_Std | checksum, high_entropy_analog, rolling_counter | 12.98 | 14.271013886744772 |
| 0x107 | Diagnostic_Codes_Std | other, rolling_counter | 12.98 | 14.271067592135793 |
| 0x238 | Login_Set_Password_Std | checksum, rolling_counter | 25.47 | 14.271580032554635 |
| 0x249 | HTL_CH_ID_WARNING_0 | checksum, rolling_counter | 25.47 | 14.271561053679466 |
| 0x250 | HTL_CH_ID_WARNING_1 | checksum, rolling_counter | 25.47 | 14.271543404832357 |
| 0x19B50000 | Overall_Parameters_Ext | checksum, other, rolling_counter | 12.98 | 14.271882898487107 |
| 0x19B50007 | Diagnostic_Codes_Ext | other, rolling_counter | 12.98 | 14.271870876912454 |

All 10 sit at almost exactly the same 14.27 bytes/frame ceiling, driven by DBC-declared message
length rather than by rate — these are 8-byte messages classified `rolling_counter` and/or
`checksum`, whose structural detection makes the payload-delta mechanism least effective per
`brackets.typical.categories.rolling_counter.note` / `.checksum.note`.

---

## What the ablations say

From `brackets.typical.ablations` in `00-REPORT.json`, each `delta_pct_vs_full` against the full
encoding's clean bytes/frame (10.030102477088075):

- **Per-ID sequence byte** (`no_sequence_byte`): removing it changes cost by **-9.969987866866925%**
  (**-9.97%**) — the sequence byte costs ~10% of the full encoding.
- **Payload delta vs. raw** (`raw_payload`): using raw payload instead of the per-ID delta changes
  cost by **+35.57004345478937%** (**+35.57%**) — the delta mechanism is the largest single
  contributor to the compression this gate measured.
- **ID dictionary** (`no_dictionary`): removing it changes cost by **+29.909963600600776%**
  (**+29.91%**) — the second-largest contributor.

If a real-traffic re-measurement at Phase 1 comes in marginal, the per-ID sequence byte is the
knob that buys the most back for the least cost: it is the only mechanism here whose removal is a
net *savings* (-9.97%) rather than a cost, because unlike the dictionary and the payload delta it
is not load-bearing for the core compression scheme — it exists to detect dropped frames, a
correctness feature this gate did not require. Removing the dictionary or the payload delta buys
back more (29.91% / 35.57%) but gives up the two mechanisms that do almost all of this encoding's
work.

---

## Critical channels

Per D-15, this subset is named regardless of the verdict, and doubles as the degraded-mode list
Phase 5's shaping and any Phase 1 real-bus re-measurement will both need. Confirmed at the
`00-07-PLAN.md` checkpoint as the trimmed 12, all standard-ID, drawn from the report's per-ID table
(`brackets.typical.per_id` / `00-REPORT.csv`, `bracket=typical`):

| ID | Message | Rate (Hz) | All-in B/frame | kbit/s |
|---|---|---|---|---|
| 0xB0 | M176_Fast_Info | 333.33 | 9.680427137954462 | 25.81 |
| 0xC0 | M192_Command_Message | 200.00 | 12.614656044015103 | 20.18 |
| 0xA6 | M166_Current_Info | 100.00 | 10.521563121885116 | 8.42 |
| 0xA7 | M167_Voltage_Info | 100.00 | 10.501983193432764 | 8.40 |
| 0x252 | CAN_WHEEL_SPEED | 25.47 | 10.577725316265385 | 2.16 |
| 0x265 | BRAKE_TEMPS | 25.47 | 10.600051556517899 | 2.16 |
| 0xC3 | M195_Pedal_Press_Percent | 25.47 | 7.138545166306077 | 1.45 |
| 0x101 | Battery_Volt_1_Overall_Param_Std | 12.98 | 13.252335706864612 | 1.38 |
| 0x251 | CAN_VEHICLE_SPEED | 25.47 | 6.496590851230935 | 1.32 |
| 0x217 | HTL_CH_ID_SAFETY_LOOP_STATUS | 25.47 | 6.128395366381156 | 1.25 |
| 0x219 | HTL_CH_ID_BRAKE_PRESSED | 25.47 | 6.1275981483395086 | 1.25 |
| 0xA0 | M160_Temperature_Set_1 | 10.00 | 10.510471235111384 | 0.84 |

**Subset total: 74.62 kbit/s** — 24.5% of the typical bracket's aggregate all-in average
(305.13072 kbit/s, `brackets.typical.aggregate.kbps_all_in`). This fits comfortably under both the
120 kbit/s pass bar and the 200 kbit/s baseline budget, with over 45 kbit/s of margin even against
the tighter bar.

Selection rationale: safety-relevant and driver-facing values — motor fast-info and the VCU command
message (the two highest-rate messages on the bus), BMS current/voltage overview, wheel/vehicle
speed, brake temperatures, pedal position, the safety-loop and brake-pressed status lines, and a
representative battery-temperature reading — rather than diagnostic, configuration, or per-cell
detail messages. This is a proposal drawn from message names and measured cost, confirmed by the
user at the checkpoint; deriving true priority ultimately needs the team's knowledge of what the
pit engineer actually watches, which the checkpoint supplied.

---

## What this decision rests on

A reader who was not in the room needs to be able to see what this verdict is conditional on:

- **The modelled-input limitation (D-01).** Every frame in `00-REPORT.json` is synthesized from
  `epbr2026_DBC_v1.0.dbc` (`meta.input_provenance`), not captured from the car. Payload entropy is
  exactly the quantity this gate exists to measure, and synthetic data has only the entropy the
  three-bracket model in `config/gate.json`'s `entropy_brackets` gives it. This is the largest
  assumption behind every number above.
- **Bus assignment is unconfirmed.** `meta.bus_assignment_confirmed` = **false** in `00-REPORT.json`
  (mirroring `config/gate.json`'s `bus_assignment.confirmed: false`). `epbr2026_DBC_v1.0.dbc` names
  no per-message bus at all; the bus1/bus2 split used throughout this report is a human-authored
  ECU-sender proxy confirmed at the 00-04 checkpoint, not a DBC-derived fact.
- **Total bus frame rate is unconfirmed.** `config/gate.json`'s `bus_targets.confirmed` = **false**:
  only 19 of 128 DBC messages declare `GenMsgCycleTime` (summing to ~1,690.67 fps); the ~3,730-4,000
  fps combined rate this run targets (`meta.bus_targets`, achieving `meta.achieved_bus_fps.bus1` =
  2900.0005, `meta.achieved_bus_fps.bus2` = 830.0050) is prose-sourced, not DBC-derivable.
- **The assumed batch size.** Every all-in figure above assumes `meta.batch_frames` = **100**
  (equal to `config/gate.json`'s `batch_frames`), which sets the D-06 framing-overhead amortization
  (batch header, CRC-16, COBS worst-case expansion). A different Phase 1 batch size is recomputable
  from the report's clean-bytes figures rather than requiring a re-measurement.
- **`config/gate.json` was edited after the threshold was locked.** Commit `7d13a77` raised
  `duration_s` from 5.0 to 100.0 *after* `00-THRESHOLD.md` (`6acbbd5`) had already pre-registered
  the bar. This is defensible — Task 1's own acceptance criterion requires
  `duration_s >= 10 x max(peak_windows_s)` = 100, and the `thresholds` block itself was untouched —
  but it is a post-lock edit to a pre-registered config and is recorded here for anyone auditing the
  phase.
- **The run is not bit-reproducible across that edit.** An earlier scratch run (pre-`7d13a77`, same
  seed) gave 305.55/312.35 kbit/s avg/peak; the published run gives 305.13072/313.552 — a 0.1-0.4%
  gap, most likely attributable to the `duration_s` change altering how many peak windows are
  sampled. The conclusion (both criteria fail, by a wide margin) is unaffected by a gap this small.
- **A modelling error was found and corrected in the record, not in the config.** The team runs the
  EMUS BMS in standard-ID mode only; the DBC's 34 `_Ext` messages modelled in this run's 128-message
  set do not exist on the real bus (23 have an identically-named `_Std` twin; 11 have a
  differently-named one, e.g. `Individual_Cells_Volt_Ext_A1` duplicating
  `Individual_Cells_Voltages_Std_A1`). Removing all 34 takes the typical bracket's all-in average
  from the published **305.13072 kbit/s down to an arithmetic estimate of ~261.85 kbit/s**
  (128 -> 94 messages) — a **sum computed by hand over the published per-ID table in `00-REPORT.csv`,
  not a fresh measurement run.** `config/gate.json` was deliberately **not** edited and the gate was
  **not** re-run for this correction, per the checkpoint resolution. The verdict is unchanged either
  way: even at ~261.85 kbit/s the typical bracket still exceeds the 120 kbit/s bar by more than 2x,
  because the fixed 6-byte/frame CFR header — paid every frame regardless of payload — is the
  binding constraint, not BMS message duplication. Phase 1's real-traffic capture is what will
  settle the true message set.

---

## What later phases should build against

The live path carries the 12-message critical-channel subset named above, not the full bus; the
full-rate archive on the onboard NVMe is untouched by this verdict and remains complete regardless
— the core value that no run's data is ever lost survives the no-go intact. Subset *membership*
must be a **data-driven allowlist Phase 1 reads at startup**, not a set baked into code: the user
confirmed at the checkpoint that changing which messages are streamed live is meant to be a config
edit plus a restart of both the car and pit-laptop ends, not a code change or redeploy. Phase 4's
dictionary-version negotiation is what makes a mid-season swap of that allowlist safe when the car
and the pit laptop briefly disagree about it. Two things in this decision are *not* cheap to
reverse: the verdict itself (D-14 — every later phase's link scope is built against it, and
reversing it after Phase 1 lands means redesigning what the live path carries) and the encoded byte
layout (D-05 — Phase 1 and Phase 4 both import the encoder core, so changing it after Phase 1 lands
means touching the encoder, the decoder, and every recorded measurement).
