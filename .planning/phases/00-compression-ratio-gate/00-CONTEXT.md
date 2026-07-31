# Phase 0: Compression Ratio Gate - Context

**Gathered:** 2026-07-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 0 delivers **a measurement and a written decision** — nothing that runs on the car.

It builds the byte-producing core of the planned wire encoding (delta timestamps, DBC-derived arbitration-ID dictionary, per-ID payload delta, per-ID sequence byte), runs it over a modelled full-bus CAN stream, and reports real bytes/frame — aggregate, per CAN ID, and with worst-case IDs broken out. It converts that to average and peak bit rate for the combined ~4,000 frames/s bus and compares it against the ~200–250 kbit/s usable radio budget. It closes with a documented go/no-go on full-bus streaming plus a named critical-channel subset.

**In scope:** encoder core + matching decoder, synthetic frame-source generator, measurement/reporting tool, the report artifact, the go/no-go decision document.

**Out of scope (belongs to later phases):** COBS/CRC framing and batching implementation (Phase 1), transport/link abstraction (Phase 1), keyframes and dictionary-version negotiation (Phase 4), leaky-bucket shaping (Phase 5), any capture from real hardware, any change to the existing loggers or dashboard.

</domain>

<decisions>
## Implementation Decisions

### Measurement Input

- **D-01:** The measured stream is **synthesized from `epbr2026_DBC_v1.0.dbc`**, not captured from the car and not sourced from an existing team log. No capture exists anywhere in the repository, and the existing loggers emit either `.vsb` (`src/neoVI_logger.py:14`) or decoded-signal CSV (`src/new_logger.py`) — decoded CSV lacks the raw `(timestamp, arb_id, dlc, payload bytes)` this measurement needs.
  - **Known limitation, accepted by the user:** payload entropy is the exact quantity the gate exists to measure, and synthetic data has only the entropy the model gives it. D-02 and D-14 are the compensating controls. — **Reversibility:** reversible — D-08's pluggable frame source means re-running against a real capture is a new reader plus a config change.

- **D-02:** Entropy is modelled as **three brackets — best / typical / worst — and reported as a band, not a point.** Worst = analog LSBs dither every frame; typical = a few low bits move; best = mostly quiescent. A single synthetic number would be false precision.

- **D-03:** Frame rates come from **`GenMsgCycleTime` where declared (~21 of 128 messages), with the remaining ~107 assigned plausible rates scaled so per-bus totals match the documented real bus loads** — bus 1 ~70% / ~2,900 fps, bus 2 ~20% / ~830 fps (`telemetry_conversation.md`). Those loads are actually measured, so they anchor the synthetic stream to something real.

- **D-04:** Worst-case IDs (GATE-02) are selected **by category AND by rank**: every message is classified into rolling counter / checksum / multiplexed / high-entropy analog with each bucket aggregated separately, *plus* the worst N individual IDs by measured bytes/frame listed regardless of bucket. Name-based detection alone is insufficient — only two rolling counters are findable by name (`VCU_INV_RollingCounter`, `INV_Rolling_Counter`) against ~52 multiplex indicators.

### Encoder Scope

- **D-05:** Phase 0 builds the **real reusable encoder core, not a throwaway script** — but **only the byte-producing core**. In scope: delta timestamp, ID dictionary, per-ID payload delta, per-ID sequence byte. Not in scope: COBS/CRC framing, batching, transport. Phase 1 imports this module; Phase 4 hardens it. The gate's number is therefore the number that ships, without committing the transport stack before the gate rules on it. — **Reversibility:** costly — Phase 1 and Phase 4 both import this module, so changing the encoded byte layout after Phase 1 lands means touching the encoder, the decoder, and every recorded measurement.

- **D-06:** Framing overhead is handled as an **analytic line item on top of the payload measurement**, not by implementing framing. Report clean payload bytes/frame separately, then add an itemised computed overhead figure — COBS worst-case expansion (~1 byte per 254), CRC-16 (2 bytes/batch), batch header — at a stated batch size. The comparison against the radio budget uses the **all-in** number; the clean payload number is what per-ID analysis uses.

