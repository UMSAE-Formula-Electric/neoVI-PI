# Phase 2: Python Ground Station and Dashboard Cutover - Pattern Map

**Mapped:** 2026-08-02
**Files analyzed:** 10 (create/modify) + 6 (delete)
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/telemetry/ground/state.py` | store | event-driven (locked mutable state + snapshot) | `src/telemetry/capture/fanout.py` (`FanOut`/`FanOutCounters`) | role-match (fan-out discipline, not identical shape) |
| `src/telemetry/ground/server.py` | controller (HTTP/SSE) | streaming (server→client push) | `src/telemetry/archive/runner.py` (`ArchiveRunner`, producer/consumer + STOP sentinel + stop_event) for the thread/shutdown half; RESEARCH.md's verified probe for the SSE mechanics themselves (no direct in-repo analog for `http.server`) | partial (thread discipline exact; HTTP/SSE mechanics have no in-repo analog) |
| `src/telemetry/ground/cli.py` (extended) | controller/CLI | request-response + streaming (composite `on_record`) | itself (existing `main()`/`on_record`/`_install_signal_handlers`) — extend in place | exact (same file, additive) |
| `src/telemetry/ground/simulate.py` | utility/CLI | batch/event-driven (feeds synthetic frames into the same decode pipeline) | `src/telemetry/logger/cli.py` (`--source synthetic` wiring, `SyntheticFrameSource` construction) | exact |
| `src/telemetry/ground/static/dashboard.html` | component (browser UI) | streaming (SSE client) | `can-dashboard/dashboard.html` | exact (port, not rewrite) |
| `config/logger.json` schema (no new file; reused) | config | — | `src/telemetry/logger/config.py` / `src/telemetry/measure/config.py` (typed fail-closed loader) — reference only, likely no new config file needed since serving-mode settings are CLI flags per Claude's Discretion | role-match |
| `tests/test_ground_server.py` | test | integration (SSE, no browser) | `tests/test_fanout.py` (direct in-process construction + assertions) + RESEARCH.md's bounded-`urlopen(timeout=...)` probe pattern | role-match |
| `tests/test_legacy_cutover.py` | test | static/grep-based | `tests/test_end_to_end.py`'s style (subprocess/filesystem assertions) — new pattern, simple `assert not path.exists()` + grep-for-imports | partial (no existing grep-style deletion test to copy verbatim; simple enough to write fresh) |
| `.claude/CLAUDE.md` | config/docs | — | itself — update Node server / legacy logger prose sections | exact |
| `.vscode/launch.json` | config | — | itself — update `args` to new CLI flags (RESEARCH.md Runtime State Inventory) | exact |

**Deletions (verify no imports before removing, per RESEARCH.md's grep-verified blast radius):**
`can-dashboard/` (whole dir: `server.js`, `simulate.js`, `README.md`, `dashboard.html` after porting), `src/neoVI_logger.py`, `src/new_logger.py`, `src/references.py`, `src/neoVI_sender.py`.

## Pattern Assignments

### `src/telemetry/ground/state.py` (store, event-driven)

**Analog:** `src/telemetry/capture/fanout.py`

**Module docstring / threading discipline convention** (lines 1-61, esp. 45-60):
```python
"""
Threading note: `FanOutCounters` is written only by the capture thread
that calls `submit()` and is read by other threads only after that
capture thread has stopped ... single-item `deque.append()` and
`Queue.put_nowait()` are each individually safe under the GIL ...

One field is the deliberate exception: `archive_high_water_mark` is a
read-modify-write ... performed from *two* threads ... guarded by
`FanOutCounters._archive_hwm_lock` — every other field keeps the
lock-free, single-writer discipline above.
"""
```
Apply this exact documentation discipline to `state.py`: state mutation happens only from the link-receive/decode thread inside `on_record`; the SSE handler threads only *read* a snapshot (copy) under a lock and register/deregister their own queue under a separate `clients_lock`. If any field is genuinely read-modify-write from two threads, name it explicitly and guard only that field — do not blanket-lock everything without saying why (mirror fanout.py's one-named-exception style, lines 52-60, 122-127).

**Counters dataclass pattern** (`FanOutCounters`, lines 87-127):
```python
@dataclass
class FanOutCounters:
    ...
    _archive_hwm_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )
