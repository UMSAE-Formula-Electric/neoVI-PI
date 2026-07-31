# Phase 0: Compression Ratio Gate - Pattern Map

**Mapped:** 2026-07-31
**Files analyzed:** 22 (new package modules, config, tests, report/decision artifacts)
**Analogs found:** 6 / 22 — this is a greenfield phase (D-07: first package in the repo); most files have **no in-repo analog** and must follow RESEARCH.md's already-settled design (`ARCHITECTURE.md` Pattern 3) plus the conventions extracted below from `src/new_logger.py`, the only structurally similar file in the codebase.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `src/telemetry/wire/dictionary.py` | utility | transform | `src/new_logger.py::build_dbc_index` (lines 135-139) | role-match |
| `src/telemetry/wire/encoder.py` | service | transform | `src/new_logger.py::writer_thread` (decode/format core, lines 214-268) | partial (inverse operation, same "core transform" role) |
| `src/telemetry/wire/decoder.py` | service | transform | `src/new_logger.py::writer_thread` (decode core, lines 238-248) | partial |
| `src/telemetry/wire/frame_source.py` | model/interface | transform | `src/new_logger.py` raw tuple frame shape (lines 202-208) | role-match (data shape only; no Protocol precedent in repo) |
| `src/telemetry/wire/overhead.py` | utility | transform | none | no analog — pure arithmetic from RESEARCH.md constants |
| `src/telemetry/synth/entropy.py` | utility | transform | none | no analog — new domain (seeded synthetic generation) |
| `src/telemetry/synth/rates.py` | utility | transform | `src/new_logger.py::build_dbc_index` (cantools iteration pattern) | partial |
| `src/telemetry/synth/generator.py` | service | event-driven (generator/iterator) | `src/new_logger.py::capture_thread` (lines 164-211, "produce frame tuples" shape) | role-match |
| `src/telemetry/measure/classify.py` | utility | transform | none | no analog — first structural classifier in repo |
| `src/telemetry/measure/report.py` | service | batch/aggregation | none | no analog — first aggregation/report module |
| `src/telemetry/measure/cli.py` | controller (CLI entry point) | request-response (batch run) | `src/new_logger.py::main` (lines 274-446) | exact (argparse CLI shape) |
| `.planning/phases/00-compression-ratio-gate/config/gate.json` | config | file-I/O | none | no analog — first checked-in assumptions config |
| `tests/conftest.py` | test | file-I/O (fixture) | none | no analog — first test in repo |
| `tests/test_wire_roundtrip.py` | test | transform | none | no analog — first test in repo |
| `tests/test_classify.py` | test | transform | none | no analog |
| `tests/test_measure_report.py` | test | transform | none | no analog |
| `requirements-dev.txt` | config | file-I/O | none | no analog — no manifest exists yet |
| `pytest.ini` (or `pyproject.toml`) | config | file-I/O | none | no analog |
| `.gitignore` (modified) | config | file-I/O | existing `.gitignore` lines 5-16 | exact (edit, not new file) |
| `.planning/phases/00-compression-ratio-gate/00-REPORT.json` | artifact | file-I/O | `src/new_logger.py::emit_signal` (JSON emission shape, lines 77-87) | partial |
| `.planning/phases/00-compression-ratio-gate/00-REPORT.csv` | artifact | file-I/O | `src/new_logger.py::writer_thread` CSV writer (lines 225-227, 255-262) | role-match |
| `.planning/phases/00-compression-ratio-gate/00-DECISION.md` | artifact | file-I/O | none (human-authored) | N/A |
| `.planning/PROJECT.md` (modified — Key Decisions row) | config/doc | file-I/O | existing PROJECT.md row | exact (edit) |

## Pattern Assignments

### `src/telemetry/wire/dictionary.py` (utility, transform)

**Analog:** `src/new_logger.py::build_dbc_index` (lines 135-139)

