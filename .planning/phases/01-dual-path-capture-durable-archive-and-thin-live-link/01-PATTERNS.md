# Phase 1: Dual-Path Capture — Pattern Map

**Mapped:** 2026-08-01
**Files analyzed:** 20 (10 runtime modules/packages + 10 Wave 0 test files)
**Analogs found:** 20 / 20 (all have at least a role-match; several are exact-shape matches)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `config/logger.json` + `src/telemetry/*/config.py` loader (`OPS-05`) | config | request-response (startup parse) | `src/telemetry/measure/config.py` + `.planning/phases/00-.../config/gate.json` | **exact** |
| `src/telemetry/archive/session.py` | service/lifecycle | file-I/O | *(no direct analog — see below)*; nearest shape is `new_logger.py::ensure_output_path` | partial |
| `src/telemetry/archive/writer.py` | service | file-I/O, batch | *(no analog — new library, `mcap`)*; nearest shape is `new_logger.py::writer_thread`'s "drain queue → write" loop | role-match |
| `src/telemetry/archive/reader.py` | utility | file-I/O | *(no analog)* | none |
| `src/telemetry/capture/hardware_source.py` | service (device I/O) | streaming | `new_logger.py::open_device`, `resolve_net_ids`, `capture_thread` + `wire/frame_source.py`'s `FrameSource` Protocol | **exact** (Protocol contract) / role-match (device calls) |
| `src/telemetry/capture/replay_source.py` | service | file-I/O → streaming | `telemetry/synth/generator.py`'s `SyntheticFrameSource` (implements same `FrameSource` Protocol) | **exact** |
| `src/telemetry/capture/fanout.py` | service | event-driven, pub-sub (fan-out) | `new_logger.py::capture_thread` (queue push) — but overflow policy is new | role-match |
| `src/telemetry/framing/cobs_frame.py` | utility | transform | *(no analog — new library, `cobs`)* | none |
| `src/telemetry/framing/crc16.py` | utility | transform | *(no analog — new library, `crccheck`)* | none |
| `src/telemetry/wire/batcher.py` | utility | transform | `src/telemetry/wire/encoder.py` (sibling module, same package, same dataclass/struct-header idiom) | role-match |
| `src/telemetry/link/base.py` | interface/service | request-response (sync) | `src/telemetry/wire/frame_source.py`'s `FrameSource` Protocol | **exact** |
| `src/telemetry/link/loopback.py` | service | streaming | `src/telemetry/synth/generator.py` (in-process producer, no OS dependency) | role-match |
| `src/telemetry/link/udp.py` | service | streaming, event-driven | *(no analog — first network I/O in the codebase)*; nearest shape is `new_logger.py::capture_thread`'s poll loop | partial |
| `src/telemetry/ground/deframe.py` | transform | transform | `src/telemetry/wire/decoder.py` (sibling decode module, same package) | role-match |
| `src/telemetry/ground/cli.py` | controller/entrypoint | request-response loop | `new_logger.py::main()` (argparse + thread wiring + signal handlers) | role-match |
| `requirements.txt` | config | — | `requirements-dev.txt` (exact pins, same repo) | **exact** |
| `tests/test_logger_config.py` | test | — | `tests/test_gate_config.py` | **exact** |
| `tests/conftest.py` (`logger_config` fixture addition) | test fixture | — | `tests/conftest.py::gate_config` | **exact** |
| `tests/test_fanout.py` | test | event-driven | `tests/test_synth_stream.py` (closest existing streaming/generator test) | role-match |
| `tests/test_archive_writer.py`, `test_archive_crash_recovery.py`, `test_session.py`, `test_framing.py`, `test_link.py`, `test_end_to_end.py`, `test_soak.py` | test | file-I/O / event-driven | `tests/test_wire_roundtrip.py` (encode→decode roundtrip shape) for the byte-transform tests; `tests/test_measure_cli_smoke.py` for the CLI/process-level tests | role-match |

## Pattern Assignments

### `config/logger.json` loader (OPS-05) — new file, e.g. `src/telemetry/logger/config.py`

**Analog:** `src/telemetry/measure/config.py` (418 lines) — **this is the load-bearing analog for the whole phase; mirror its shape exactly, do not invent a second idiom.**

