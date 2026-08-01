# Phase 0 Pre-Registered Pass Threshold

**Pre-registered:** 2026-07-31, before any measurement has been run.

**Status at the time of writing:** No full-bus measurement exists. The only report artifact on disk (`00-REPORT.json`) is plan 00-02's tracer output for a single CAN ID (`M192_Command_Message`, 8.129 bytes/frame) -- it carries no `thresholds` comparison block and is not the aggregate go/no-go report plan 00-06/00-07 will produce. This document is committed before that aggregate report exists, per D-13 and the amendment rule below.

This document exists so that a marginal result cannot be rationalised into a go after it is on the screen (D-13). Everything below is written down now, while no number exists yet.

---

## Pre-registered pass condition

Selected at the 00-04 checkpoint: **option-a, conservative floor, 40% headroom.**

- **Baseline radio budget:** `thresholds.baseline_budget_kbps` = **200 kbit/s** -- the conservative end of the documented 200-250 kbit/s usable RFD900x range (`telemetry_conversation.md`, PROJECT.md § Constraints).
- **Pass requires BOTH:**
  - `thresholds.max_average_kbps` = **120 kbit/s** -- the typical-bracket all-in average bit rate must be at or below this (`thresholds.required_average_headroom_pct` = **40**, matching PROJECT.md's own "~40% headroom" claim).
  - `thresholds.max_peak_kbps` = **170 kbit/s** -- the sliding-window peak bit rate must be at or below this at the `thresholds.peak_window_s` = **1.0** second scale (`thresholds.required_peak_headroom_pct` = **15**).

These five values are quoted verbatim from `config/gate.json`'s `thresholds` block; if the two documents ever disagree, `config/gate.json` is the bug (see Amendment rule).

**Rationale (recorded, not re-litigated at result time):** the RFD900x is unpurchased and unmeasured, so staking the link scope on best-case throughput that cannot be verified is the larger risk. A go under this bar survives the radio landing at the pessimistic end of its documented range.

---

## Which bracket decides

Per D-14: `thresholds.gating_bracket` = **typical**.

- A go requires the **typical** entropy bracket to fit within both caps above. This is the bracket that gates the verdict.
- The **worst** bracket is measured and reported alongside it, but it does **not** gate. It assumes every analog low bit dithers every frame, which under synthetic data is our own pessimism rather than a measured fact.
- If the worst-case bracket fails while typical passes, that failure becomes a **documented condition to re-check against real captured traffic in Phase 1** (D-14), not a reason to fail the gate now.
- The **best** bracket is reported for context only; it neither gates nor triggers a re-check condition.

---

## What "all-in" means

Two distinct numbers appear throughout this phase's reports, and they must never be confused:

- **Clean payload bytes/frame** -- the CFR encoder's output only (delta timestamps, ID dictionary, per-ID payload delta, per-ID sequence byte). This is what per-ID and per-category analysis uses.
- **All-in bytes/frame** -- clean payload **plus** the D-06 analytic framing overhead (batch header, CRC-16, COBS worst-case expansion) at the batch size stated in `config/gate.json` (`batch_frames` = 100). This is the number compared against the radio budget above.

The threshold comparison in this document, and in every report derived from it, uses the **all-in** figure. A clean-payload number alone is never compared against `max_average_kbps` or `max_peak_kbps`.

---

## What this threshold is not

This is a bar against a **modelled stream synthesized from `epbr2026_DBC_v1.0.dbc`** (D-01), not against a captured vehicle log. Known limitation, accepted by the user: payload entropy is exactly the quantity this gate exists to measure, and synthetic data has only the entropy the model gives it.

The compensating controls are:

- **D-02's three-bracket band** (best/typical/worst) -- reporting a range rather than a single confident number, so the result cannot borrow false precision from an assumption.
- **D-14's worst-case re-check condition** -- a worst-bracket failure is carried forward as an explicit open item for Phase 1 rather than silently absorbed or silently ignored.

**Pre-registered known risk (structural, known before any measurement, NOT a reason to move the bar later):** the CFR header is a fixed **6 bytes/frame**, paid on every frame regardless of payload compressibility. At the prose-cited combined rate of ~3,730-4,000 frames/s (`telemetry_conversation.md` / CLAUDE.md), header overhead alone is **~179-192 kbit/s** -- already exceeding the 120 kbit/s pass bar before a single payload byte is counted. At the DBC-derivable floor of ~1,691 frames/s (the sum of the 19 messages that actually declare `GenMsgCycleTime` in `epbr2026_DBC_v1.0.dbc`), header overhead is **~81 kbit/s** and fits comfortably. **The gate may therefore fail on header overhead alone, and that outcome is information about the encoding and the rate assumption -- the threshold above must NOT be revised to accommodate it.**

---

## Amendment rule

This document is committed in its own commit, before the measurement runs and before any full aggregate report artifact (`00-REPORT.json` carrying a `thresholds` comparison block) exists.

Any later change to the numbers above is a **new, dated entry appended below this line**, stating explicitly what it supersedes and why. It is never an in-place edit of the numbers already written above.

*(No amendments yet.)*

---

## Assumptions this threshold rides on

Every number above is only as good as the modelling assumptions in `config/gate.json`. None of the following are measured facts, and none should be read as such in any report this gate produces:

1. **Bus assignment is a human-authored proxy, `bus_assignment.confirmed: false`.** `epbr2026_DBC_v1.0.dbc` has one `BU_:` node line and no per-message bus attribute at all -- nothing in this repository states which of the 128 messages rides bus1 versus bus2. The ECU-sender mapping in `config/gate.json` (`bus_assignment.by_ecu`) is a placeholder confirmed at the 00-04 checkpoint, not a DBC-derived finding.
2. **Default periods for messages with no declared cycle time are assigned, not measured.** `default_period_ms_by_ecu.confirmed: false`. Only 19 of the DBC's 128 messages declare a `GenMsgCycleTime`; the remaining 109 messages' periods are seeded uniformly (100 ms) and scaled at runtime by plan 00-05's rate model to hit `bus_targets`.
3. **The entropy bracket definitions (best/typical/worst) are a model of payload behaviour, not an observation of it.** This is the exact quantity the gate exists to measure and the exact quantity synthetic input cannot supply on its own -- see "What this threshold is not" above.
4. **Total bus frame rate is an explicitly recorded, unconfirmed assumption (`bus_targets.confirmed: false`), added at the 00-04 checkpoint because it dominates the verdict more than any of the other three and is not derivable from this DBC.** Measured basis, reproducible against `epbr2026_DBC_v1.0.dbc` via `cantools`:
   - 128 total messages; only **19** declare a `cycle_time`. Those 19 alone sum to **~1,690.67 frames/s**.
   - **109** messages declare no cycle time at all -- their contribution is assumed (`default_period_ms_by_ecu`), not known.
   - `telemetry_conversation.md` / CLAUDE.md cite ~2,900 frames/s (bus1) + ~830 frames/s (bus2) ≈ **3,730-4,000 frames/s** combined (`bus_targets.bus1.target_fps` = 2900, `bus_targets.bus2.target_fps` = 830). That figure is prose-sourced and cannot be derived from this DBC.
   - The true combined rate could therefore land anywhere between the DBC-derivable ~1,691 fps floor and the prose-cited ~3,730-4,000 fps figure -- see the header-overhead risk above for why this range alone can decide the verdict.