- **D-07:** The encoder core lives in a **new package that starts the target rebuild layout** (e.g. `src/telemetry/wire/`), not as a flat script beside the existing loggers and not in a separate `tools/` tree. PROJECT.md commits to a whole-stack rebuild; this is its first brick, and putting it in `tools/` would force Phase 1 to import from an analysis directory or copy the module — undercutting D-05's "same code, same number" guarantee. — **Reversibility:** costly — this sets the package layout Phase 1 and Phase 2 build into.

- **D-08:** The tool reads frames through a **pluggable frame-source interface**. The synthetic generator is one implementation; a real-log reader can be added later without reworking the measurement tool. **Do not write the real-log reader now** — there is no file to test it against.

- **D-09:** Phase 0 **also builds the matching decoder and asserts every synthetic frame round-trips byte-identical.** A byte count for an encoding nobody proved reversible is not a measurement — anything compresses further if it never has to decode. This introduces **pytest into a repository that currently has no tests**; that is accepted here even though formal test requirements (TEST-01…03) live in Phase 5.

### Measurement Matrix

- **D-10:** The headline is the **full planned encoding**, reported alongside **ablations that isolate each mechanism's cost** — with/without the per-ID sequence byte (research estimates ~12–15%), payload delta vs. raw, ID dictionary on/off. If the baseline is a marginal fail, the ablations already say which knob buys the most back, avoiding a second measurement round.
  - Not in scope: a generic second-pass compressor (zstd) over batches. That evaluates a transport-layer choice this gate was not scoped to decide. See Deferred Ideas.

- **D-11:** **Peak = sliding-window max reported at several scales** (e.g. 100 ms, 1 s, 10 s), not a single number and not a theoretical worst-case frame alignment. Short windows expose the bursts a batching + leaky-bucket design must absorb; long windows show what the link must sustain. Reporting the set makes "fits with headroom" checkable rather than definitional.

- **D-12:** Runs are **seeded and deterministic, with every modelling assumption in a checked-in config file** — entropy brackets, per-ID rates, batch size, bus loads. For a gate built on modelled rather than measured data, the assumptions *are* the result; anyone must be able to regenerate the exact report and audit what was assumed without reading source.

### Decision Artifact

- **D-13:** The **pass threshold is pre-registered — written down before the measurement runs.** Form: a stated bit-rate ceiling plus a required headroom percentage against the ~200–250 kbit/s budget. Pre-registering the bar is what prevents a marginal result being rationalised into a go, and makes the decision reviewable by someone who was not in the room.
  - **Open item for planning:** the specific numeric threshold and headroom percentage were deliberately left unset. The planner proposes a concrete number (against the ~200–250 kbit/s budget and the ~40% headroom claim in PROJECT.md) for the user to confirm **before** the measurement runs — not after.

- **D-14:** **The typical bracket gates the verdict; the worst-case bracket informs it.** A go requires the typical bracket to fit with headroom. Worst case does not gate — it assumes every analog LSB dithers every frame, which under synthetic data is our own pessimism rather than a measured fact — but it is reported, and if it fails it becomes a **documented condition to re-check against real traffic in Phase 1**. — **Reversibility:** one-way — every later phase's link scope is built against this verdict; reversing it after Phase 1 means redesigning what the live path carries.

- **D-15:** The **critical-channel subset is named regardless of outcome**, not only on a no-go. It costs little once per-ID numbers exist, and it doubles as the degraded-mode list that Phase 5's shaping and any marginal real-bus result will both need. Deriving the priority ranking requires knowing which signals the pit engineer actually watches.

- **D-16:** Two artifacts, not one: a **tool-generated report** (numbers, per-ID tables, brackets, ablations, plus machine-readable JSON/CSV) and a **short hand-written go/no-go decision** that cites it. Numbers stay reproducible; the judgement — why this bar, what the worst-case bracket implies for Phase 1 — stays human and quotable. SC-4 wants a decision every later phase is built against; that is a document, not a tool output.