**Exact structure to copy:**
- Module docstring states the refusal-to-guess philosophy up front (lines 1–16).
- `REQUIRED_TOP_LEVEL_KEYS` / `REQUIRED_..._KEYS` as module-level `set()` constants (lines 26–57) — the loader diffs `raw_keys - REQUIRED` and `REQUIRED - raw_keys` explicitly, both directions, so unknown keys AND missing keys are separately, specifically named.
- One named exception class, no hierarchy needed:
```python
class GateConfigError(Exception):
    """Raised for any malformed, incomplete, or internally inconsistent
    gate.json -- this loader validates rather than defaults."""
```
For Phase 1 this becomes `LoggerConfigError(Exception)` — same one-liner docstring pattern, same "validates rather than defaults" phrasing.
- Frozen dataclasses per config sub-block (`EntropyBracket`, `BusTarget`, `Thresholds`, lines 77–108), plus one top-level frozen dataclass (`GateConfig`, lines 110–129) holding a `raw: dict = field(default_factory=dict, repr=False, compare=False)` — keep the raw JSON around for hashing/audit, excluded from `repr`/`eq`.
- `default_path()` classmethod resolves `Path(__file__).resolve().parent...` relative to the repo, never a hardcoded absolute path (lines 131–144) — explicitly cites the `src/new_logger.py` path-construction convention as its own precedent; Phase 1's loader should do the same relative-to-`__file__` resolution.
- `config_hash` property: SHA-256 over canonicalized (`sort_keys=True, separators=(",", ":")`) raw JSON, truncated to 12 hex chars (lines 146–152) — worth carrying into `logger.json` too, so a session's archive can record exactly which config produced it (mirrors ARCH-05's spirit of provenance).
- Validation helpers as free functions, not methods: `_require_positive_number(value, name)`, `_require_probability(value, name)` (lines 155–163) — reused across every field check, always raising with the dotted key path in the message (e.g. `"entropy_brackets.{name}.analog_dither_bits must be..."`).
- Per-block `_parse_X(name, value)` free functions (lines 165–295) each: (1) type-check the block is a dict, (2) diff required keys, (3) validate each field with the shared helpers, (4) return the frozen dataclass.
- Top-level `load_gate_config(path) -> GateConfig` (lines 298–417): open+parse with `try/except OSError` and `try/except json.JSONDecodeError`, each re-raised as the named error with `from exc`; then top-level key diffing; then per-field/per-block parsing in the same order as the dataclass fields; returns the fully constructed dataclass.

**For `config/logger.json` specifically**, the required top-level keys per RESEARCH.md/CONTEXT.md should cover: channels/net-ID mapping, DBC path, archive queue depth + flush cadence (record-count and time), telemetry queue depth, link settings (loopback/udp, host/port), and the critical-channel allowlist — each validated the same fail-closed way (unknown key = error, not warning, per the locked decision).

---

### `src/telemetry/capture/hardware_source.py` (service, streaming) — CAP-01 consolidation

**Analog for the Protocol contract:** `src/telemetry/wire/frame_source.py` (33 lines, read in full)

```python
class RawFrame(NamedTuple):
    timestamp_us: int
    frame_id: int
    is_extended: bool
    payload: bytes

class FrameSource(Protocol):
    def frames(self) -> Iterator[RawFrame]: ...
```
The module docstring (lines 1–11) explicitly says this Protocol was formalized *for* the deferred Phase 1 real-log/hardware reader — `hardware_source.py` should be the second-ever implementation, and `replay_source.py` the third (after `SyntheticFrameSource`). Implement `frames()` as a generator wrapping the poll loop; do not add extra required methods to the Protocol — keep it minimal per the existing contract.

**Analog for the hardware calls themselves:** `src/new_logger.py` — reusable shape, NOT reusable error handling (see Anti-Patterns below):
- `open_device(serial)` (lines 96–118): `ics.find_devices()` → filter by serial or take first → `ics.open_device(device)`. Raises `RuntimeError` with a descriptive message when nothing is found (lines 98, 108–111) — keep the fail-fast `RuntimeError`, but this phase's CAP-06 requires the error to also be logged with context, not just raised.
- `CHANNEL_MAP` / `NET_ID_TO_NAME` (lines 41–59): flat `dict[str, int]` mapping friendly channel names to `ics.NETID_*` constants, plus a reverse-ish display map. Copy this shape but load it from `config/logger.json` instead of hardcoding — CONTEXT.md's config decision says "never baked into code."
- `resolve_net_ids(channel_names)` (lines 121–133): resolves a list of channel-name strings to a `set[int]` of net IDs, falling back to `getattr(ics, f"NETID_{name.upper()...}")` for unmapped names. **Anti-pattern to drop:** the fallback path only logs a `[WARN]` and silently continues filtering as if the channel didn't exist (line 131) — CAP-06 requires this to be a hard, named, counted error instead.
- `build_dbc_index(db)` (lines 135–139): flat `{frame_id: cantools.Message}` dict, faster than repeated `db.decode_message()` lookups — reuse this exact idiom in `hardware_source.py`/`ground/cli.py` wherever DBC structure (not full decode) is needed on the car side.

