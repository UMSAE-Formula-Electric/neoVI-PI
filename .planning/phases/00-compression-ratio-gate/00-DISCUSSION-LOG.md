# Phase 0: Compression Ratio Gate - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-30
**Phase:** 0-Compression Ratio Gate
**Areas discussed:** Log source & fidelity, Encoder scope, Measurement matrix, Decision artifact

---

## Log source & fidelity

### Q1: There's no captured CAN log in the repo. What does Phase 0 actually measure against?

| Option | Description | Selected |
|--------|-------------|----------|
| Capture a fresh raw log | Run the car or a bench session and capture raw frames first. Most trustworthy — real dither on real analog channels is what the gate exists to catch. Cost: depends on car + neoVI availability. | |
| Use a log the team already has | An existing `.vsb`/`.blf`/`.asc` capture from a prior session, outside the repo. Fastest path to a real number; needs path, format, and confirmation it holds raw payload bytes. | |
| Synthesize from the DBC | Generate traffic from `epbr2026_DBC_v1.0.dbc` with modelled signal behaviour. Zero hardware dependency. But entropy is the whole question, and synthetic entropy is whatever we assume. | ✓ |
| Real log now, synthetic as harness | Build the tool against synthetic so it's testable without hardware, but let only a real capture produce the binding number. | |

**User's choice:** Synthesize from the DBC
**Notes:** Claude flagged once that entropy in the low bits of analog channels is precisely what the gate exists to measure, and synthetic data only carries the entropy the model gives it — making the *next* question (entropy modelling) load-bearing. User proceeded with synthetic; bracketing (Q2) was accepted as the compensating control. Scout finding that drove this question: no capture exists anywhere in the repo, and `src/new_logger.py` emits decoded-signal CSV rather than the raw `(timestamp, arb_id, dlc, payload)` this measurement needs.

---

### Q2: With synthetic input, how should payload behaviour be modelled so the ratio means something?

| Option | Description | Selected |
|--------|-------------|----------|
| Bracket: best/typical/worst | Three entropy assumptions, report a band not a point. Go/no-go then reads "fits even at worst case" or "fits only at typical" — more honest than one synthetic number. (Recommended) | ✓ |
| Per-signal-class behaviour model | Classify each DBC signal by kind and drive each accordingly. One number, most physically plausible; realism rests on the classification being right. | |
| Adversarial worst case only | Single pessimistic bound. A pass is conclusive; a fail is inconclusive rather than a no-go. | |
| You decide | Claude picks based on what the DBC signal definitions support. | |

**User's choice:** Bracket: best/typical/worst
**Notes:** Worst = analog LSBs dither every frame; typical = a few low bits move; best = mostly quiescent.

---

### Q3: Where does the frame-rate model come from, given only ~21 of 128 messages declare `GenMsgCycleTime`?

| Option | Description | Selected |
|--------|-------------|----------|
| DBC times + fit to bus load | Use declared cycle times; scale the remaining ~107 messages so totals hit the documented real bus loads (bus 1 ~70%/~2,900 fps, bus 2 ~20%/~830 fps). Those loads are measured, so they anchor the synthetic stream. (Recommended) | ✓ |
| Declared cycle times only | Model only the ~21 declared messages and scale up. Cleanest provenance; extrapolates 128 messages of bandwidth from 21. | |
| Flat rate across all IDs | Divide ~4,000 fps evenly. Simplest; flattens per-ID worst cases, which is the opposite of GATE-02. | |
| You decide | Claude chooses from what the DBC and `telemetry_conversation.md` support. | |

**User's choice:** DBC times + fit to bus load
**Notes:** Bus load figures sourced from `telemetry_conversation.md`.

---

### Q4: How do we pick which IDs get their own line in the report (GATE-02)?