- **D-17:** Both artifacts live in **`.planning/phases/00-compression-ratio-gate/`**, with the verdict recorded as a row in **PROJECT.md's Key Decisions table** — which already carries a `— Pending` entry for exactly this gate — pointing at them.

### Claude's Discretion

The user made an explicit selection on every question; no area was delegated wholesale. Discretion remains on:

- Concrete signal-classification heuristics for D-04 (multiplexors are structural; counters/checksums inferable from bit width, position, and naming; analog entropy from scaling, range, and bit width).
- The value of N in "worst N individual IDs".
- Exact module and file names inside the D-07 package layout, and how far the layout is sketched now vs. left for Phase 1.
- Report rendering — how three entropy brackets × the ablation set × several peak windows are presented without a combinatorial explosion.
- The proposed numeric threshold in D-13 (proposed by the planner, **confirmed by the user before running**).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements
- `.planning/ROADMAP.md` § "Phase 0: Compression Ratio Gate" — goal, the four success criteria, and the "Why Phase 0 exists separately" structural note
- `.planning/REQUIREMENTS.md` — GATE-01 (bytes/frame overall and per CAN ID against a real log), GATE-02 (worst-case IDs reported separately), GATE-03 (documented go/no-go)

### Bandwidth premise and encoding design
- `telemetry_conversation.md` — the RF and link analysis this gate tests. Load figures used by D-03 (bus 1 ~70%/~2,900 fps, bus 2 ~20%/~830 fps), the ~780 kbit/s naive vs. 130–160 kbit/s compressed estimate, the ~200–250 kbit/s RFD900x usable budget, and line 248's "measure your actual compression ratio" recommendation
- `.planning/PROJECT.md` § Context — the "full bus fits with ~40% headroom" claim and the explicit "Unverified assumption" paragraph; § Key Decisions — the `Compression ratio becomes a go/no-go gate` row that D-17 updates
- `.planning/research/SUMMARY.md` — the compression mechanism (delta timestamps, ID dictionary, per-ID payload delta), the ~12–15% per-ID sequence-number cost feeding D-10's ablations, and why per-frame CRC is rejected in favour of batched COBS+CRC-16 (feeds D-06's overhead model)
- `.planning/research/PITFALLS.md` — pitfall #1 is this phase's entire reason for existing; pitfall #2 (stateful compression + accepted loss = desync trap) constrains what the encoder core must leave room for
- `.planning/research/ARCHITECTURE.md` — the wire-encoder component definition and the four recovery mechanisms; informs the D-07 package layout

### Signal source
- `epbr2026_DBC_v1.0.dbc` — 128 messages, ~52 multiplex indicators, `GenMsgCycleTime` on ~21 messages. The sole input to the D-01 synthetic generator and the D-04 classification
- `ECU database breakdown/` — per-ECU DBC splits (ACU, BMS, ENERGY_METER, IMU, MCU, SCU, U2C, VCU). Useful for D-15's critical-channel ranking, since ECU ownership maps roughly onto what the pit watches

### Conventions
- `.claude/CLAUDE.md` — Python `snake_case`, module-level docstrings on entry points, `log()`/`debug()` to stderr with stdout reserved for data
- `.planning/codebase/CONCERNS.md` — the carried-in debt (no dependency manifests, no tests anywhere, silent decode-exception swallowing) that D-09 partially starts paying down

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`epbr2026_DBC_v1.0.dbc` + cantools** — already the established decode path across all three loggers. Phase 0 uses cantools to *read structure* (message IDs, bit layouts, multiplexors, cycle-time attributes, scaling) for both the synthetic generator and the ID dictionary — not to decode, since the whole point of the design is that decode happens on the ground.
- **DBC index pattern** (`src/new_logger.py:135-139`, `294-304`) — the `{frame_id: cantools.Message}` dictionary lookup is the same shape the arbitration-ID dictionary needs.
- **Raw tuple frame representation** (`src/new_logger.py:202-208`) — `(timestamp, arb_id, network_id, dlc, data_bytes)` is already the codebase's internal frame shape and is a natural fit for the D-08 frame-source interface.