**Core pattern to copy** (exact shape, extend for versioning per RESEARCH.md):
```python
def build_dbc_index(db) -> dict[int, object] | None:
    """Flat arb_id → cantools Message lookup. Faster than db.decode_message()."""
    if db is None:
        return None
    return {msg.frame_id: msg for msg in db.messages}
```
RESEARCH.md's Code Examples section already supplies the extended version this file should actually implement (`build_id_dictionary`, keyed on `(frame_id, is_extended_frame)` pairs with a `dict_version` hash) — use that as the target shape, but note it descends directly from this same-repo pattern: a flat dict comprehension over `db.messages`, no cantools decode calls.

**Import convention** (from `src/new_logger.py` lines 14-27):
```python
import cantools
from pathlib import Path
```

---

### `src/telemetry/wire/encoder.py` / `decoder.py` (service, transform)

**Analog:** `src/new_logger.py::writer_thread` (lines 214-268), specifically the decode-and-format core (lines 238-248) — inverse role (this is encode, not decode-for-display), but it is the only place in the repo that transforms a raw `(ts, arb_id, net_id, dlc, data)` tuple into another representation, which is exactly encoder.py's job.

**Raw frame tuple shape to preserve** (lines 202-208, 238):
```python
raw_queue.put((
    m.TimeSystem,
    m.ArbIDOrHeader & 0x1FFFFFFF,
    m.NetworkID,
    m.NumberBytesData,
    bytes(m.Data[:m.NumberBytesData]),
))
...
ts, arb_id, net_id, dlc, data = item
```
D-08's `RawFrame` NamedTuple (RESEARCH.md Pattern 4) is this same shape, formalized with a `Protocol`. Field order and "timestamp first, payload last" convention should be preserved for consistency with the rest of the codebase.

**Error-handling convention to copy** (lines 244-247) — silent-fallback-with-comment pattern the codebase already uses for decode failures; RESEARCH.md's Security Domain section explicitly says the *encoder/decoder* must NOT repeat this pattern (must raise on malformed input, per V5) — use as a documented anti-pattern reference, not something to copy verbatim:
```python
try:
    decoded = msg_def.decode(data)
except Exception:
    pass
```
Note for planner: RESEARCH.md's Common Pitfalls / Security Domain explicitly override this convention for wire/encoder.py and wire/decoder.py — those must raise clear errors on malformed length rather than silently swallow, unlike this analog.