| Option | Description | Selected |
|--------|-------------|----------|
| By category + auto-ranked worst N | Classify into GATE-02's four buckets and aggregate each separately, PLUS list the worst N individual IDs by measured bytes/frame regardless of bucket. Satisfies GATE-02 literally and catches surprises no taxonomy predicted. (Recommended) | ✓ |
| Auto-ranked worst N only | Rank all 128 by bytes/frame, top N get rows. Simple, but a reviewer can't confirm "checksums were considered". | |
| Hand-curated list | User names the IDs they're worried about. Highest signal if the bus's problem children are already known; misses what nobody thought of. | |
| You decide | Claude derives classification from DBC structure. | |

**User's choice:** By category + auto-ranked worst N
**Notes:** Question was prompted by the scout finding that only two rolling counters are findable by name (`VCU_INV_RollingCounter`, `INV_Rolling_Counter`) against ~52 multiplex indicators — so name-matching alone cannot satisfy GATE-02.

---

## Encoder scope

### Q1: Throwaway measurement code, or the real wire encoder Phase 1/4 will import?

| Option | Description | Selected |
|--------|-------------|----------|
| Throwaway measurement script | Standalone script that models the encoding well enough to count bytes. Fastest; risk that the production encoder later measures differently. | |
| Real encoder module now | Full production encoder in `src/`, imported by Phase 1/4. Number guaranteed to match what ships; builds the wire format before the gate approves it. | |
| Encoder core now, framing later | Real reusable byte-producing core (delta timestamp, ID dictionary, per-ID payload delta, sequence byte); no COBS/CRC, no batching, no transport. Real number without committing the transport stack. (Recommended) | ✓ |
| You decide | Claude picks based on how much encoder is needed for a defensible byte count. | |

**User's choice:** Encoder core now, framing later

---

### Q2: How is COBS + CRC-16 + batching overhead handled in the reported bit rate?

| Option | Description | Selected |
|--------|-------------|----------|
| Analytic overhead line on top | Clean payload bytes/frame reported separately, plus an itemised analytic overhead figure at a stated batch size; radio comparison uses the all-in number. (Recommended) | ✓ |
| Payload only, overhead noted | Overhead explicitly out of scope with a rough caveat. Simpler; the headline "does it fit" number is optimistic by an unquantified margin. | |
| Batch size as a swept parameter | All-in bit rate as a curve against batch size. More informative; starts making transport decisions the gate wasn't asked to make. | |

**User's choice:** Analytic overhead line on top
**Notes:** Driven by SC-3's requirement that the reported rate be "directly comparable to the ~200–250 kbit/s usable radio budget".

---

### Q3: Where does the reusable encoder core live?

| Option | Description | Selected |
|--------|-------------|----------|
| New package, start the rebuild | Create the target layout now (e.g. `src/telemetry/wire/`) as the first brick of the rebuild Phase 1 continues. Sets structure deliberately rather than inheriting a scratch file's placement. (Recommended) | ✓ |
| Flat in `src/`, matching today | `src/wire_encoder.py` beside the existing scripts. No structural debate now; costs a refactor and moved-file diff later. | |
| Separate `tools/` or analysis dir | Keeps the gate out of the production tree; but Phase 1 then imports from `tools/` or copies the module, undercutting "same code, same number". | |
| You decide | Claude chooses from what `.planning/research/ARCHITECTURE.md` implies. | |

**User's choice:** New package, start the rebuild
**Notes:** Consistent with PROJECT.md's "whole-stack rebuild rather than bolting transport onto the existing code".

---

### Q4: Does Phase 0 also build a matching decoder?

| Option | Description | Selected |
|--------|-------------|----------|
| Decoder + round-trip test | Build the inverse decoder and assert byte-identical round-trip on every synthetic frame. A byte count for an unproven-reversible encoding isn't a measurement. Introduces pytest to a repo with no test setup. (Recommended) | ✓ |
| Encode and count only | Fastest to a number; risk that an encoding omitting something the receiver needs measures small, surfacing only after the go/no-go is acted on. | |
| Round-trip on a sample only | Decoder plus sampled assertions. Middle ground; weaker guarantee on rare-path IDs, which are also the worst-case ones. | |