```
Use this same dataclass-with-embedded-lock shape for any counters `state.py`/`server.py` need (e.g. `sse_clients_connected`, `sse_client_dropped_count` per RESEARCH.md Pattern 2) — `repr=False, compare=False` on the lock field keeps the dataclass a plain data holder for logging/tests, exactly as `fanout.py` does.

**Never-block / drop-oldest discipline** (`submit`, lines 154-198): the `was_full` check before `append`, and returning without raising, is the shape to copy for `push_dropping_oldest` (RESEARCH.md Pattern 2) — check fullness/attempt `put_nowait` first, count the drop, never let a slow consumer block the producer thread.

---

### `src/telemetry/ground/server.py` (controller, streaming)

**Analog (thread lifecycle half):** `src/telemetry/archive/runner.py`

**Producer/consumer + non-blocking poll + explicit STOP/shutdown discipline** (lines 46-99):
```python
STOP = object()

class ArchiveRunner:
    def __init__(self, ..., stop_event: threading.Event, poll_timeout_s=..., name=...):
        self.thread = threading.Thread(target=self._run, name=name, daemon=False)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._archive_queue.get(timeout=self._poll_timeout_s)
            except queue.Empty:
                continue
            ...
        self._drain_remaining()
```
Copy this shape for the SSE handler's per-client loop (`q.get(timeout=1.0)` / `queue.Empty` → heartbeat, per RESEARCH.md Pattern 1) and for the overall server lifecycle: name the thread, poll `stop_event`, never block forever.

**Cross-thread shutdown discipline** — this phase's `httpd.shutdown()` must be called from the link-receive/decode thread, never from the signal handler (RESEARCH.md Pattern 4/Pitfall 3). This is a NEW pattern not present in any existing file (existing threads only ever set `stop_event` and let their own loop notice it) — document it as prominently as `fanout.py`'s one lock exception is documented, since it's this module's one surprising exception to "just set stop_event and return."

**SSE mechanics (no in-repo analog — copy directly from RESEARCH.md's verified probe, § Code Examples):**
```python
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args): pass  # stderr logging convention: use `logger`, not default BaseHTTPRequestHandler stderr spam
    def do_GET(self):
        if self.path != "/events":
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = queue.Queue(maxsize=64)
        with clients_lock:
            clients.add(q)
        self.wfile.write(sse_frame("snapshot", state_snapshot()))
        try:
            while True:
                try:
                    chunk = q.get(timeout=1.0)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    continue
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionAbortedError, OSError):
            pass
        finally:
            with clients_lock:
                clients.discard(q)
```
Route allowlist per ASVS V5 (RESEARCH.md Security Domain): explicit `if self.path not in {"/", "/events"}` → 404, never a naive `os.path.join(static_dir, self.path)` filesystem walk. Never set `Content-Length` on `/events` (Pitfall 5). Always send `200 text/event-stream` unconditionally before anything that can fail (Pitfall 4).

**Error-handling convention to mirror from `fanout.py`/`runner.py`:** every failure caught by specific type, counted on a dataclass counter, logged once with rate-limiting for repeats (`_record_telemetry_error`, lines 234-255) — apply the same specific-except-then-count-then-log-once shape to SSE write failures rather than a bare `except Exception: pass`.

---

### `src/telemetry/ground/cli.py` (extended in place)

**Analog:** itself, lines 392-470 (`main()`), 264-269 (`_emit_record`), 439-441 (`on_record` closure)

**Composite `on_record`, exact target shape (RESEARCH.md Pattern 3, confirmed against real file lines 439-441):**
```python
def on_record(**fields) -> None:
    _emit_record(sys.stdout, output_file, **fields)