### Established Patterns

- **Python-only, stdlib-heavy** — argparse CLIs, `Path(__file__).parent` for path construction, `if __name__ == "__main__":` entry points. The measurement tool should look like the rest of `src/`.
- **stdout is for data, stderr is for logs** — `log()`/`debug()` write to stderr precisely so stdout stays clean. The measurement tool's machine-readable output should respect this.
- **No dependency manifest exists** — neither `requirements.txt` nor `package.json`. Phase 1 owns provisioning (ARCH/OPS requirements), but Phase 0 adds pytest and so is the first phase to need one. Flag rather than silently `pip install`.

### Integration Points

- **Nothing in Phase 0 wires into the running system.** The encoder core is a library with no callers until Phase 1's capture fan-out imports it. This is the phase's chief safety property — it can be wrong without breaking anything currently working.
- **`src/` currently holds four flat scripts** (`neoVI_logger.py`, `new_logger.py`, `neoVI_sender.py`, `references.py`). D-07 introduces the first package alongside them; the existing scripts are untouched, and duplicate-logger consolidation is Phase 1's job.
- **PROJECT.md Key Decisions table** is the integration point for the verdict itself (D-17) — the row exists and is marked `— Pending`.

</code_context>

<specifics>
## Specific Ideas

- The user explicitly wanted the gate to run **with no hardware and no waiting on a track session** — that is what drove D-01 to synthetic input over capturing a real log first. Speed to a decision was valued over input fidelity, with D-02's bracketing accepted as the way to stay honest about the tradeoff.
- Repeated preference for **honest ranges over confident single numbers**: brackets rather than a point (D-02), a set of peak windows rather than one peak (D-11), ablations alongside the headline (D-10).
- Strong preference for **auditability over convenience**: assumptions in a checked-in config rather than in source (D-12), threshold pre-registered rather than judged after (D-13), a hand-written decision that cites a generated report rather than one auto-rendered document (D-16).
- The user consistently chose the option that **leaves the next phase better set up** — reusable encoder core over a throwaway script (D-05), new package layout over a flat file to be moved later (D-07), pluggable frame source over a synthetic-only tool (D-08), subset named regardless of verdict (D-15).

</specifics>

<deferred>
## Deferred Ideas

- **zstd (or any generic compressor) as a second pass over batches** — raised in `telemetry_conversation.md:248` and considered as a matrix variant (D-10). Deferred: it evaluates a transport-layer choice, and the right time to test it is when batching actually exists. Belongs with Phase 1's batching work, or as a rescue option if a real-traffic re-measurement comes in marginal.
- **Batch size as a swept parameter** — considered for D-06; deferred because batch size trades framing overhead against latency, which is Phase 1/Phase 5 territory. Phase 0 states a single batch size as an assumption in the D-12 config instead.
- **Writing the real-log reader (`.vsb` / `.blf` / `.asc`)** — the D-08 interface is built now, the reader is not. Do it when a real capture exists to test against, most naturally alongside Phase 1's capture work.
- **CPU cost per frame for the encoder** — offered and not selected. Genuinely needed, but `.planning/research/SUMMARY.md` already assigns "per-frame encoder CPU cost measured on real hardware" to Phase 1's exit criteria, where it can be measured on the actual CM4 rather than a laptop.
- **Capturing a real log to re-run this gate against** — not scope creep so much as the deliberate follow-up to D-01. The natural trigger is the first track or bench session in Phase 1; D-14's worst-case-bracket condition is what would make it urgent.

</deferred>

---

*Phase: 0-Compression Ratio Gate*
*Context gathered: 2026-07-30*