**User's choice:** Decoder + round-trip test
**Notes:** Accepted that this adds the repo's first tests, ahead of TEST-01…03 which formally live in Phase 5.

---

## Measurement matrix

### Q1: Only the planned encoding, or a sweep of variants?

| Option | Description | Selected |
|--------|-------------|----------|
| Planned encoding + ablations | Headline is the full encoding; ablations isolate each mechanism (sequence byte ~12–15%, payload delta vs raw, dictionary on/off). A marginal fail immediately says which knob buys the most back. (Recommended) | ✓ |
| Planned encoding only | One configuration, one number. Tightest scope; a marginal fail needs another measurement round. | |
| Full sweep incl. zstd second pass | Ablations plus a generic compressor over batches. Broadest information; evaluates transport choices out of scope for the gate. | |
| You decide | Claude picks the variant set. | |

**User's choice:** Planned encoding + ablations
**Notes:** zstd second pass captured as a deferred idea rather than dropped.

---

### Q2: How is "peak" bit rate defined?

| Option | Description | Selected |
|--------|-------------|----------|
| Sliding-window max, several windows | Max sustained rate over ~100 ms / 1 s / 10 s windows, reported as a set. Makes "fits with headroom" checkable rather than definitional. (Recommended) | ✓ |
| Single 1-second window max | One number, matches how the budget is quoted. Hides sub-second bursts, where batching + leaky bucket actually feels pain. | |
| Absolute worst-case frame alignment | Theoretical max from simultaneous cycle deadlines. Upper bound independent of simulated phasing; likely far above anything real, so a fail wouldn't be a genuine no-go. | |

**User's choice:** Sliding-window max, several windows

---

### Q3: How much reproducibility do we build in, given synthetic input?

| Option | Description | Selected |
|--------|-------------|----------|
| Seeded + assumptions in config | Fixed seed and every assumption (brackets, per-ID rates, batch size, bus loads) in a checked-in config. For a gate built on modelled data, the assumptions are the result. (Recommended) | ✓ |
| Seeded run only | Stable numbers, assumptions as constants in the tool. Auditing means reading source. | |
| Report the seed, no config | Self-documenting report header, no separate config. Lightest; changing an assumption means a code edit. | |

**User's choice:** Seeded + assumptions in config

---

### Q4: How hard should re-running the gate against a real capture later be?

| Option | Description | Selected |
|--------|-------------|----------|
| Pluggable frame source | Frame-source interface; synthetic generator is one implementation, a real-log reader another. Re-running later is a config change plus one reader. Synthetic result becomes a baseline to diff against reality. (Recommended) | ✓ |
| Synthetic only, port later | Less code now; re-validating later means reworking the tool exactly when a fast answer is wanted. | |
| Pluggable + write the log reader now | Interface plus a `.vsb`/`.blf`/`.asc` reader with no file to test against. Ready the day real data arrives; writing an untestable parser. | |

**User's choice:** Pluggable frame source
**Notes:** Explicitly does not include writing the real-log reader now.

---

## Decision artifact

### Q1: Is the go/no-go threshold written down before the numbers, or judged after?

| Option | Description | Selected |
|--------|-------------|----------|
| Threshold stated first | Pre-register the bar before running. Stops a marginal result being rationalised into a go, and makes the decision reviewable by someone not in the room. (Recommended) | ✓ |
| Judged after, with rationale | Look at brackets, ablations, outliers, then write the decision. Uses information a fixed threshold can't anticipate; risks the bar moving to wherever the answer landed. | |
| Threshold first, override allowed | Pre-register with a documented override path. Keeps discipline while allowing for a bad model assumption; in practice either unused or used every time. | |

**User's choice:** Threshold stated first
**Notes:** The specific numeric threshold and headroom percentage were deliberately left unset — flagged to the user and carried into CONTEXT.md as an open item for the planner to propose and the user to confirm before the measurement runs.

---

### Q2: Which entropy bracket has to clear the bar for a go?