---

### `src/telemetry/capture/fanout.py` (service, event-driven) — CAP-01..06

**Analog:** `src/new_logger.py::capture_thread` (lines 164–211) for the *poll → tuple → queue* shape; RESEARCH.md's own Pattern 1 (already vetted, verbatim below) for the *fan-out with divergent overflow* shape that must replace it.

**Reusable shape from `new_logger.py`:**
```python
def capture_thread(device, net_ids, raw_queue, stop_event, poll_s, hw_errors):
    while not stop_event.is_set():
        time.sleep(poll_s)
        try:
            msgs, error_count = ics.get_messages(device)
        except Exception as e:
            debug(f"[capture] get_messages error: {e}")
            stop_event.set()
            break
        if error_count:
            hw_errors[0] += error_count
        for m in msgs:
            if net_ids and m.NetworkID not in net_ids:
                continue
            raw_queue.put((m.TimeSystem, m.ArbIDOrHeader & 0x1FFFFFFF,
                            m.NetworkID, m.NumberBytesData,
                            bytes(m.Data[:m.NumberBytesData])))
    raw_queue.put(_STOP)   # sentinel shutdown
```
Keep: the `_STOP = object()` sentinel pushed at shutdown (line 62, 211), the shared-mutable-list counter pattern (`hw_errors = [0]`, line 170 param / 323 call site) for cross-thread counters, thread naming (`name="capture"`, daemon=True) and non-daemon writer (lines 335–346) so the writer flushes before exit, and `threading.Event` polled every loop iteration for shutdown (line 178, wired from `SIGINT`/`SIGTERM` handlers at lines 329–332).

**Must NOT copy — this is exactly the debt CAP-05/CAP-06 exist to eliminate:**
- `except Exception as e: debug(...)` then `stop_event.set(); break` (lines 183–187) swallows the real error type and exits with only a debug-level message (invisible unless `DEBUGGING=True`). Phase 1 needs a named, always-logged error with frame context.
- Single queue with one `put()` (line 202) — Phase 1 needs the two-queue fan-out from CONTEXT.md/RESEARCH.md Pattern 1 instead:
```python
def on_frame(frame, stop_event, hwm_counters, discard_counters):
    try:
        archive_q.put_nowait(frame)
    except queue.Full:
        log_critical("archive queue full — durability guarantee at risk; stopping session")
        stop_event.set()
        return
    hwm_counters.archive = max(hwm_counters.archive, archive_q.qsize())
    was_full = len(telemetry_q) == telemetry_q.maxlen
    telemetry_q.append(frame)
    if was_full:
        discard_counters.telemetry += 1
```
Note the `was_full`-checked-before-append idiom — `deque(maxlen=N).append()` gives no signal it evicted anything, so CAP-05's discard count must be computed this way, not by inspecting the deque afterward.

---

### `src/telemetry/archive/writer.py`, `session.py`, `reader.py` (ARCH-01..05)

**No direct analog exists in the codebase** — this is genuinely new: nothing currently uses `mcap`, and `new_logger.py`'s CSV writer (`writer_thread`, lines 214–268) is structurally the closest but is CSV/row-oriented, not a durable append-only container. Reuse only the *shape*, not the content:
- Own the file object, open once, write in a drain loop, close in a `finally`/explicit `close()` — same idea as `with open(out_path, "w", ...) as csvfile:` (line 225) wrapping the whole drain loop.
- Shared mutable counters passed in as one-element lists or small dataclasses (`frame_counter = [0]`, line 219/268) — carry into HWM/discard counters here too.

RESEARCH.md Pattern 2 (lines 308–357 of 01-RESEARCH.md) is the authoritative, already-verified reference implementation for `writer.py` (fsync cadence, `use_chunking=False`) and `reader.py` (`NonSeekingReader(..., log_time_order=False)` crash recovery) — the planner should point directly at that code, not re-derive it. Session naming/`.done` marker follow RESEARCH.md Pattern 3 (lines 361–379), which itself extends the same "own the file descriptor, fsync explicitly" discipline from Pattern 2.