**Byte layout — no in-repo analog.** Use `.planning/research/ARCHITECTURE.md` Pattern 3 verbatim (already quoted in RESEARCH.md's "Architecture Patterns" → Pattern 3), packed with stdlib `struct`.

---

### `src/telemetry/wire/frame_source.py` (interface/model, transform)

**No Protocol precedent exists in this codebase** (grep for `Protocol` / `ABC` in `src/` returns nothing). Use RESEARCH.md's Pattern 4 code example directly — it is already the concrete target shape, not a suggestion:
```python
from typing import Protocol, Iterator, NamedTuple

class RawFrame(NamedTuple):
    timestamp_us: int
    frame_id: int
    is_extended: bool
    payload: bytes

class FrameSource(Protocol):
    def frames(self) -> Iterator[RawFrame]: ...
```

---

### `src/telemetry/synth/generator.py` (service, event-driven/generator)

**Analog:** `src/new_logger.py::capture_thread` (lines 164-211) — role-match as "the thing that produces a stream of frame tuples," though capture_thread is a hardware-polling thread and generator.py is a pure-Python synthetic iterator (no threading needed here — D-08 wants a plain `Iterator[RawFrame]`).

**What to copy:** the discipline of "zero decoding, zero I/O in the producer" (module docstring, lines 7-9) — the generator should only emit `RawFrame` tuples, leaving encoding/measurement to downstream stages, mirroring capture_thread's separation from writer_thread.

**What NOT to copy:** threading/queue machinery — `generator.py` should be a plain generator function/class implementing the `FrameSource` Protocol, not a thread producer.

---

### `src/telemetry/measure/cli.py` (controller, request-response/batch)

**Analog:** `src/new_logger.py::main` (lines 274-446)

**Argparse pattern to copy** (lines 275-292):
```python
def main():
    p = argparse.ArgumentParser(description="...")
    p.add_argument("--dbc", default=DBC_FILE,
                   help="Path to .dbc file for decoding.")
    p.add_argument("--out", default=None,
                   help="Output directory (timestamped .csv created inside).")
    args = p.parse_args()
```

**DBC load-with-warning pattern to copy** (lines 294-302):
```python
db = None
try:
    db = cantools.database.load_file(args.dbc)
    log(f"Loaded DBC: {args.dbc}  ({len(db.messages)} messages)")
except Exception as e:
    log(f"[WARN] Could not load DBC '{args.dbc}': {e}. Decoding disabled.")
```
Note: RESEARCH.md's Security Domain wants this tightened for Phase 0 — an unreadable DBC should likely be a hard failure for a measurement tool (no meaningful "decoding disabled" degraded mode when the DBC *is* the input), but the try/except-with-`log()`-message shape is the convention to reuse.

**Entry point pattern** (line 446):
```python
if __name__ == "__main__":
    main()
```

---

### `src/telemetry/measure/report.py` (service, batch/aggregation) — no analog

No aggregation/reporting code exists anywhere in the repo. Follow RESEARCH.md's Architecture Patterns diagram (report.py consumes encoder.py output + classify.py buckets + overhead.py add-on) and the stdlib-only convention (`json`/`csv`, no `pandas` — see RESEARCH.md "Standard Stack → Alternatives Considered").

**JSON emission shape to borrow** (from `src/new_logger.py::emit_signal`, lines 77-87) — same "build dict, `json.dumps`, write" shape, though report.py should build one document and write once (not append newline-delimited per record):
```python
sys.stdout.write(json.dumps({...}) + "\n")
sys.stdout.flush()
```

**CSV writer shape to borrow** (`src/new_logger.py` lines 225-227, 255-262):
```python
with open(out_path, "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["timestamp_s", "arb_id", "network_id", "dlc", "data_hex", "decoded"])
    ...
    writer.writerow([...])
```

---

### `src/telemetry/measure/classify.py`, `src/telemetry/synth/entropy.py`, `src/telemetry/synth/rates.py`, `src/telemetry/wire/overhead.py` — no analog

These are net-new domains (structural signal classification, seeded entropy modelling, bus-load-scaled rate assignment, analytic overhead formula). No file in the repo does anything comparable. Implement directly from RESEARCH.md's Pattern 1 (classify heuristic), Pattern 2 (cantools API surface), and Pattern 3 (overhead constants) — those sections are already concrete, cited code, not abstractions to re-derive.

---

### `tests/*.py` — no analog (first tests in repo)

No test framework or test file exists anywhere in this repository (confirmed in RESEARCH.md's Environment Availability and Validation Architecture sections). Use RESEARCH.md's Code Examples → "Round-trip assertion shape (D-09)" verbatim as the target shape for `test_wire_roundtrip.py`:
```python
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
`conftest.py` should follow the codebase's existing "load once, module-level" convention seen in `src/new_logger.py`'s module-level `db = None` global pattern (line 64) — but as a proper pytest fixture (`scope="module"`) rather than a mutable global, since this is the first place the repo introduces test fixtures.

---

## Shared Patterns

### Logging: stdout for data, stderr for logs
**Source:** `src/new_logger.py` lines 70-75
**Apply to:** `cli.py`, `generator.py`, any module doing diagnostic output
```python
def log(*args, **kwargs):
    print("[LOG]", *args, **kwargs, file=sys.stderr)

def debug(*args, **kwargs):
    if DEBUGGING:
        print("[DEBUG]", *args, **kwargs, file=sys.stderr)
```
Report JSON/CSV artifacts are written to files under `.planning/phases/00-compression-ratio-gate/`, not stdout, so this phase's "stdout reserved for data" convention loosens slightly — but any log/progress output from `cli.py` should still go to stderr, matching the rest of the codebase.

### Path construction
**Source:** `src/new_logger.py` line 32
**Apply to:** `config/gate.json` loading, DBC path resolution, report output paths
```python
DEFAULT_OUTPUT_DIR = str(Path(__file__).parent.parent / "logs")
```
Use `Path(__file__).parent`-relative construction, never hardcoded absolute paths, consistent across `cli.py` and `conftest.py`.

### DBC loading and index-building
**Source:** `src/new_logger.py` lines 294-304, 135-139
**Apply to:** `dictionary.py`, `classify.py`, `rates.py`, `conftest.py`
```python
db = cantools.database.load_file(args.dbc)
dbc_index = {msg.frame_id: msg for msg in db.messages}
```
Every module reading DBC structure should go through a single load (per RESEARCH.md's `conftest.py` note: "avoid reloading a 1,241-line DBC per test") rather than each module calling `cantools.database.load_file()` independently.

### Naming and docstring convention
**Source:** `src/new_logger.py` lines 1-12 (module docstring), snake_case throughout
**Apply to:** all new `.py` files
- Module-level docstring stating purpose and one-line architecture summary (see `new_logger.py`'s "capture_thread / writer_thread / main thread" breakdown as the template for wire/synth/measure's own three-stage split).
- `snake_case` for functions (`build_id_dictionary`, `classify_signal`, `run_measurement`), verb-prefixed helpers (`ensure_`, `build_`, `classify_`, `resolve_`) per `.claude/CLAUDE.md`'s documented naming convention.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/telemetry/measure/classify.py` | utility | transform | First structural classifier in repo — no prior art in codebase or an external library (RESEARCH.md Assumption A2); implement from RESEARCH.md Pattern 1 |
| `src/telemetry/synth/entropy.py` | utility | transform | First seeded synthetic-data generator; implement from RESEARCH.md D-02/D-12 (seeded `random.Random` instances, never the global module) |
| `src/telemetry/synth/rates.py` | utility | transform | First rate-modelling module; implement from RESEARCH.md Pattern 2 + D-03, reading `message.cycle_time` at runtime (never hardcode the 23-message count, per Pitfall 3) |
| `src/telemetry/wire/overhead.py` | utility | transform | Pure arithmetic from already-known constants (RESEARCH.md Pattern 3's `cobs_worst_case_overhead`/`all_in_bytes_per_batch`) — copy those functions directly |
| `.planning/phases/00-compression-ratio-gate/config/gate.json` | config | file-I/O | First checked-in assumptions config in the repo (D-12); no `requirements.txt`/`package.json`-style precedent for structure — free-form JSON matching RESEARCH.md's listed fields (brackets, per-ID rates, bus split, batch size) |
| `.planning/phases/00-compression-ratio-gate/00-DECISION.md` | artifact | file-I/O | Human-authored, no code pattern applies |
| `requirements-dev.txt`, `pytest.ini`/`pyproject.toml` | config | file-I/O | No dependency manifest or test config exists anywhere in the repo yet — this phase is first; use standard pip/pytest conventions, not an in-repo analog |

## Metadata

**Analog search scope:** `src/` (all four existing scripts read/scanned), `can-dashboard/` (checked, no Python/CLI analogs — JS server pattern not applicable to this phase's pure-Python scope), `.planning/research/ARCHITECTURE.md` and `.planning/research/SUMMARY.md` (used as the canonical wire-format spec per D-05/Pattern 3, since no code analog exists for a novel binary encoding)
**Files scanned:** `src/new_logger.py` (447 lines, fully read), `src/neoVI_logger.py` (grepped for `attach_controllers`/error-handling shape, not fully needed — same conventions as `new_logger.py`), `.gitignore` (confirmed CSV/JSON allowlist gap per RESEARCH.md Pitfall 2)
**Pattern extraction date:** 2026-07-31
</content>