| Option | Description | Selected |
|--------|-------------|----------|
| Typical passes, worst informs | Go requires typical to fit with headroom; worst case is reported and, if it fails, becomes a documented condition to re-check against real data in Phase 1. Gating on worst case would likely no-go a link that works fine. (Recommended) | ✓ |
| Worst case must fit | Maximum safety; likely forces a critical-channels fallback the real bus may not need, and under synthetic data the worst case is our own pessimism. | |
| Tiered verdict, no single bar | Conditional verdict per bracket. Most honest to synthetic data; pushes SC-4's decision downstream. | |

**User's choice:** Typical passes, worst informs

---

### Q3: Does Phase 0 produce the critical-channel subset regardless of outcome?

| Option | Description | Selected |
|--------|-------------|----------|
| Always name it | Ranked subset and its bit rate whether go or no-go. Cheap once per-ID numbers exist; doubles as the degraded-mode list Phase 5 and any marginal real-bus result will want. (Recommended) | ✓ |
| Only on a no-go | Exactly what SC-4 requires, nothing more. If real traffic later comes in worse, someone picks the subset under time pressure during testing season. | |
| Always name it, user picks signals | Same, but the user supplies the priority list. Most accurate to what the team watches; needs user input before the phase can finish. | |

**User's choice:** Always name it
**Notes:** Deriving the ranking still requires knowing which signals the pit engineer actually watches — noted in CONTEXT.md.

---

### Q4: Where do the report and decision live, and how are they produced?

| Option | Description | Selected |
|--------|-------------|----------|
| Generated report + hand-written decision | Tool emits report and machine-readable data; go/no-go is a short human document citing it. Numbers reproducible, judgement quotable. SC-4 wants a decision later phases build against — that's a document, not tool output. (Recommended) | ✓ |
| One fully generated document | Verdict rendered by applying the threshold automatically. Zero drift; but the reasoning is the part that matters downstream and a template writes it badly. | |
| Decision in PROJECT.md only | A Key Decisions row plus the generated report. Keeps decisions in one place; less room for the subset list and attached conditions. | |

**User's choice:** Generated report + hand-written decision

---

### Q5: Which directory do the artifacts live in?

| Option | Description | Selected |
|--------|-------------|----------|
| Phase dir + PROJECT.md pointer | Both in `.planning/phases/00-compression-ratio-gate/`, verdict as a row in PROJECT.md's Key Decisions table (which already has a Pending entry for this gate). Consistent with GSD conventions and how downstream agents find things. (Recommended) | ✓ |
| `docs/` as a project deliverable | Findable by teammates who never touch `.planning/`; splits phase artifacts across two locations. | |
| Both — phase dir plus `docs/` copy | Best discoverability for a non-GSD teammate; two copies that can drift. | |

**User's choice:** Phase dir + PROJECT.md pointer

---

## Claude's Discretion

The user made an explicit selection on every question — no area was delegated wholesale. Discretion remains on:

- Signal-classification heuristics for the GATE-02 category breakdown
- The value of N in "worst N individual IDs"
- Exact module/file names inside the new package, and how far the layout is sketched now vs. left to Phase 1
- Report rendering across three brackets × ablations × several peak windows
- The proposed numeric threshold (planner proposes, user confirms before running)

## Deferred Ideas

- **zstd / generic compressor as a second pass over batches** — evaluates a transport-layer choice; belongs with Phase 1's batching, or as a rescue option on a marginal real-traffic re-measurement
- **Batch size as a swept parameter** — trades framing overhead against latency; Phase 1/5 territory. Phase 0 states one batch size as a config assumption
- **Writing the real-log reader (`.vsb`/`.blf`/`.asc`)** — interface built now, reader deferred until a real capture exists to test against
- **CPU cost per frame for the encoder** — already assigned to Phase 1's exit criteria in `.planning/research/SUMMARY.md`, where it can be measured on the actual CM4
- **Capturing a real log to re-run this gate against** — the deliberate follow-up to the synthetic-input decision; natural trigger is the first track or bench session in Phase 1