```
Grows to:
```python
def on_record(**fields) -> None:
    _emit_record(sys.stdout, output_file, **fields)      # unchanged, GND output survives
    signal_state.update(**fields)                          # NEW
    sse_hub.broadcast(...)                                  # NEW
```
Zero changes needed to `run_consumer_loop`'s signature (lines 334-345) or `_decode_and_emit`'s call sites (lines 295-331) — only this closure in `main()` grows, exactly as RESEARCH.md prescribes.

**Argparse pattern to extend** (lines 111-171): add a `--serve` (or discretion-chosen name) flag, an `--http-host`/`--http-port` pair, following the existing `parser.add_argument(..., help=...)` style already used for `--output-file`, `--duration-s`, etc.

**Signal-handler-before-resources ordering** (lines 392-397, `_install_signal_handlers(stop_event)` called immediately after `stop_event = threading.Event()`, before config load) — preserve this ordering exactly when adding HTTP server construction; the server must not be built before signal handlers are installed.

**`_json_default` / choice-decoded-enum handling** (lines 256-261) — reuse verbatim for any JSON serialization inside `state.py`/`server.py` (the SSE payload will hit the same `NamedSignalValue` issue).

---

### `src/telemetry/ground/simulate.py` (utility/CLI)

**Analog:** `src/telemetry/logger/cli.py`, `--source synthetic` wiring

**Synthetic source construction pattern** (`logger/cli.py` imports, lines 86-88, and its module docstring lines 18-27):
```python
from telemetry.measure.config import GateConfig, GateConfigError, load_gate_config
from telemetry.synth.entropy import BRACKET_NAMES
from telemetry.synth.generator import SyntheticFrameSource
```
`SyntheticFrameSource` construction (from `src/telemetry/synth/generator.py`, lines 38-65):
```python
SyntheticFrameSource(
    db, dictionary, config, bracket_name,
    duration_s=..., only_message_names=...,
)
```
then iterate `.frames()` (line 75) to get `RawFrame`s. For `simulate.py`, drive these frames directly into the ground station's own decode path (or into a loopback `Link`) rather than reinventing per-signal random-walk generation the way `can-dashboard/simulate.js` did (lines 30-40 of that file — explicitly NOT to be reproduced; `SyntheticFrameSource`'s `PayloadMutator`/entropy-bracket model replaces it).

**CLI shape to copy:** `logger/cli.py`'s `_configure_logging`, `_install_signal_handlers`, `_parse_args` functions (lines 99-171 range) — same argparse/logging/signal conventions, scaled down since `simulate.py` has no archive/link/fan-out machinery, just a frame producer.

---

### `src/telemetry/ground/static/dashboard.html` (component, streaming)

**Analog:** `can-dashboard/dashboard.html` (734 lines) — port target, not rewrite, per locked decision.

**Only the transport client changes.** WebSocket block to replace (lines 415-441 of `can-dashboard/dashboard.html`):
```javascript
// WebSocket
let ws, reconnectTimer;
function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => { setStatus('live', 'Live'); clearTimeout(reconnectTimer); };
  ws.onclose = () => { setStatus('error', 'Reconnecting…'); reconnectTimer = setTimeout(connect, 2000); };
  ws.onerror = () => setStatus('error', 'Error');
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'snapshot') { state = msg.state; rebuildAll(); }
    else if (msg.type === 'update') { handleUpdate(msg); }
  };
}
```
Becomes (per RESEARCH.md Open Question 1's recommendation — generic `message` event, `type` field inside JSON, minimal diff):
```javascript
let es;
function connect() {
  es = new EventSource('/events');
  es.onopen = () => setStatus('live', 'Live');
  es.onerror = () => setStatus('error', 'Reconnecting…');   // EventSource auto-retries; no setTimeout/reconnectTimer needed
  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'snapshot') { state = msg.state; rebuildAll(); }
    else if (msg.type === 'update') { handleUpdate(msg); }
  };
}
```
Delete `reconnectTimer`/`setTimeout(connect, 2000)` entirely — `EventSource` supplies this per the locked decision. `handleUpdate` (lines 449-468), `rebuildAll` (lines 471-478), `renderSignalValue`/`scheduleRender`/`flushUpdates` (lines 400-413), and every DOM/CSS/toggle/search/tab function elsewhere in the file are untouched — only this ~25-line block changes.

**New this-phase addition — staleness dimming** (per 02-UI-SPEC.md "Additional copy element — per-signal staleness" and Color section): add a `--dim` (`#55555f`) text-color rule keyed off `Date.now() - ts > 3000`, applied inside the existing render path (`renderSignalValue`/`scheduleRender`, same function that already reads `state[...].signals[...].ts`) — do not introduce a new polling loop; recompute staleness at the same `requestAnimationFrame` cadence `scheduleRender`/`flushUpdates` already use (lines 400-413).