**No analog found — flag for planner:** archive session lifecycle (UTC name + monotonic-counter fallback, `.done` sidecar) has zero precedent in this codebase; build directly from RESEARCH.md Pattern 3, there is no in-repo shape to imitate.

---

### `src/telemetry/framing/cobs_frame.py`, `crc16.py` (LINK-01/02)

**No analog exists** — first use of `cobs`/`crccheck` in the codebase. RESEARCH.md Pattern 6 (lines 414–444) is the verified reference (`cobs.encode`/`decode`, `cobs.cobs.DecodeError` catch, `Crc16CcittFalse.calc`). Structurally these should be small, pure-function modules matching the existing `src/telemetry/wire/decoder.py`/`overhead.py` style: no classes, just `encode(payload) -> bytes` / `decode(bytes) -> payload` raising a specific exception type, mirroring `CfrError`/`BatchWindowExceeded`/`PayloadTooLong`'s exception-family shape in `encoder.py` (lines 45–56):
```python
class CfrError(Exception):
    """Base exception for all CFR encode/decode failures."""

class BatchWindowExceeded(CfrError):
    """Raised when a frame's timestamp falls outside the batch's representable
    delta-t window..."""
```
Follow this same base-exception-plus-specific-subclass idiom for framing errors (e.g. a `FramingError` base, `CrcMismatch`/`CobsDecodeError` subclasses) so `ground/deframe.py` can catch one base type while still discriminating counters (LINK-02: "discarded and counted").

---

### `src/telemetry/link/base.py`, `loopback.py`, `udp.py` (LINK-03/04)

**Analog:** `src/telemetry/wire/frame_source.py`'s `FrameSource` Protocol (already used above) is explicitly named in CONTEXT.md as the style to mirror:
> "The link interface is a synchronous `send(bytes)` / `recv() -> bytes` Protocol... mirrors the `FrameSource` Protocol style already established in `src/telemetry/wire/frame_source.py`."

Concretely, `base.py` should be a `typing.Protocol` with 2–3 method stubs and `...` bodies, same minimal-surface style as `FrameSource`:
```python
class Link(Protocol):
    def send(self, data: bytes) -> None: ...
    def recv(self, timeout: Optional[float] = None) -> Optional[bytes]: ...
    def close(self) -> None: ...
```
(Verified reference implementations for `LoopbackLink`/`UdpLink` are in RESEARCH.md Pattern 7, lines 446–494 — `LoopbackLink` wraps a `queue.Queue`, `UdpLink` wraps a bound `socket.SOCK_DGRAM`.) No analog exists in-repo for `UdpLink` — this is the first network-socket code in the codebase; size `recvfrom`'s buffer generously per RESEARCH.md's stated pitfall (truncation is silent).

---

### `src/telemetry/ground/deframe.py`, `cli.py` (GND-01)

**Analog for `deframe.py`:** `src/telemetry/wire/decoder.py` (sibling module in the same package family — matching decode-side counterpart to `encoder.py`); read its error-handling shape (same `CfrError` family) before writing the COBS/CRC-then-CFR decode pipeline.

**Analog for `cli.py`:** `src/new_logger.py::main()` (lines 274–446) for the argparse + thread-wiring + signal-handler shape — but the ground CLI is a single-threaded loop per CONTEXT.md ("no asyncio in Phase 1"), so only the argparse/config-loading/signal-handling parts transfer, not the multi-thread orchestration. RESEARCH.md's own `run_ground_station()` sketch (lines 498–508+, continues past the truncated read) is the concrete reference to hand the planner.

---

### `requirements.txt` (OPS-06)

**Analog:** `requirements-dev.txt` (exact-pin style already established, e.g. `cantools==42.0.3`, `pytest==9.1.1`) — Phase 1's `requirements.txt` should use the identical `package==version` pin format, and per RESEARCH.md must also pin `mcap`'s transitive deps (`lz4==4.4.5`, `zstandard==0.25.0`) since `mcap` imports them unconditionally at module load even though Phase 1's writer never calls their compression path.

---

### `tests/test_logger_config.py` (OPS-05/06)

