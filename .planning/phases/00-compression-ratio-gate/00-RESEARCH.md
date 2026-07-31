# Phase 0: Compression Ratio Gate - Research

**Researched:** 2026-07-31
**Domain:** Domain-specific binary wire-encoding + offline measurement tooling for a CAN telemetry compression gate, built against a real vehicle DBC
**Confidence:** MEDIUM-HIGH — HIGH on the DBC's actual structure (measured directly from `epbr2026_DBC_v1.0.dbc`), HIGH on the cantools API surface needed, MEDIUM on the concrete entropy-bracket and rate-assignment methodology (necessarily judgment calls on synthetic modelling, flagged individually), LOW/flagged wherever a claim rests on training knowledge rather than something checked in this session.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Measured stream is synthesized from `epbr2026_DBC_v1.0.dbc`, not captured from the car and not sourced from an existing log — none exists in the repo. Known limitation (synthetic data only has the entropy the model gives it) accepted; D-02/D-14 are the compensating controls. Reversible via D-08's pluggable frame source.
- **D-02:** Entropy modelled as three brackets — best / typical / worst — reported as a band, not a point.
- **D-03:** Frame rates come from `GenMsgCycleTime` where declared, remaining messages assigned plausible rates scaled so per-bus totals match documented real bus loads (bus 1 ~70%/~2,900 fps, bus 2 ~20%/~830 fps).
- **D-04:** Worst-case IDs selected by category (rolling counter / checksum / multiplexed / high-entropy analog, each bucket aggregated separately) AND by rank (worst N individual IDs by measured bytes/frame, regardless of bucket). Name-based detection alone is insufficient.
- **D-05:** Phase 0 builds the real reusable encoder core (delta timestamp, ID dictionary, per-ID payload delta, per-ID sequence byte) — not COBS/CRC framing, batching, or transport. Costly to reverse: Phase 1 and Phase 4 both import this module.
- **D-06:** Framing overhead is an analytic line item on top of the payload measurement, not implemented. Report clean payload bytes/frame separately, then add itemised computed overhead (COBS worst-case ~1 byte/254, CRC-16 2 bytes/batch, batch header) at a stated batch size. Radio-budget comparison uses the all-in number; per-ID analysis uses clean payload.
- **D-07:** Encoder core lives in a new package starting the target rebuild layout (e.g. `src/telemetry/wire/`), not a flat script and not `tools/`. Costly to reverse — sets the layout Phase 1/Phase 2 build into.
- **D-08:** Tool reads frames through a pluggable frame-source interface. Synthetic generator is one implementation; do NOT write the real-log reader now.
- **D-09:** Phase 0 also builds the matching decoder and asserts every synthetic frame round-trips byte-identical. Introduces pytest into a repo with no tests — accepted even though formal TEST-01…03 requirements live in Phase 5.
- **D-10:** Headline is the full planned encoding, reported alongside ablations isolating each mechanism's cost (with/without sequence byte, payload delta vs raw, ID dictionary on/off). Generic second-pass compressor (zstd) explicitly NOT in scope — deferred.
- **D-11:** Peak = sliding-window max reported at several scales (e.g. 100 ms, 1 s, 10 s), not a single number or theoretical worst-case alignment.
- **D-12:** Runs are seeded and deterministic, every modelling assumption in a checked-in config file (entropy brackets, per-ID rates, batch size, bus loads).
- **D-13:** Pass threshold is pre-registered — written down before the measurement runs. Form: a stated bit-rate ceiling plus required headroom percentage against the ~200–250 kbit/s budget. **Open item for planning:** the specific numeric threshold and headroom percentage were deliberately left unset — the planner proposes a concrete number for the user to confirm before running, not after.
- **D-14:** Typical bracket gates the verdict; worst-case bracket informs it (reported, not gating — if it fails, becomes a documented condition to re-check in Phase 1). One-way reversibility — every later phase's link scope is built against this verdict.
- **D-15:** Critical-channel subset is named regardless of outcome, not only on a no-go.
- **D-16:** Two artifacts: a tool-generated report (numbers, per-ID tables, brackets, ablations, machine-readable JSON/CSV) and a short hand-written go/no-go decision that cites it.
- **D-17:** Both artifacts live in `.planning/phases/00-compression-ratio-gate/`, verdict recorded as a row in PROJECT.md's Key Decisions table (existing `— Pending` row for this gate).

### Claude's Discretion

- Concrete signal-classification heuristics for D-04 (multiplexors are structural; counters/checksums inferable from bit width, position, naming; analog entropy from scaling, range, bit width).
- The value of N in "worst N individual IDs."
- Exact module and file names inside the D-07 package layout, and how far the layout is sketched now vs. left for Phase 1.
- Report rendering — how three entropy brackets × the ablation set × several peak windows are presented without a combinatorial explosion.
- The proposed numeric threshold in D-13 (proposed by the planner, confirmed by the user before running).

### Deferred Ideas (OUT OF SCOPE)

- zstd or any generic second-pass compressor over batches — a transport-layer choice, right time to test is when batching exists (Phase 1) or as a rescue option on a marginal real-traffic re-measurement.
- Batch size as a swept parameter — trades framing overhead against latency (Phase 1/5 territory); Phase 0 states a single value in the D-12 config instead.
- Writing the real-log reader (`.vsb`/`.blf`/`.asc`) — interface built now, reader deferred to when a real capture exists (Phase 1).
- CPU cost per frame for the encoder — assigned to Phase 1's exit criteria, measured on real CM4 hardware.
- Capturing a real log to re-run this gate — the deliberate follow-up to D-01, triggered by the first track/bench session in Phase 1, urgent if D-14's worst-case condition is unmet.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GATE-01 | Compression ratio measured against a real captured CAN log, reported as bytes/frame overall and per CAN ID | CONTEXT.md D-01 substitutes a DBC-derived synthetic stream for "a real captured log" (none exists in-repo); see Assumptions Log A1. Section `Architecture Patterns` gives the exact CFR/batch byte layout to measure against (from `.planning/research/ARCHITECTURE.md` Pattern 3, already settled). Section `Code Examples` gives the cantools calls needed to build the ID dictionary and per-ID structure the measurement iterates over. |
| GATE-02 | Measurement includes worst-case IDs — rolling counters, checksums, multiplexed messages, high-entropy analog — reported separately | Section `DBC Ground Truth` gives the actual counts found in `epbr2026_DBC_v1.0.dbc` (2 name-findable rolling counters, 3 multiplexed messages, 0 name-findable checksums) that D-04's structural classifier must catch beyond name matching. Section `Common Pitfalls` (Pitfall: Multiplexed-message XOR corruption) explains the specific failure this measurement must expose, not paper over. |
| GATE-03 | Documented go/no-go decision records whether full-bus streaming is viable or falls back to critical channels | Section `Decision Artifact — Proposed D-13 Threshold` gives a concrete, sourced proposed number for the user to confirm. Section `Don't Hand-Roll` and `Architecture Patterns` point at the exact PROJECT.md/ROADMAP.md rows this decision must update (D-17). |
</phase_requirements>