**Empty-state copy replacement** (per 02-UI-SPEC.md Copywriting Contract): the current `node server.js` instruction text must be replaced with the literal chosen serving-mode invocation, e.g. `python -m telemetry.ground.cli --serve` — resolve the `{SERVING_FLAG}` placeholder to whatever flag name Task/plan for `cli.py` actually picks; do not ship the literal placeholder string.

---

### `tests/test_ground_server.py` (test, integration)

**Analog:** `tests/test_fanout.py` (direct in-process construction, no subprocess) + RESEARCH.md's bounded-`urlopen` probe.

**In-process construction/assertion style** (lines 1-46 of `test_fanout.py`):
```python
def _make_frame(frame_id, is_extended=False, payload=b"\x01", timestamp_us=0):
    return RawFrame(...)

def test_discard_counting():
    stop_event = threading.Event()
    allowlist = frozenset({(0x100, False)})
    fan_out = FanOut(archive_maxsize=1000, telemetry_maxsize=4, ...)
    for i in range(20):
        fan_out.submit(CapturedFrame(channel=CHANNEL_A, frame=_make_frame(0x100, timestamp_us=i)))
```
Mirror this for `state.py`/`server.py`: construct real objects in-process (a real `ThreadingHTTPServer` on `127.0.0.1:0`, an ephemeral port), no mocks, small literal bound values (queue depths, timeouts) never taken from `config/logger.json` — "so a config tune can never change what an assertion here means" (`test_fanout.py` line 15-16 docstring rationale).

**Bounded-read pattern (from RESEARCH.md § Code Examples, verified live this session):**
```python
resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=1.0)
line1 = resp.readline()   # returns immediately with buffered bytes
line2 = resp.readline()
line3 = resp.readline()   # blank line terminating the SSE frame
try:
    resp.readline()        # blocks up to 1.0s, then...
except TimeoutError:
    pass                    # ...raises real TimeoutError -- confirmed
```
Use this exact bounded-`urlopen(timeout=...)` idiom for GND-04/GND-05 assertions — never loop unconditionally on `readline()` with no deadline (RESEARCH.md explicit warning).

---

### `tests/test_legacy_cutover.py` (test, static/grep-based)

**No direct analog exists in-repo for a deletion-verification test.** Write fresh, simple:
```python
def test_can_dashboard_dir_removed():
    assert not (REPO_ROOT / "can-dashboard").exists()

def test_legacy_loggers_removed_and_unreferenced():
    for name in ("neoVI_logger.py", "new_logger.py", "references.py", "neoVI_sender.py"):
        assert not (REPO_ROOT / "src" / name).exists()
    # grep src/ and tests/ for stray imports, mirroring RESEARCH.md's own
    # Deletion Blast Radius audit methodology (grep for `import`/`from`
    # referencing these module names, expect zero hits)
```
`REPO_ROOT` resolution: mirror `telemetry.logger.config._REPO_ROOT`'s convention (`config.py` lines 84-86): `Path(__file__).resolve().parents[N]`, never a hardcoded absolute path.