**Analog:** `tests/test_gate_config.py` (80 lines read in full) — copy its exact structure:
```python
@pytest.fixture()
def base_config_dict():
    """A mutable copy of the checked-in gate.json, for malformed-input tests
    that need to start from a known-good document and break exactly one
    thing."""
    with open(GateConfig.default_path(), "r", encoding="utf-8") as f:
        return json.load(f)

def _write_config(tmp_path, data):
    path = tmp_path / "gate.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path
```
Then: (1) a `test_default_config_loads_clean()` sanity test against the real checked-in file, (2) cross-consistency tests reading from the `dbc` session fixture rather than hardcoded literals (`test_every_dbc_ecu_node_appears_in_by_ecu`, lines 61–70), (3) one malformed-input test per validation branch, each built by mutating `base_config_dict` (never a hand-typed JSON literal), asserting `pytest.raises(LoggerConfigError)`. The docstring at the top of the file (lines 1–9) states *why*: "malformed-input cases build a mutated copy of it... so these tests fail loudly if the real file's shape ever drifts out from under them" — carry this same rationale into the new test file's docstring.

---

### `tests/conftest.py` — `logger_config` fixture addition

**Analog:** `tests/conftest.py::gate_config` (lines 47–53, full fixture read):
```python
@pytest.fixture(scope="session")
def gate_config() -> GateConfig:
    """The checked-in `config/gate.json`, loaded exactly once per test
    session via the typed loader (`src/telemetry/measure/config.py`) — the
    single source of every rate-model, entropy-bracket, and bus-target
    assumption a test needs, never duplicated as a literal in a test file."""
    return load_gate_config(GateConfig.default_path())
```
New `logger_config` fixture should be `scope="session"`, load `config/logger.json` via the new typed loader exactly once, with the same one-paragraph docstring explaining *why* (single source of truth, never duplicated as a literal). Follows the same `repo_root`/`dbc_path`/`dbc` session-scoped-fixture pattern already at the top of the file (lines 24–44) — `Path(__file__).parent.parent` resolution, never hardcoded absolute paths.

---

### Streaming/integration test files (`test_fanout.py`, `test_archive_writer.py`, `test_archive_crash_recovery.py`, `test_session.py`, `test_framing.py`, `test_link.py`, `test_end_to_end.py`, `test_soak.py`)

**Analog:** `tests/test_synth_stream.py` (generator/streaming shape) and `tests/test_wire_roundtrip.py` (encode→decode roundtrip shape) are the two closest existing test files by data flow — both were not read in full this pass (out of the 3–5-analog budget), but their names and role in the existing 127-test suite indicate the established idioms: session-scoped fixtures from `conftest.py`, `pytest.raises(SpecificError)` for negative cases, and reuse of `SyntheticFrameSource` as a deterministic load generator rather than hand-rolled fixtures — RESEARCH.md's Wave 0 list explicitly directs `test_soak.py` to "reuse `telemetry.synth.generator.SyntheticFrameSource` as the load source, driven through the real fan-out and writer rather than the measurement CLI," confirming this is the intended reuse point. `test_archive_crash_recovery.py` must carry an inline comment stating its own SIGKILL-vs-fsync scope limit per RESEARCH.md Pattern 4 (page-cache caveat) — no existing test in the suite has this shape, it is new.

## Shared Patterns

### Config idiom (applies to `config/logger.json` loader + `test_logger_config.py` + `conftest.py`)
**Source:** `src/telemetry/measure/config.py` (whole file) + `tests/test_gate_config.py` + `tests/conftest.py::gate_config`
Single idiom across the project: typed frozen-dataclass config, named `*ConfigError` exception, `default_path()` classmethod, fail-closed on unknown/missing keys, tested by mutating a copy of the real checked-in file. Do not invent a second config idiom for `logger.json` — CONTEXT.md is explicit about this.

### Thread lifecycle / shutdown signaling (applies to `capture/fanout.py`, `archive/writer.py`, `ground/cli.py`)
**Source:** `src/new_logger.py` lines 62 (`_STOP` sentinel), 178 (`threading.Event` polled), 329–332 (signal handlers wired before thread start), 335–346 (daemon capture / non-daemon writer)
Apply to every new thread-owning module: name threads for debugging, poll a shared `threading.Event`, use a sentinel object (not `None`) to signal queue drain-and-stop, daemon=True only for threads with no durability obligation, daemon=False for anything that must flush before exit.

### Exception-family shape (applies to `framing/`, `link/`, `archive/`)
**Source:** `src/telemetry/wire/encoder.py` lines 45–56 (`CfrError` / `BatchWindowExceeded` / `PayloadTooLong`)
One base exception per subsystem, specific subclasses for each distinct failure mode, always with a docstring one-liner explaining exactly when it's raised. Callers catch the base type when they just need to count-and-continue (LINK-02), or the specific subclass when they need to branch.