## Summary

Phase 0 is a self-contained, offline measurement problem: build the byte-producing half of an already-designed wire protocol (the full design exists in `.planning/research/ARCHITECTURE.md` Pattern 3 — Phase 0 does not need to invent the encoding, only implement and measure it), run it against traffic synthesized from the team's real 128-message DBC, and report real bytes/frame with worst-case IDs broken out. The DBC itself was inspected directly for this research (not assumed): it has exactly 128 messages, 23 carry a `GenMsgCycleTime` attribute (CONTEXT.md's "~21" estimate was close but not exact — use the measured 23), exactly 2 signals are name-findable rolling counters (`VCU_INV_RollingCounter`, `INV_Rolling_Counter`), exactly 0 signals are name-findable as checksums/CRCs, and exactly 3 messages are multiplexed (`CAR_ERROR_STATE`, `CAN_ENERGY_METER_TEMPERATURE` with 7 mux values covering 32 packed temperature signals, and the extended-ID `INV_Diag_Buffer` with 6 mux values). No nested/extended multiplexing was found despite the DBC declaring `MultiplexExtEnabled = Yes`, but this was checked by regex, not by loading the file with cantools — the plan should re-verify this programmatically as a first step, not assume the regex result. Several messages use 29-bit extended CAN IDs (values above 2^31 in the raw DBC text, e.g. `INV_Diag_Buffer` at 2147486373, all four IMU messages, and `PDM_PDM1_FaultCodes`-style range) — `cantools` handles this transparently via `message.frame_id` / `message.is_extended_frame`, but the ID dictionary must be built from `frame_id`, not the raw DBC integer.

The single most consequential gap this research surfaces: **the DBC contains no per-message bus assignment.** There is one `BU_:` node line listing all eight ECUs as if on one bus; nothing in the file distinguishes which messages ride HSCAN (bus 1, ~2,900 fps) versus HSCAN2 (bus 2, ~830 fps) per D-03. This split is not derivable from anything in the repository — it requires the team's own knowledge of their physical bus wiring, and should be captured explicitly in the D-12 checked-in config rather than inferred silently by the generator.