## Shared Patterns

### Thread discipline (name threads, poll `stop_event`, non-daemon where flush must complete)
**Source:** `src/telemetry/archive/runner.py` lines 46-99, `src/telemetry/capture/fanout.py` lines 45-60
**Apply to:** `server.py`'s SSE handler loop, the link-receive/decode thread's shutdown addition, `simulate.py` if it runs its own thread.

### Typed, fail-closed config loading
**Source:** `src/telemetry/logger/config.py` (`_diff_keys`, `LoggerConfigError`, `load_logger_config`, lines 206-219, 371-438)
**Apply to:** only if this phase introduces a new config surface beyond CLI flags (Claude's Discretion leaves flag names/route layout open) — if a `config/ground.json` or similar is added, it MUST mirror this exact `_diff_keys`/required-key-set/raise-never-default shape, not invent a new idiom.

### Structured logging to stderr; stdout reserved for JSON
**Source:** `src/telemetry/ground/cli.py` lines 94-99 (`_configure_logging`), module docstring lines 49-56
**Apply to:** `server.py`, `state.py`, `simulate.py` — never `print()` for diagnostics; `logger = logging.getLogger(__name__)` + `logger.warning/info/critical`, exactly as every existing `telemetry.*` module does. `BaseHTTPRequestHandler.log_message` must be overridden to route through this `logger`, not left as default (which writes directly to stderr uncontrolled).

### Specific-exception-type + counter + rate-limited-log-once
**Source:** `src/telemetry/capture/fanout.py` `_passes_telemetry_precheck`/`_record_telemetry_error` (lines 200-255), `src/telemetry/ground/cli.py` `_decode_and_emit` (lines 295-319)
**Apply to:** SSE write failures in `server.py`, DBC-channel-lookup misses if any occur in `state.py` — catch specific exception types (`BrokenPipeError`, `ConnectionAbortedError`, `OSError`), count on a dataclass field, log once per key with `..._log_suppressed_count` for repeats. Never a bare `except Exception: pass`.

### Message-name → channel resolution, computed once at startup
**Source:** `tests/test_end_to_end.py` lines 792-804 (exact reusable snippet):
```python
from telemetry.measure.config import GateConfig, load_gate_config
from telemetry.synth.rates import assign_rates

gate_config = load_gate_config(GateConfig.default_path())
name_to_bus = {r.name: r.bus for r in assign_rates(dbc, gate_config)}
bus_to_channel = {c.bus: c.name for c in logger_config.channels}
```
**Apply to:** `cli.py`'s `main()`, computed once before `run_consumer_loop` starts, passed into (or closed over by) `on_record` so `state.py`'s `update()` can resolve `channel` per record without a per-frame computation (Pitfall 2).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/telemetry/ground/server.py` (SSE/`http.server` mechanics specifically) | controller | streaming | No prior module in this codebase serves HTTP or SSE — Phase 1 is entirely batch/stream-to-file/stream-to-link, never stream-to-browser. RESEARCH.md's own verified probe script (§ Code Examples) is the only source; treat it as the analog in place of an in-repo file. |
| `tests/test_legacy_cutover.py` | test | static/grep-based | No existing test in this repo verifies file deletion/absence of imports; write fresh using `Path.exists()` + grep, following RESEARCH.md's own audit methodology as the model rather than a prior test file. |

## Metadata

**Analog search scope:** `src/telemetry/**`, `can-dashboard/`, `tests/*.py`, `.claude/CLAUDE.md`, `.vscode/launch.json`
**Files scanned:** `fanout.py`, `archive/runner.py`, `ground/cli.py`, `logger/cli.py`, `logger/config.py`, `synth/generator.py`, `can-dashboard/server.js`, `can-dashboard/simulate.js`, `can-dashboard/dashboard.html`, `tests/test_fanout.py`, `tests/test_end_to_end.py` (targeted grep)
**Pattern extraction date:** 2026-08-02