### Counters as shared mutable state (applies to `capture/fanout.py`, `archive/writer.py`)
**Source:** `src/new_logger.py` lines 170/219/268/322–323 (`hw_errors = [0]`, `frame_counter = [0]`, passed by reference into threads)
Phase 1's CAP-05/CAP-06 needs richer counters (discard counts, HWMs, per-frame error context) than a bare `list[int]` — use a small mutable dataclass or `threading`-safe counter object instead of the one-element-list hack, but keep the "pass a shared mutable object into the thread, read it from main after join" wiring pattern.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `src/telemetry/archive/writer.py` (mcap-specific parts) | service | file-I/O | First use of `mcap` in the codebase; no prior append-only-container writer exists. Use RESEARCH.md Pattern 2 verbatim. |
| `src/telemetry/archive/session.py` | service | file-I/O | No prior session-lifecycle/naming code exists. Use RESEARCH.md Pattern 3. |
| `src/telemetry/archive/reader.py` | utility | file-I/O | No prior crash-recovery reader exists. Use RESEARCH.md Pattern 2's `recover_crashed_session()`. |
| `src/telemetry/framing/cobs_frame.py`, `crc16.py` | utility | transform | First use of `cobs`/`crccheck`; only precedent is RESEARCH.md Pattern 6 (already-executed library calls, not in-repo code). |
| `src/telemetry/link/udp.py` | service | streaming | First network-socket code in the codebase. Use RESEARCH.md Pattern 7's `UdpLink`. |
| `tests/test_archive_crash_recovery.py` | test | file-I/O + process signal | No existing test simulates a process kill; the page-cache/fsync scope-limit caveat (RESEARCH.md Pattern 4) has no precedent either. |

## Anti-Patterns Flagged — do NOT copy from `src/new_logger.py` / `src/neoVI_logger.py`

1. **Bare/broad `except Exception` swallowing** (`new_logger.py` lines 183–187 stop-on-any-error with only `debug()`-level output; line 246–247 DBC decode silently swallows with `pass`; `neoVI_logger.py`'s general poll catch-all `except Exception as e: print(f"error: {e}")`). CAP-05/CAP-06 exist specifically to eliminate this — every new module must log with named error type + frame context, never silently continue or downgrade to debug-only output.
2. **Hardcoded transmit configuration and hardcoded arbitration IDs** (`new_logger.py` lines 145–161, 347–376: `transmit_can(device, 0x18f02a80, 8, 1, ...)` etc., duplicated thread name `"transmitter"` five times). Nothing in Phase 1 needs a transmit thread; if any test harness needs to inject frames, use `SyntheticFrameSource`/`replay_source.py`, not a copy of this pattern.
3. **Commented-out code left in place as "alternative approaches"** (`new_logger.py` lines 380–384, 386–402: five commented `.start()` calls and two commented calibration message blocks). Do not carry this practice into new modules — delete, don't comment out.
4. **Silent unknown-channel fallback with only a `[WARN]` log** (`new_logger.py::resolve_net_ids`, line 131). Phase 1's config-driven channel list should make an unresolvable channel name a hard `LoggerConfigError` at startup, not a runtime warning.
5. **CHANNEL_MAP/NET_ID_TO_NAME baked into source** (`new_logger.py` lines 41–59). Phase 1 must load this mapping from `config/logger.json`, per the locked "subset allowlist... never baked into code" decision — the same principle extends to the channel/net-ID map itself.

## Metadata

**Analog search scope:** `src/telemetry/` (wire/, synth/, measure/ packages), `src/new_logger.py`, `src/neoVI_logger.py`, `tests/` (all 9 files, `conftest.py` read in full; 5 of 9 test files read in full — `test_synth_stream.py` and `test_wire_roundtrip.py` referenced by name/role only, within the 3–5-analog stopping budget), `.planning/phases/00-.../config/gate.json` shape (via `config.py`), `requirements-dev.txt` (referenced, not re-quoted).
**Files scanned:** 3 fully-read runtime files (`config.py`, `frame_source.py`, `encoder.py` partial), `new_logger.py` (full, 447 lines), `conftest.py` (full), `test_gate_config.py` (80/? lines), `01-CONTEXT.md`, `01-RESEARCH.md` (first 725 of 725 lines paginated to line 508), `01-VALIDATION.md` (Wave 0 section).
**Pattern extraction date:** 2026-08-01