The encoder core, decoder, classifier, synthetic generator, and measurement/report tool are all pure-Python, stdlib-heavy work (matching the codebase's existing convention) with exactly one new dependency: `pytest`, for the D-09 round-trip assertion. `cantools` is already a project dependency (already imported by all three existing loggers) and is used here only to read DBC structure, never to decode payloads — decode-on-ground-station is this project's already-settled architectural inversion, so a Phase-0 "decoder" exists only to prove the encoder is reversible, not as a preview of the real ground-station package.

**Primary recommendation:** Implement the wire-encoding exactly as already specified in `.planning/research/ARCHITECTURE.md` Pattern 3 (CFR + batch-header layout is already fully designed — don't re-derive it), classify DBC signals structurally (not by name) per the concrete heuristics below, and treat the missing bus-assignment data as a required, explicit, human-supplied input to the D-12 config rather than something the generator infers.

## Architectural Responsibility Map

This phase has no web-application tiers (browser/API/CDN/DB) — it maps instead onto this project's own already-settled car/ground-station split. Mapping capabilities against that split now prevents Phase 0 code from landing in the wrong package and needing to move in Phase 1.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| DBC structure reading (messages, cycle times, mux, extended-ID flags) | Offline Analysis Tooling (Phase-0-only) | Car-side Telemetry Library (`dictionary.py` is reused unchanged in Phase 1/4) | Reading structure to build a dictionary is shared with the real system; the tool driving it (argparse CLI, report generation) is Phase-0-only |
| Wire encoding (delta ts, ID dictionary, payload delta, sequence byte) | Car-side Telemetry Library (`src/telemetry/wire/`) | — | This is the D-05 reusable core Phase 1 imports for real capture and Phase 4 hardens — must live where Phase 1 will import from, per D-07 |
| Wire decoding (round-trip verification only) | Car-side Telemetry Library (`src/telemetry/wire/decoder.py`), test-scoped | Ground-station (real decoder is rebuilt/hardened there in Phase 4) | D-09 requires a matching decoder to prove reversibility now; the *real* ground-station reconstructor (with per-ID state, gap detection) is Phase 4 scope per `.planning/research/ARCHITECTURE.md` — Phase 0's decoder is deliberately the minimal mirror needed for the round-trip assertion, not that component |
| Synthetic frame generation (entropy brackets, rate assignment) | Offline Analysis Tooling | — | No car or ground-station component; exists only to drive the measurement, per D-08's "pluggable frame source" design (a real-log reader is the alternate implementation, deferred) |
| Bytes/frame measurement, aggregation, per-ID/ablation/peak-window reporting | Offline Analysis Tooling | — | Produces the report artifact (D-16); no runtime component ships from this |
| Framing overhead (COBS/CRC/batch header) estimate | Offline Analysis Tooling (analytic formula only) | Car-side Telemetry Library (Phase 1 implements it for real, per `.planning/research/ARCHITECTURE.md` Pattern 3) | D-06 — computed from known constants (COBS ~1/254, CRC-16 = 2 bytes, 13-byte batch header already specified), never implemented here |
| Go/no-go decision | Human-authored document | PROJECT.md Key Decisions table (D-17) | D-16 — deliberately not a tool output |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `cantools` | 42.0.3 (latest on PyPI, verified via `pypi.org/pypi/cantools/json`) | Read DBC structure: messages, `cycle_time`, mux detection, extended-ID handling | Already the established decode path across all three existing loggers (`src/new_logger.py`, `src/neoVI_logger.py`) — not a new dependency, just a new use (structure reading vs. payload decode) |
| `pytest` | 9.1.1 (latest on PyPI, verified via `pypi.org/pypi/pytest/json`) | D-09's round-trip assertion; first test framework in this repository | De facto standard Python test runner; introducing it here is an explicit, accepted decision (D-09), not scope creep |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `struct` (stdlib) | — | Pack/unpack the CFR byte layout (flags, id_index, seq, delta_t_us, payload) | Every encoder/decoder call — matches the codebase's stdlib-first convention |
| `dataclasses` (stdlib) | — | Typed containers for per-ID state, classification results, report rows | Keeps encoder/classifier code readable without adding a dependency |
| `json`/`csv` (stdlib) | — | D-16's machine-readable report output | Matches existing convention (`json module (stdlib)` already used for stdout emission in `new_logger.py`) |
| `random` (stdlib, seeded) | — | D-12's deterministic entropy-bracket sampling | `random.Random(seed)` instances, never the global `random` module, so runs are reproducible per-component |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled CFR struct packing | `cobs`/`crc` packages for the framing overhead line item | D-06 explicitly says framing is analytic-only in Phase 0 — installing `cobs`/`crc16` now would be premature; the exact numbers needed (COBS ≈1 byte/254 ≈0.39%, CRC-16 = 2 bytes/batch, 13-byte batch header) are already known constants, not something that needs a library call in this phase |
| stdlib `json`/`csv` for the report | `pandas` for per-ID tables | Pulls in a large dependency for tabular output this project doesn't otherwise need; stdlib is sufficient for a 128-row table and matches the existing "stdlib-heavy" convention |

**Installation:**
```bash
pip install cantools pytest
```
No `requirements.txt` exists yet (confirmed absent, per `.planning/codebase/CONCERNS.md`). Creating the full manifest is explicitly Phase 1's job (OPS-06). Recommend a minimal, clearly-scoped file for Phase 0 (e.g. `requirements-dev.txt` with just `cantools` and `pytest`, pinned) rather than either (a) silently `pip install`ing with nothing checked in, or (b) building the full manifest early and duplicating Phase 1's work. Flag this file as superseded once Phase 1 lands `requirements.txt`.

**Version verification:** Both versions above were confirmed directly against the PyPI JSON API (`pypi.org/pypi/<name>/json`, `info.version` field) in this research session, not from training data or a general web search — training-data version numbers for fast-moving packages like `cantools` are commonly months stale.

## Package Legitimacy Audit

| Package | Registry | Age (latest release) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----------------------|-----------|--------------|---------|-------------|
| `cantools` | PyPI | Latest release (42.0.3) published 2026-07-05 — the *package* itself is long-established (already an in-use dependency across every existing logger in this repo) | Not returned by the legitimacy-check API | Not returned by the legitimacy-check API (actual repo: `github.com/cantools/cantools`) | SUS (automated heuristic: "too-new", "unknown-downloads", "no-repository") | **Approved, verdict overridden with justification** — this package is not newly discovered; it is already imported and relied upon in `src/new_logger.py`, `src/neoVI_logger.py`, and `src/references.py` in this exact repository. The SUS signal reflects the *latest point release's* recency and the checker's inability to fetch download/repo metadata for this ecosystem query, not evidence of a hallucinated or malicious package. |
| `pytest` | PyPI | Latest release (9.1.1) published 2026-06-19 | Not returned by the legitimacy-check API | `github.com/pytest-dev/pytest` (returned by checker) | SUS (automated heuristic: "unknown-downloads" only) | **Approved, verdict overridden with justification** — pytest is the de facto standard Python test framework; the sole SUS signal is a missing downloads figure from the checker's data source, not a legitimacy concern. |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** `cantools`, `pytest` — both overridden above with justification (pre-existing dependency; industry-standard tooling with a verifiable GitHub organization). Per protocol this SUS verdict still means the planner should insert a lightweight `checkpoint:human-verify` before the `pip install` step purely as a formality — the override reasoning above should be visible at that checkpoint so a reviewer isn't alarmed by the raw verdict.

No other packages are installed in this phase. `cobs` (1.2.2 on PyPI) and any CRC-16 library are explicitly **not** installed — D-06 keeps framing overhead analytic-only.

## DBC Ground Truth

Measured directly from `epbr2026_DBC_v1.0.dbc` in this repository during this research session (not assumed):

| Property | Measured value | Relevance |
|---|---|---|
| Total messages (`BO_` count) | 128 | Matches CONTEXT.md/PROJECT.md's stated figure |
| Messages with `GenMsgCycleTime` attribute | 23 | CONTEXT.md/D-03 states "~21 of 128" — close but the exact count is 23; use 23, not 21, when the plan implements D-03's rate assignment |
| Name-findable rolling counters | 2 (`VCU_INV_RollingCounter` on `M192_Command_Message`, `INV_Rolling_Counter` near `CAN_MC_RX_TORQUE_CAPABILITY`/`M176_Fast_Info`) | Confirms D-04's premise: name-based detection alone catches almost nothing; structural classification is required |
| Name-findable checksum/CRC signals | 0 | No signal anywhere in the DBC has "checksum" or "crc" in its name — if worst-case checksum-carrying IDs exist on this bus, they must be found by bit-width/position heuristics, not name matching, or the report will simply omit that category |
| Multiplexed messages | 3 — `CAR_ERROR_STATE` (mux 0 only, 2 flag bits), `CAN_ENERGY_METER_TEMPERATURE` (mux 0–6, 32 `Temp_N` signals packed 5-per-mux-value), `INV_Diag_Buffer` (mux 0–5+, extended-ID diagnostic message) | These are the entire population D-04's "multiplexed" bucket has to work with — small enough to hand-verify each one's classification result |
| Nested/extended multiplexing (`MultiplexExtEnabled = Yes` is declared) | **Not found by regex** (`m\d+M` pattern, zero matches) | Flagged, not confirmed — the file *declares* extended muxing is enabled but no signal appears to use nested selectors. Verify this programmatically with `cantools` (`signal.multiplexer_ids` returning more than one level) as an early Phase 0 step rather than trusting the regex result, since a missed nested-mux signal would silently corrupt that message's XOR-delta encoding |
| Extended (29-bit) CAN IDs | Present — e.g. `INV_Diag_Buffer` (raw DBC value 2147486373), all four IMU messages (`SlopeSensor_Type2`, `AngularRate`, `Acceleration`, `Magnetometer`, raw values ~2.56–2.57 billion) | The raw integer in the `BO_` line has the extended-frame marker bit already added by the DBC export tool (standard Vector DBC convention: bit 0x80000000 set). `cantools`'s `message.frame_id` returns the ID with that bit stripped; `message.is_extended_frame` reports the flag separately. **The ID dictionary must be built from `frame_id`+`is_extended_frame` as a pair, not the raw file integer** — two messages could theoretically share a `frame_id` value while differing only in the extended flag |
| Per-message bus assignment (HSCAN vs HSCAN2) | **Not present in the DBC at all** — single `BU_:` node line lists all 8 ECUs with no per-bus channel indicator | D-03 requires bus-load-scaled rates split ~70%/~2,900 fps (bus 1) vs ~20%/~830 fps (bus 2), but nothing in this repository states which of the 128 messages rides which physical bus. This must be supplied as an explicit, human-authored mapping in the D-12 config — see Open Questions |
| ECU/node breakdown (`BU_:` line) | `ENERGY_METER`, `INERTIAL_MEASUREMENT_UNIT`, `SENSOR_CONTROL_UNIT`, `VEHICLE_CONTROL_UNIT`, `ACCUMULATOR_CONTROL_UNIT`, `MOTOR_CONTROLLER`, `EMUS_BMS`, `U2C` | Useful for D-15's critical-channel candidate list (see Open Questions) and as a plausible (but unconfirmed) proxy for bus assignment if no better source exists |

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────┐
                         │   epbr2026_DBC_v1.0.dbc       │
                         │   (single source of truth)    │
                         └───────────────┬───────────────┘
                                         │ cantools: db.messages,
                                         │ cycle_time, is_multiplexed(),
                                         │ frame_id, is_extended_frame
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
        ┌───────────────────┐ ┌───────────────────┐ ┌──────────────────────┐
        │ dictionary.py       │ │ classify.py         │ │ rates.py               │
        │ static frame_id →   │ │ D-04: counter /     │ │ D-03: GenMsgCycleTime  │
        │ id_index table       │ │ checksum / mux /    │ │ where declared, else  │
        │ (versioned)          │ │ analog + rank        │ │ bus-load-scaled        │
        └──────────┬──────────┘ └──────────┬──────────┘ └───────────┬───────────┘
                    │                        │                        │
                    └────────────┬───────────┴────────────┬───────────┘
                                 ▼                          ▼
                    ┌─────────────────────────────────────────────────┐
                    │  generator.py — SyntheticFrameSource               │
                    │  (D-08: implements a pluggable FrameSource         │
                    │  Protocol; produces (timestamp, frame_id,          │
                    │  is_extended, payload) tuples per entropy bracket) │
                    └───────────────────────┬─────────────────────────┘
                                            │  D-02: run once per bracket
                                            │  (best / typical / worst)
                                            ▼
                    ┌─────────────────────────────────────────────────┐
                    │  encoder.py — the D-05 byte-producing core         │
                    │  delta_t_us · id_index · payload XOR/trim ·        │
                    │  per-ID seq byte  →  CFR bytes                     │
                    └───────────────────────┬─────────────────────────┘
                        ┌────────────────────┼──────────────────────┐
                        ▼                    ▼                       ▼
            ┌───────────────────┐ ┌────────────────────┐ ┌───────────────────────┐
            │ decoder.py          │ │ report.py             │ │ overhead.py (D-06)      │
            │ D-09: byte-identical│ │ aggregate + per-ID +   │ │ analytic COBS/CRC/batch  │
            │ round-trip assertion│ │ ablations (D-10) +     │ │ header add-on, no impl   │
            │ (pytest)            │ │ peak windows (D-11)    │ └────────────┬──────────┘
            └─────────────────────┘ └──────────┬────────────┘              │
                                                 └──────────────┬───────────┘
                                                                 ▼
                                              ┌───────────────────────────────┐
                                              │ report.json / report.csv        │
                                              │ (D-16 tool-generated artifact)  │
                                              └───────────────┬───────────────┘
                                                               │ cites
                                                               ▼
                                              ┌───────────────────────────────┐
                                              │ DECISION.md (D-16 hand-written) │
                                              │ go/no-go vs D-13 threshold      │
                                              │ → PROJECT.md Key Decisions (D-17)│
                                              └───────────────────────────────┘
```

A reader can trace the primary use case left-to-right/top-to-bottom: DBC → structure readers (dictionary/classify/rates) → synthetic generator → encoder → {decoder for correctness, report for measurement, overhead for the analytic add-on} → report artifact → human decision document → project-level record.

### Recommended Project Structure

```
src/telemetry/
├── __init__.py
└── wire/
    ├── __init__.py
    ├── dictionary.py        # static frame_id+is_extended → id_index table, versioned (dict_version)
    ├── encoder.py            # D-05 core: delta timestamp, payload delta/XOR+trim, per-ID seq byte
    ├── decoder.py             # matching decoder — D-09's round-trip target, per-ID state dict
    ├── frame_source.py        # D-08: FrameSource Protocol (pluggable — synth now, real-log later)
    └── overhead.py             # D-06: analytic COBS/CRC-16/batch-header add-on (no framing impl)

src/telemetry/synth/
├── __init__.py
├── entropy.py               # D-02: best/typical/worst bracket generators, seeded
├── rates.py                  # D-03: cycle_time-derived + bus-load-scaled per-message rates
└── generator.py                # SyntheticFrameSource implementing frame_source.FrameSource

src/telemetry/measure/
├── __init__.py
├── classify.py               # D-04: structural classifier (counter/checksum/mux/analog + rank-N)
├── report.py                   # aggregation: per-ID, ablations (D-10), peak windows (D-11)
└── cli.py                       # argparse entrypoint — matches existing loggers' CLI convention

.planning/phases/00-compression-ratio-gate/
├── config/
│   └── gate.json              # D-12: checked-in assumptions (brackets, rates, bus split, batch size)
├── 00-REPORT.json               # D-16 tool-generated artifact (machine-readable)
├── 00-REPORT.csv                 # D-16 tool-generated artifact (per-ID table)
└── 00-DECISION.md                 # D-16 hand-written go/no-go, cites the report

tests/
├── __init__.py
├── conftest.py                # module-scoped fixture: load epbr2026_DBC_v1.0.dbc once
├── test_wire_roundtrip.py       # D-09: every synthetic frame round-trips byte-identical
├── test_classify.py              # D-04: known IDs (the 2 counters, 3 mux messages) classify correctly
└── test_measure_report.py         # sanity checks on aggregation/ablation/peak-window math
```

**Placement notes:**
- `src/telemetry/wire/` is the only package Phase 1/4 import from — keep it free of anything synthetic-data- or report-specific (D-05/D-07's whole point).
- `src/telemetry/synth/` and `src/telemetry/measure/` are Phase-0-only; nothing later imports them, so they're safe to be more script-like.
- Placing config and report artifacts under `.planning/phases/00-compression-ratio-gate/` (not `src/`) directly satisfies D-17 and keeps Phase-0-only outputs out of the package Phase 1 will build on.
- `.gitignore` currently ignores `*.csv` globally (line 16) with no allowlist exception (unlike `.planning/**/*.json`, which is explicitly allowlisted on line 7). **The report's CSV artifact will be silently excluded from git unless the plan adds an allowlist line** (e.g. `!.planning/phases/00-compression-ratio-gate/**/*.csv`) or the CSV is placed under a path already covered by the existing `.planning/**/*.json` allowlist and renamed to `.json`. This is a concrete, easy-to-miss failure mode: the report is D-16's load-bearing artifact and D-17 requires it to live in a tracked location.

### Pattern 1: Structural (not name-based) signal classification for D-04

**What:** Classify every signal into rolling-counter / checksum / multiplexed / high-entropy-analog using bit width, position, and scaling — not name substring matching, since only 2 of the ~128 messages' worth of signals are name-findable as counters and 0 as checksums.

**When to use:** D-04's classifier, run once per DBC load, cached alongside the dictionary.

**Concrete heuristics (Claude's discretion, proposed for the plan to adopt or refine):**
```python
# Source: derived from CONTEXT.md D-04's stated heuristic + this session's DBC inspection,
# not from an external library — no off-the-shelf CAN signal classifier exists to cite.
def classify_signal(signal, message) -> str:
    # Multiplexed: purely structural, cantools tells you directly
    if message.is_multiplexed():
        return "multiplexed"

    # Rolling counter: small bit width (typically 4-8 bits), scale=1, offset=0,
    # range starts at 0 and covers exactly 2**length - 1 (a wraparound counter)
    if (signal.scale == 1 and signal.offset == 0
            and signal.length <= 8
            and signal.minimum == 0
            and signal.maximum == (2 ** signal.length) - 1):
        # Name match is a *positive* signal, not required:
        # VCU_INV_RollingCounter / INV_Rolling_Counter both satisfy this shape too
        return "rolling_counter_candidate"  # confirm by simulating and checking
                                             # for a monotonic-mod-2^n pattern

    # Checksum: same small-bit-width shape as a counter, but harder to distinguish
    # structurally alone — no checksum signal exists in this DBC to calibrate against.
    # Flag candidates the same way as counters and let the worst-N ranking (D-04's
    # second selection method) surface anything that behaves like one under the
    # generator's "worst" bracket (never compresses, unlike a real counter which at
    # least trims leading/trailing zero nibbles some of the time).

    # High-entropy analog: signal.length large relative to message size, scale is a
    # small fraction (fine-grained physical unit), and the message is NOT multiplexed
    if signal.length >= 8 and abs(signal.scale) < 1.0 and not message.is_multiplexed():
        return "analog_candidate"

    return "other"
```

**Trade-offs:** This heuristic will produce false positives (e.g., a genuinely static 8-bit enum with a wide declared range) and needs the worst-N ranking as a second, independent check per D-04 — the two methods together are the actual detection strategy, not either alone. **[ASSUMED]** — this specific heuristic was reasoned out for this DBC in this session, not sourced from an established CAN-tooling library; validate it against every one of this DBC's 128 messages by hand-checking the classifier's output for at least the 2 known counters, 3 known mux messages, and a handful of obviously-static signals (enums, flags) before trusting the aggregate report.

### Pattern 2: cantools API surface needed for D-03/D-04

**What:** The exact `cantools` calls the dictionary, classifier, and rate-assignment modules need. Confirmed against cantools' official documentation in this session (`cantools.readthedocs.io`).

```python
# Source: cantools official docs (fetched this session)
import cantools

db = cantools.database.load_file("epbr2026_DBC_v1.0.dbc")

for message in db.messages:                     # all 128 BO_ entries
    frame_id = message.frame_id                  # extended-flag already stripped
    is_ext = message.is_extended_frame            # True for the IMU / INV_Diag_Buffer messages
    cycle_ms = message.cycle_time                 # GenMsgCycleTime, int ms, or None (23/128 messages)
    is_mux = message.is_multiplexed()              # True for exactly 3 messages in this DBC

    for signal in message.signals:
        is_selector = signal.is_multiplexer         # the "M" signal itself (one per mux message)
        active_for = signal.multiplexer_ids           # which mux value(s) this signal is present under
        length_bits = signal.length
        scale, offset = signal.scale, signal.offset
        lo, hi = signal.minimum, signal.maximum
```

**Why this matters for D-03's rate assignment:** `message.cycle_time` returning `None` for 105 of the 128 messages is exactly the population D-03 assigns "plausible rates scaled so per-bus totals match documented real bus loads" to. The plan needs an explicit, documented method for that scaling (see Open Questions) — this API surface is necessary but not sufficient; the scaling algorithm itself is a modelling decision this research does not resolve.

### Pattern 3: The wire encoding is already fully designed — implement, don't redesign

**What:** `.planning/research/ARCHITECTURE.md` Pattern 3 already specifies the exact CFR (Compressed Frame Record) and batch-header byte layout this phase must measure against — flags byte, `id_index`, per-ID `seq` byte, `delta_t_us` (batch-relative uint16), `trim_count`, payload. Phase 0 should implement this design, not re-derive a new one.

```
# Source: .planning/research/ARCHITECTURE.md, Pattern 3 (already-settled project research)
byte 0:        flags        bit0 = KEYFRAME, bit1 = EXTENDED_ID, bits2-7 reserved
byte 1:        id_index     0-255, from the static dictionary
byte 2:        seq          8-bit, wraps, PER-ID (not global)
bytes 3-4:     delta_t_us   uint16, microseconds since this batch's base timestamp
byte 5:        trim_count   number of trailing zero bytes elided from the XOR delta
bytes 6..N:    payload      KEYFRAME: full DLC bytes; delta: XOR(payload, last_payload), trimmed
```

Batch header (13 bytes, fixed) is likewise already specified: `protocol_version` (1B), `dict_version` (1B), `batch_base_timestamp` (8B int64), `frame_count` (2B uint16), `batch_seq` (1B). D-06's analytic overhead formula should use these exact constants:

```python
# Overhead per batch, all constants sourced from the already-settled architecture design
BATCH_HEADER_BYTES = 13
CRC16_BYTES = 2
def cobs_worst_case_overhead(payload_bytes: int) -> int:
    return (payload_bytes // 254) + 1  # ~0.39% worst case, one byte per 254-byte block

def all_in_bytes_per_batch(clean_payload_bytes: int) -> int:
    body = clean_payload_bytes
    framed = body + CRC16_BYTES
    return BATCH_HEADER_BYTES + framed + cobs_worst_case_overhead(framed)
```

**Batch size:** D-06 requires "a stated batch size" as a D-12 assumption. `.planning/research/STACK.md`/`ARCHITECTURE.md` recommend a 20–50 ms flush cadence; at the combined ~4,000 fps target that's roughly 80–200 frames/batch. **[ASSUMED, proposed for planner to confirm alongside D-13]:** use 100 frames/batch (~25 ms at 4,000 fps combined) as the single D-12 value — a clean number inside the already-recommended range, small enough that `delta_t_us`'s uint16 (max 65,535 µs) comfortably covers the batch window with headroom.

### Pattern 4: Pluggable frame source (D-08)

**What:** A minimal `Protocol`/ABC so the synthetic generator and (later, Phase 1) a real-log reader are interchangeable without touching the encoder or measurement tool.

```python
from typing import Protocol, Iterator, NamedTuple

class RawFrame(NamedTuple):
    timestamp_us: int      # monotonic-since-epoch-start, matches the codebase's
                            # existing (timestamp, arb_id, network_id, dlc, data) shape
    frame_id: int           # cantools' frame_id (extended flag already resolved)
    is_extended: bool
    payload: bytes

class FrameSource(Protocol):
    def frames(self) -> Iterator[RawFrame]: ...
```

`SyntheticFrameSource` (this phase) and a future `.vsb`/`.blf` reader (explicitly deferred to Phase 1) both implement this. **[CITED: pattern generalized from `.planning/research/ARCHITECTURE.md` Pattern 4's `Link` Protocol design]** — the same "narrow interface, swappable implementation" approach already chosen for the transport layer, applied here to frame sourcing.

### Anti-Patterns to Avoid

- **Building the ID dictionary from the raw DBC file integer instead of `frame_id`:** the extended-ID marker bit (0x80000000) is embedded in several `BO_` lines' raw values — using it directly instead of `cantools`'s parsed `frame_id` will silently produce a dictionary with wrong/colliding indices for the IMU and `INV_Diag_Buffer` messages.
- **Classifying signals by name substring only:** this DBC has 0 name-findable checksums and only 2 name-findable counters — a name-only classifier will silently under-report GATE-02's worst-case categories.
- **Assuming the "~21 messages with GenMsgCycleTime" figure from CONTEXT.md is exact:** the measured count is 23. Off-by-2 doesn't change the modelling approach, but the plan's rate-assignment code should read the actual count from the DBC at runtime, never hardcode 21.
- **Inferring bus assignment from ECU node names without confirming with the team:** `SENSOR_CONTROL_UNIT`/`MOTOR_CONTROLLER`/etc. are a plausible but unconfirmed proxy for which physical bus a message rides — see Open Questions.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CFR/batch wire layout | A new byte-format design for Phase 0 specifically | The already-specified layout in `.planning/research/ARCHITECTURE.md` Pattern 3 | It's already fully designed, reviewed, and is what Phase 1/4 will actually build — measuring against a different layout in Phase 0 makes the gate's number meaningless for the real system |
| DBC structure parsing (message iteration, mux detection, cycle-time attributes) | Hand-rolled `.dbc` text parsing | `cantools.database.load_file()` + its documented API | Already the established, correct tool for this exact file across the whole codebase; hand parsing would duplicate work and risk missing the extended-ID marker-bit convention |
| COBS/CRC-16 byte counts | A real COBS/CRC-16 implementation for the overhead line item | The known closed-form constants (COBS ≈ payload/254 + 1 byte, CRC-16 = 2 bytes, batch header = 13 bytes — all from the already-settled architecture design) | D-06 explicitly scopes this as analytic-only; implementing real framing here would be scope creep into Phase 1's job and adds two dependencies (`cobs`, a CRC library) this phase doesn't need |
| Round-trip test harness for byte-identical assertions | A bespoke comparison/diff tool | `pytest` with plain `assert encoded_then_decoded == original` | Standard, no reason to build tooling around a simple equality assertion |

**Key insight:** almost everything Phase 0 needs was already designed in prior project research (`ARCHITECTURE.md`) or is a direct, already-established use of `cantools`. The actual net-new engineering in this phase is narrow: the entropy-bracket generator, the structural classifier, and the report aggregation — everything else is implementation of an existing design.

## Common Pitfalls

### Pitfall 1: Multiplexed-message XOR corruption, unmodelled

**What goes wrong:** If the synthetic generator treats a multiplexed message's payload like any other ID's payload (XOR against whatever the previous frame of that ID happened to be), and the mux selector changes between consecutive frames of the same ID, the "delta" is comparing two semantically unrelated byte layouts — this is exactly the failure `.planning/research/PITFALLS.md` Pitfall 1 and 2 warn about, and it needs to show up as a *measured, reported number* in this gate's output, not be silently avoided by generating traffic that never changes mux value.

**Why it happens:** It's easy to build a synthetic generator that holds each ID's mux value constant for simplicity — but that would make `CAN_ENERGY_METER_TEMPERATURE` (32 signals across 7 mux values) and `INV_Diag_Buffer` (diagnostic, likely mux value changes on every read cycle in reality) look artificially compressible, which directly undermines GATE-02.

**How to avoid:** The generator must cycle each multiplexed ID through its real mux value set (proportionally, per D-12's config) so the measurement captures the real cost of mux-value transitions, and D-04's "multiplexed" bucket must report this specifically — likely showing much worse compression than a same-mux-value baseline would suggest.

**Warning signs:** The report's "multiplexed" bucket shows compression as good as or better than the "typical analog" bucket — a strong sign the generator isn't actually varying mux values.

### Pitfall 2: `.gitignore`'s `*.csv` rule silently excludes the D-16 report artifact

**What goes wrong:** `.gitignore` line 16 (`*.csv`) has no allowlist exception, unlike `.planning/**/*.json` (line 7, explicitly allowlisted). If the plan writes `00-REPORT.csv` under `.planning/phases/00-compression-ratio-gate/` without adding a matching allowlist line, `git status` will never show it, and D-17's "both artifacts live in [that directory]" requirement will silently fail — the file exists on disk but was never committed.

**Why it happens:** The existing `.gitignore` was written for a codebase that treats CSV as bulk log/data output (correct for `src/new_logger.py`'s CSV logs), not as a curated planning artifact. Nothing about D-16's CSV report is exceptional-looking to someone skimming `.gitignore`.

**How to avoid:** Either (a) add `!.planning/phases/00-compression-ratio-gate/**/*.csv` to `.gitignore` (matching the existing `.planning/**/*.json` pattern), or (b) emit the machine-readable report only as JSON under `.planning/` (already allowlisted) and treat CSV as a convenience export outside git. Verify with `git status` after the report is first generated, not by inspection of the code alone.

### Pitfall 3: The `~21 messages with GenMsgCycleTime` figure is stale — use 23

**What goes wrong:** CONTEXT.md's D-03 cites "~21 of 128 messages" from earlier research. This session's direct grep of the DBC found 23 `BA_ "GenMsgCycleTime" BO_ ...` lines. Hardcoding 21 anywhere (a comment, a test assertion, a config default) will silently drift from the actual file.

**How to avoid:** Read the count from the DBC at runtime (`sum(1 for m in db.messages if m.cycle_time is not None)`); never hardcode either 21 or 23 into logic — only into narrative documentation, and even then note it's a measured, not fixed, quantity.

### Pitfall 4: Assuming the DBC states which bus each message is on

**What goes wrong:** D-03's rate-scaling math depends on knowing bus 1 vs. bus 2 membership per message. Nothing in `epbr2026_DBC_v1.0.dbc` encodes this (single `BU_:` node line, no per-message channel attribute). A plan that assumes this is derivable from the DBC (e.g., "parse the bus from an attribute") will fail at implementation time having already committed to that approach.

**How to avoid:** Treat bus assignment as a required, explicit, human-authored input in the D-12 config from the start of planning — see Open Questions for a proposed starting method.

### Pitfall 5: Encoder core drifts from the already-designed CFR layout "for convenience"

**What goes wrong:** Because D-05 explicitly says this is real, reusable code Phase 1/4 will import, any shortcut taken here (e.g., a slightly different byte order, a missing `trim_count` field, a `seq` byte that isn't per-ID) becomes technical debt baked into the layout Phase 1 builds on — D-05 marks this reversibility as "costly."

**How to avoid:** Treat `.planning/research/ARCHITECTURE.md` Pattern 3 as the spec, not a suggestion; if the plan needs to deviate from it (e.g., a different batch size), that deviation should be a deliberate, documented decision — not an implementation-time shortcut.

## Code Examples

### Loading the DBC and building a versioned ID dictionary
```python
# Source: cantools official docs (fetched this session) + project convention
# (matches src/new_logger.py's build_dbc_index pattern, extended for dict_version)
import hashlib
import cantools

def build_id_dictionary(dbc_path: str) -> tuple[dict[tuple[int, bool], int], bytes]:
    db = cantools.database.load_file(dbc_path)
    entries = sorted((m.frame_id, m.is_extended_frame) for m in db.messages)
    id_index = {key: i for i, key in enumerate(entries)}  # 0-255, fits <256 unique IDs
    dict_version = hashlib.sha256(repr(entries).encode()).digest()[:1]  # 1-byte version
    return id_index, dict_version
```

### Round-trip assertion shape (D-09)
```python
# Source: this session, following pytest convention + the codebase's stdlib-first style
import pytest
from telemetry.wire import encoder, decoder
from telemetry.synth.generator import SyntheticFrameSource

@pytest.mark.parametrize("bracket", ["best", "typical", "worst"])
def test_roundtrip_byte_identical(dbc_index, bracket):
    source = SyntheticFrameSource(dbc_index, bracket=bracket, seed=42)
    enc = encoder.Encoder(dbc_index)
    dec = decoder.Decoder(dbc_index)
    for frame in source.frames():
        cfr_bytes = enc.encode(frame)
        recovered = dec.decode(cfr_bytes)
        assert recovered.payload == frame.payload
        assert recovered.frame_id == frame.frame_id
```

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Synthesizing from the DBC is an adequate substitute for "a real captured log" (GATE-01's literal wording) | Phase Requirements, Summary | This is a locked project decision (D-01), not a research finding — flagged here only because it means GATE-01 is satisfied via CONTEXT.md's explicit substitution, and the plan/verification should reference D-01 explicitly when marking GATE-01 complete, not claim a real log was used |
| A2 | The structural classification heuristic in Pattern 1 (bit-width/range shape for counters, scale/length shape for analog) will correctly separate this DBC's signals into D-04's four categories | Architecture Patterns, Pattern 1 | No external CAN-tooling library was found that does this classification — the heuristic was reasoned out in this session against this specific DBC's known counters/mux messages, not validated against a broader dataset. Wrong classification means GATE-02's "worst-case IDs" table reports the wrong signals |
| A3 | 100 frames/batch (~25 ms at combined 4,000 fps) is a reasonable single D-12 batch-size assumption for D-06's overhead calculation | Architecture Patterns, Pattern 3 | If the real Phase 1 batch size differs substantially, the all-in bit-rate number in this gate's report would need recomputation — low risk since the formula (not just the number) is reported, but the headline "all-in" figure could mislead if read without the assumption |
| A4 | ECU node names (`SENSOR_CONTROL_UNIT`, `MOTOR_CONTROLLER`, etc.) are a reasonable starting proxy for which physical bus a message rides, pending team confirmation | Open Questions | If the actual wiring splits differently than ECU-name intuition suggests (e.g., some SCU messages are actually on bus 1), the bus-load-scaled rate assignment (D-03) would misallocate frame rates between buses, skewing the per-bus/combined bit-rate numbers |
| A5 | No nested/extended multiplexing exists in this DBC despite `MultiplexExtEnabled = Yes` being declared | DBC Ground Truth | Found by a text regex, not by loading with `cantools` and checking `signal.multiplexer_ids` depth — if wrong, a nested-mux message would be classified as simple mux and its encoding/classification could be subtly incorrect |

**If this table is empty:** N/A — see entries above; several genuine judgment calls exist in this domain (offline modelling of real traffic) and are flagged rather than presented as settled fact.

## Open Questions

1. **Which of the 128 messages ride bus 1 (HSCAN, ~2,900 fps) vs. bus 2 (HSCAN2, ~830 fps)?**
   - What we know: the DBC has no per-message bus attribute; the team's own bus load figures (70%/20% split) come from `telemetry_conversation.md`, which is aggregate, not per-message.
   - What's unclear: the actual physical wiring — which ECUs' messages are on which bus.
   - Recommendation: this needs a short answer from the team (likely already known informally — e.g., "drivetrain-critical ECUs on bus 1, sensor/BMS on bus 2") captured explicitly in the D-12 config as a per-ECU or per-message bus assignment list. If unavailable before the gate needs to run, a documented, clearly-labelled placeholder assignment (e.g., by ECU) should be used and the report should state this assumption prominently, since it affects every combined-bus number in the output.

2. **What is the actual proposed D-13 threshold, and does the team agree with the ~200 kbit/s conservative floor?**
   - What we know: the usable radio budget is documented as ~200–250 kbit/s; PROJECT.md's own "~40% headroom" claim is the number this whole architecture currently rests on.
   - What's unclear: whether the team wants the conservative (200 kbit/s) or optimistic (250 kbit/s) end of the range as the pass/fail baseline, and whether 40% headroom (vs. some other percentage) is the right bar.
   - Recommendation (planner's proposed threshold, per D-13's requirement that a concrete number be proposed for user confirmation before running):
     - **Baseline budget:** 200 kbit/s (conservative end of the stated range).
     - **Pass condition (typical bracket, all-in bit rate, gates the verdict per D-14):** average ≤ 120 kbit/s (≥40% headroom against 200 kbit/s, matching PROJECT.md's own headroom claim) **and** 1-second-window peak ≤ 170 kbit/s (≥15% headroom).
     - **Worst-case bracket:** reported, not gating — if the worst-case average exceeds 200 kbit/s, record it as a documented condition for Phase 1's real-traffic re-check per D-14, not a Phase 0 fail.
     - This is a proposal, not a locked decision — D-13 requires the user to confirm before the measurement runs.

3. **What is N in "worst N individual IDs" (D-04)?**
   - What we know: 128 total messages; the categorical buckets (counter/checksum/mux/analog) already isolate the structurally-worst signals.
   - What's unclear: how many additional individually-ranked worst IDs add value beyond the categorical buckets.
   - Recommendation: **N = 10** — large enough to catch outliers that don't fit a clean category (e.g., a wide-range signal that's neither an obvious counter nor obviously mux'd), small enough to read as a table alongside the four categorical buckets without combinatorial sprawl (ties into the report-rendering discretion item).

4. **What should the D-15 critical-channel candidate list start from?**
   - What we know: the `BU_:` ECU breakdown and the `ECU database breakdown/` per-ECU DBC files (BMS has by far the most messages at 67, suggesting cell-level monitoring detail) are the only structural hints in-repo; deriving true priority requires knowing what the pit engineer actually watches.
   - What's unclear: the actual watch-list — this is explicitly named in CONTEXT.md as requiring information not in the repository.
   - Recommendation: propose a starting candidate list from message/signal names that map obviously to safety-relevant or driver-facing values (cell voltages/temps from BMS, `BRAKE_TEMPS`, `TWO_FOOT_RULE`, `HTL_CH_ID_SAFETY_LOOP_STATUS`, wheel speed, motor temps/currents) and have the team confirm/amend it during plan review rather than treating this list as research-derived fact.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.x interpreter | Everything in this phase | ✗ (not confirmed in this research session — `python3` resolves only to a Windows Store app-execution-alias stub, no working interpreter found in the dev shell used for this research) | — | None — this is a hard blocker for implementation, not just this research session. The plan should include an early step confirming a working Python 3 interpreter is installed on the machine that will execute Phase 0, before any code is written |
| `cantools` package | DBC structure reading | Not confirmed installed (no working `pip`/`python` found to check) | Target: 42.0.3 (latest, PyPI-verified) | None needed if already used by existing loggers on the target dev machine — but this research session's environment could not confirm it |
| `pytest` package | D-09 round-trip test | Not installed anywhere in repo (confirmed — no `requirements.txt`, no test config files exist) | Target: 9.1.1 (latest, PyPI-verified) | None — this is the one genuinely new dependency this phase adds |

**Missing dependencies with no fallback:**
- A working Python 3 interpreter on the machine that will implement/execute Phase 0 — could not be confirmed present in this research session's shell environment. This should be the very first thing verified when planning moves to execution, not assumed.

**Missing dependencies with fallback:**
- None — both `cantools` and `pytest` are straightforward `pip install`s once Python itself is confirmed working; there's no viable "fallback" for either since they're the phase's only two dependencies.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest` 9.1.1 — not yet installed, first test framework introduced to this repository (D-09) |
| Config file | none — Wave 0 gap, needs a minimal `pytest.ini` or `pyproject.toml` `[tool.pytest.ini_options]` block |
| Quick run command | `pytest tests/ -x` |
| Full suite command | `pytest tests/` (small suite in this phase; no need for a separate "quick" subset yet) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GATE-01 | Encoder/decoder round-trips byte-identical across all three entropy brackets | unit | `pytest tests/test_wire_roundtrip.py -x` | ❌ Wave 0 |
| GATE-01 | Report aggregation math (bytes/frame, bit-rate conversion) is internally consistent | unit | `pytest tests/test_measure_report.py -x` | ❌ Wave 0 |
| GATE-02 | Known rolling-counter and multiplexed IDs (`VCU_INV_RollingCounter`, `INV_Rolling_Counter`, `CAR_ERROR_STATE`, `CAN_ENERGY_METER_TEMPERATURE`, `INV_Diag_Buffer`) are classified into the correct D-04 bucket | unit | `pytest tests/test_classify.py -x` | ❌ Wave 0 |
| GATE-03 | Go/no-go decision document exists, cites the report, and records a verdict | manual-only | N/A — human-authored artifact (D-16); verify by review, not automation | N/A |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x`
- **Per wave merge:** `pytest tests/`
- **Phase gate:** Full suite green before `/gsd-verify-work`; GATE-03's decision document is separately reviewed by a human, not covered by the automated suite.

### Wave 0 Gaps
- [ ] `tests/conftest.py` — module-scoped fixture loading `epbr2026_DBC_v1.0.dbc` once (avoid reloading a 1,241-line DBC per test)
- [ ] `tests/test_wire_roundtrip.py` — covers GATE-01's reversibility requirement (D-09)
- [ ] `tests/test_classify.py` — covers GATE-02's structural-classification requirement
- [ ] `tests/test_measure_report.py` — covers GATE-01's report-math correctness
- [ ] Framework install: `pip install pytest` — no test framework currently exists in this repository
- [ ] `pytest.ini` or `pyproject.toml` test config — none exists yet

## Security Domain

This phase has no network surface, no authentication, no persisted user data, and processes only a single trusted, already-in-repo input file (`epbr2026_DBC_v1.0.dbc`). Most ASVS categories genuinely do not apply; the ones that do are lightweight.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth surface — offline local tooling |
| V3 Session Management | No | No sessions — single-run CLI tool |
| V4 Access Control | No | No multi-user/access boundary — local file, local execution |
| V5 Input Validation | Yes (lightweight) | Bounds-check DLC/payload length before `struct.pack`/`struct.unpack` in the encoder/decoder — a malformed synthetic frame (e.g., payload longer than 8 bytes) should raise a clear error, not silently truncate or corrupt the CFR layout. `is_multiplexed()`/`multiplexer_ids` results should be validated against the signal's declared range before indexing, to avoid `IndexError`/`KeyError` on a malformed or edge-case DBC entry |
| V6 Cryptography | No — the `dict_version` hash (SHA-256 truncated to 1 byte) is a **version-mismatch detector, not a security control**; no confidentiality/integrity guarantee is claimed or needed here | N/A — do not present this as cryptographic protection anywhere in documentation |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/adversarial DBC file crashing the tool (not a realistic threat here — file is repo-local and trusted — but worth defensive handling given `.planning/codebase/CONCERNS.md`'s documented pattern of silent failures elsewhere in this codebase) | Denial of Service (self-inflicted, not adversarial) | Explicit `try`/`except` around `cantools.database.load_file()` with a clear error message, matching D-09's broader "no bare except" convention already adopted project-wide per `.planning/research/PITFALLS.md` Pitfall 8 |
| Struct pack/unpack length mismatch (e.g., a payload shorter than the DLC implies) silently producing wrong bytes rather than an error | Tampering (data corruption, not malicious) | Explicit length assertions before every `struct.pack`/`unpack` call in `encoder.py`/`decoder.py` — this is also exactly what D-09's round-trip test is designed to catch, so treat any such assertion failure surfaced by the test suite as the intended detection mechanism, not a bug to work around |

## Sources

### Primary (HIGH confidence)
- `epbr2026_DBC_v1.0.dbc` — directly inspected in this research session (message count, cycle-time attribute count, mux structure, rolling-counter/checksum name search, extended-ID values, `BU_:` node line) via `Grep`/`Bash` in this repository
- `pypi.org/pypi/cantools/json`, `pypi.org/pypi/pytest/json`, `pypi.org/pypi/cobs/json` — fetched directly via `WebFetch` for authoritative current version numbers
- `.planning/CONTEXT.md` (Phase 0), `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/PROJECT.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`, `.planning/research/SUMMARY.md`, `telemetry_conversation.md`, `.planning/codebase/CONCERNS.md` — this project's own settled research and decisions, read in full for this research session

### Secondary (MEDIUM confidence)
- `cantools.readthedocs.io` — fetched via `WebFetch` for `cycle_time`, `is_multiplexed()`, `multiplexer_ids`, `frame_id`/`is_extended_frame` API confirmation (Context7 MCP tooling was unavailable in this environment; used official docs directly instead, tagged `[CITED]` rather than `[VERIFIED: context7]`)
- COBS overhead figure (~1 byte per 254, ~0.39%) — corroborated across multiple sources (`mbedded.ninja`, Wikipedia, the `cobs` package's own PyPI/readthedocs pages) via `WebSearch`

### Tertiary (LOW confidence)
- The structural signal-classification heuristic (Pattern 1) — reasoned out in this session against this specific DBC, not sourced from an established library or published methodology; flagged as Assumption A2
- The proposed D-13 threshold numbers and D-06 batch-size assumption — planner proposals per the explicit CONTEXT.md discretion grant, not verified facts; flagged as Assumptions A3 and Open Question 2

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — both new/reused packages verified directly against PyPI's JSON API; no ambiguity about what's needed
- Architecture: HIGH — the wire encoding itself was already fully designed in prior project research; this phase implements a known spec rather than inventing one
- DBC ground truth: HIGH — measured directly from the file in this repository, not assumed
- Pitfalls: MEDIUM-HIGH — several are directly observed in this repository (`.gitignore` CSV gap, missing bus-assignment data); the modelling-methodology pitfalls (entropy brackets, classification heuristic) are reasoned, not externally validated
- Signal classification methodology: LOW-MEDIUM — no external prior art found for this exact problem; treat as a starting proposal, not settled practice

**Research date:** 2026-07-31
**Valid until:** 30 days for the stack/version claims (stable ecosystem, `cantools`/`pytest` don't churn fast); the DBC-ground-truth findings are valid until `epbr2026_DBC_v1.0.dbc` itself changes (should be re-verified if the DBC is ever updated before this phase executes)
