<!-- GSD:project-start source:PROJECT.md -->

## Project

**UMSAE neoVI PI Telemetry & Logging**

A telemetry and data-logging system for the UMSAE formula car, running on an Intrepid neoVI PI (Raspberry Pi CM4). It captures both vehicle CAN buses at full rate into a complete local archive on the onboard NVMe, and simultaneously streams the bus — compressed — over a low-bandwidth radio link to a laptop in the pit, where an engineer watches live plots and limit alarms while the car is on track.

It is used by the UMSAE team: the pit engineer during a run, and anyone doing post-session analysis afterward.

**Core Value:** The pit sees what the car is doing *while it is doing it*, and no run's data is ever lost.

### Constraints

- **Tech stack**: neoVI PI (Raspberry Pi CM4), python-ics / vspyx for hardware access, cantools for DBC decode, `epbr2026_DBC_v1.0.dbc` — the hardware SDK dictates Python on the car side.
- **Bandwidth**: ~200–250 kbit/s usable radio payload against ~4,000 frames/s of CAN. Compression is load-bearing, not an optimization.
- **Latency**: live view must be useful during a run — sub-second end to end.
- **Hardware availability**: the RFD900x is not purchased. Everything must be buildable, testable, and demonstrable with no radio present.
- **Timeline**: testing season is weeks away, not months. Every phase must leave something runnable on the car.
- **Environment**: vehicle vibration, −20 °C to +80 °C, and broadband RF noise from the inverter, HV cabling, and ignition. Abrupt power loss is a normal shutdown mode, not an exception.
- **Regulatory**: ISM 902–928 MHz, license-free under ISED in Canada.
- **Competition rules**: no antenna above the main roll hoop plane.

<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python 3.x only, end to end — the car-side logger, the ground station, and its browser dashboard's server are all one language now; no separate server-side JavaScript runtime exists anywhere in this repository.
- HTML/CSS/JS (inline, no build step) — the dashboard UI, `src/telemetry/ground/static/dashboard.html`, is a single self-contained file served over HTTP by the Python ground station.

## Runtime

- Python 3.12.10 — the pinned dev interpreter (native Windows CPython, per `STATE.md`); the deployment target is Linux on the Raspberry Pi CM4 (the neoVI PI).
- pip, driven by `requirements.txt` (exact `==` pins, each verified against the installed interpreter — never transcribed from prose).
- No JavaScript package manifest, no lockfile, and no build pipeline anywhere in the repository.

## Frameworks

- `cantools` — DBC parsing and CAN message decode/encode against `epbr2026_DBC_v1.0.dbc`, used throughout `src/telemetry/wire`, `src/telemetry/logger`, and `src/telemetry/ground`.
- `python-ics` — the sole neoVI hardware SDK this codebase imports (`src/telemetry/capture/hardware_source.py`). `vspyx` is never imported anywhere under `telemetry`, not even as a fallback — a bare `import vspyx` was measured to hang for a full 30s with no native driver present, and a "try the other SDK" branch would reintroduce that hang.
- `cobs` — COBS byte-stuffing for wire framing (LINK-01), `src/telemetry/framing/cobs_frame.py`.
- `crccheck` — CRC-16/CCITT-FALSE over each framed batch, `src/telemetry/framing/crc16.py`.
- `mcap` — the durable, crash-safe, append-only on-car archive format, `src/telemetry/archive/writer.py`/`reader.py`.
- `lz4`, `zstandard` — `mcap`'s transitive compression backends, pinned explicitly rather than left to resolve implicitly.
- stdlib `http.server` + Server-Sent Events — the dashboard's browser transport (`src/telemetry/ground/server.py`). Zero new runtime dependency: no `aiohttp`, nothing beyond the standard library.
- `pytest` — the test framework (`tests/`).
- `argparse` (stdlib) — CLI parsing for every entry point below.

## Key Dependencies

Exact pins live in `requirements.txt`; read that file rather than trusting this list if the two ever appear to disagree.

- `cantools==42.0.3` — DBC decode/encode, the one dependency every capture and decode path shares.
- `python-ics==1!26.3.9` (PEP 440 epoch 1) — neoVI hardware capture.
- `cobs==1.2.2` — wire-frame byte-stuffing.
- `crccheck==1.3.1` — the framing CRC.
- `mcap==1.4.0` — the archive format.
- `lz4==4.4.5`, `zstandard==0.25.0` — `mcap`'s compression backends.
- `pytest==9.1.1` — test runner.
- `requirements-dev.txt` is a deliberately unchanged, superseded Phase 0 record (two pins: `cantools`, `pytest`), kept only for provenance and cross-checked against `requirements.txt` for drift by a dedicated test — it is not a second source of truth to install from.

## Configuration

- `config/logger.json` — the one runtime config both the car and the ground station read: channels, capture cadence, archive path/sizing/flush cadence, telemetry queue sizing, the link kind (`loopback`/`udp`) and its settings, and the critical-channel allowlist. Parsed by a typed, fail-closed loader (`src/telemetry/logger/config.py`) that raises a named `LoggerConfigError` naming the offending key and value on any malformed input — it never silently defaults.
- `.planning/phases/00-compression-ratio-gate/config/gate.json` — Phase 0's own modelling-assumption config, loaded by the analogous `src/telemetry/measure/config.py`. Deliberately kept out of `config/`: it records a phase artifact's assumptions, not runtime configuration the car reads at boot.
- `epbr2026_DBC_v1.0.dbc` (repo root) — the single DBC every decode path resolves against.
- No environment variables configure anything. The dashboard's bind host/port are CLI flags (`--http-host`, default `127.0.0.1` loopback-only; `--http-port`, default `8080`) on `python -m telemetry.ground.cli --serve` — the server has no authentication of any kind, so binding a non-loopback address publishes live vehicle telemetry to everyone on that network.
- Python debugging — `.vscode/launch.json`, `debugpy`, launching `telemetry.logger.cli` as a module with `PYTHONPATH` set to `src/`.
- No build pipeline anywhere — every entry point runs directly via `python -m`.

## Platform Requirements

- Python 3.12 interpreter — native Windows CPython for local development, Linux (Raspberry Pi CM4) as the deployment target.
- neoVI PI hardware for a real capture run, or `--source synthetic` (backed by `src/telemetry/synth/generator.py`) / an archived-session replay source for fully hardware-free development and testing.
- No separate JavaScript runtime or package manager to install anywhere.
- VS Code with the Python extension, for `.vscode/launch.json`-based debugging (optional).

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- `snake_case.py` module files under `src/telemetry/<subpackage>/`, one concern per module (e.g., `wire/encoder.py`, `wire/decoder.py`, `archive/writer.py`, `archive/reader.py`).
- `snake_case` functions, prefixed with a descriptive action verb (`ensure_`, `build_`, `resolve_`, `load_`, `recover_`).
- `PascalCase` for dataclasses, Protocols, and named exceptions (`ArchiveWriter`, `FrameSource`, `LoggerConfigError`).
- Counters live on a frozen-field-free, mutable `@dataclass` per subsystem, always named `<Subsystem>Counters` (`FanOutCounters`, `DeframeCounters`, `GroundConsumerCounters`).

## Code Style

- Runtime settings are typed, `frozen=True` dataclasses (`LoggerConfig`, `ChannelConfig`, `TelemetryConfig`) built by one loader function per config file — never a bare `dict` passed around.
- Interchangeable implementations are declared as `typing.Protocol`s with the minimal method surface actually needed (`FrameSource`, `Link` — three methods each), not abstract base classes.
- Every module that logs gets its own `logger = logging.getLogger(__name__)` at module scope; no module configures logging itself except the CLI entry points.

## Import Organization

- Absolute imports rooted at the `telemetry` package (`from telemetry.wire.encoder import ...`), resolved via `pytest.ini`'s `pythonpath = src` for tests and `PYTHONPATH=src` for direct runs — never a relative import across subpackages.
- Repository-relative paths are always resolved from `Path(__file__).resolve()` walking up a fixed number of `.parent`s to the repo root, never a hardcoded absolute path (`src/telemetry/logger/config.py::_REPO_ROOT`, `tests/conftest.py::repo_root`, `tests/test_legacy_cutover.py::REPO_ROOT`).

## Error Handling

- **Catch the SDK's own exception type, never the builtin it shadows.** `ics.RuntimeError` is *not* a subclass of `builtins.RuntimeError` (verified directly against the installed SDK, not assumed from its name) — every hardware exception is caught via the injected SDK object's own attribute (`self._sdk.RuntimeError`), so a bare `except RuntimeError:` around a poll call would silently catch nothing on real hardware (`src/telemetry/capture/hardware_source.py`).
- **Name it, count it, never swallow it.** No bare `except Exception: pass` exists anywhere under `telemetry`. Every consumer-loop failure mode is caught by a specific exception type, incremented on that subsystem's counter dataclass, and logged once per `(frame_id, is_extended)` key with further repeats suppressed-and-counted rather than swallowed or re-logged per occurrence (`src/telemetry/capture/fanout.py::_record_telemetry_error`, `src/telemetry/ground/deframe.py`).
- **Two consumers, two deliberately different overflow policies.** The archive path never drops — a full archive queue is fatal by locked decision: logs critical, sets an overflow flag, sets the shared stop event, and the process halts rather than silently losing a frame. The telemetry path drops the oldest pending item and counts the drop; it is structurally incapable of blocking or crashing the archive path (CAP-03/CAP-04, `src/telemetry/capture/fanout.py`).
- **Fail-closed config loading.** `LoggerConfigError` / `GateConfigError` are raised, naming the offending key and value, on any missing, malformed, or internally inconsistent config — never a silent default (`src/telemetry/logger/config.py`, `src/telemetry/measure/config.py`).

## Logging

- `logging.getLogger(__name__)` per module, writing to stderr — reserved for humans.
- stdout is reserved exclusively for machine-readable output: newline-delimited JSON records (`telemetry.ground.cli`) or file artifacts (`telemetry.measure.cli`'s reports). Mixing the two would corrupt a piped consumer's input stream.

## Comments

- Module docstrings record empirically verified facts (SDK behaviour actually observed, library quirks actually measured against the installed version) rather than transcribed documentation prose — this project's single most repeated recorded failure mode is a prose figure disagreeing with measured reality.
- Docstrings explicitly flag a deliberate departure from a prior design ("this is unlike what the retired logger did, because...") so the reasoning survives even after the code it's contrasted against is gone. Several docstrings under `src/telemetry/**` and `tests/**` still cite the retired car-side loggers by name this way — that is intentional, not stale prose; those files remain fully readable in git history, and `tests/test_legacy_cutover.py` is the regression gate that keeps them out of the working tree while leaving this rationale text untouched.
- "Why", not "what" — the code already shows what.

## Function Design

- Functions kept focused on a single responsibility; longer functions are reserved for the main consumer/producer loops (`run_consumer_loop`, `feed_frames`), which stay linear rather than being fragmented for its own sake.
- Related parameters travel together as a dataclass, not a loose parameter list (`ChannelConfig`, `RawFrame`, `CapturedFrame`).
- Sentinel values signal special conditions across a thread boundary (`STOP = object()` pushed onto a queue to signal drain-and-stop).
- Early returns reduce nesting; functions return a meaningful value or raise a named exception, never `None` standing in for an error.

## Module Design

- One `if __name__ == "__main__":`-free entry point per process: `telemetry.logger.cli`, `telemetry.ground.cli`, `telemetry.ground.simulate`, `telemetry.measure.cli`, each with its own `main(argv=None)` and its own `_parse_args`, testable without a subprocess.
- Thread naming for debugging: `name="capture"`, `name="writer"`, `name="telemetry"`.
- Daemon vs. non-daemon is a deliberate choice, not a default: capture/telemetry threads are daemons (background, lossy-at-stop by design); the archive writer thread is non-daemon so a flush completes before the process exits.
- Shared state crosses a thread boundary only through a bounded `queue.Queue` / `collections.deque`, a `threading.Event` for shutdown, or a single `threading.Lock` guarding one dict — the specific exception is always named in that module's own docstring (`fanout.py`'s `_archive_hwm_lock`, `state.py`'s single `self._lock`).
- Clean shutdown: signal handlers set a shared `stop_event`; every loop polls `stop_event.is_set()` (or `.wait(timeout=...)`) rather than blocking forever.

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text
neoVI PI hardware (both CAN buses)
  -> telemetry.capture.hardware_source (one device handle, both buses)
  -> telemetry.capture.fanout.FanOut.submit()
       -> archive queue (never drops) -> telemetry.archive.runner.ArchiveRunner
            -> telemetry.archive.writer.ArchiveWriter -> session .mcap on NVMe
       -> telemetry queue (drop-oldest, counted) -> telemetry.logger.pipeline.TelemetryPipeline
            -> telemetry.wire.encoder (CFR) -> telemetry.wire.batcher
            -> telemetry.framing.cobs_frame (COBS+CRC-16) -> telemetry.link.{loopback,udp}.send()
                 ... the link (loopback / UDP now, RFD900x serial in Phase 9) ...
            -> telemetry.ground.deframe.Deframer.feed() -> telemetry.wire.decoder
            -> telemetry.ground.cli (decode against the DBC)
                 -> stdout / --output-file, one JSON record per line (always)
                 -> telemetry.ground.state.SignalState.update() (when --serve)
                      -> telemetry.ground.server.SseHub.broadcast() -> browser EventSource
                      -> telemetry.ground.static/dashboard.html
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| **Config Loading** | Typed, fail-closed parsing of `config/logger.json` — channels, archive, telemetry, link | `src/telemetry/logger/config.py` |
| **Hardware Capture** | One `python-ics` device handle, both configured buses, one tagged frame stream | `src/telemetry/capture/hardware_source.py` |
| **Fan-Out** | Splits captured frames to the archive queue (never drops) and the telemetry deque (drop-oldest, counted) | `src/telemetry/capture/fanout.py` |
| **Archive Writer / Runner / Session** | Durable, crash-safe MCAP archive on the onboard NVMe; batched flush cadence; `.done` marker only after a flushed close | `src/telemetry/archive/writer.py`, `runner.py`, `session.py` |
| **Archive Reader / Replay** | Recovers a session archive that may have crashed mid-write; replays it as a `FrameSource` for re-measurement | `src/telemetry/archive/reader.py`, `src/telemetry/capture/replay_source.py` |
| **Wire Encode / Decode** | The Compressed Frame Record (CFR) byte layout, per-CAN-ID delta state, the static DBC-derived ID dictionary | `src/telemetry/wire/encoder.py`, `decoder.py`, `dictionary.py` |
| **Batching & Framing** | Batch header assembly/disassembly; COBS byte-stuffing plus a CRC-16 trailer inside the COBS envelope | `src/telemetry/wire/batcher.py`, `src/telemetry/framing/cobs_frame.py`, `crc16.py` |
| **Link Transport** | The swappable `Link` Protocol — loopback (in-process), UDP (real network hop); a serial RFD900x implementation is Phase 9 | `src/telemetry/link/base.py`, `loopback.py`, `udp.py` |
| **Car-Side Entry Point** | Wires capture, fan-out, archive, and the telemetry pipeline into one process, driven entirely from config | `src/telemetry/logger/cli.py` |
| **Telemetry Pipeline** | Drains the telemetry queue on its own thread: batch, encode, frame, send | `src/telemetry/logger/pipeline.py` |
| **Ground Deframe** | Byte-stream-to-`RawFrame` recovery; every COBS/CRC/batch/CFR failure is caught by specific type, counted, and skipped — never fatal | `src/telemetry/ground/deframe.py` |
| **Ground-Station Entry Point** | Headless JSON output always; `--serve` additionally starts the dashboard server | `src/telemetry/ground/cli.py` |
| **Live Signal State** | In-memory current-value store, bounded by the DBC's own message count, guarded by one lock | `src/telemetry/ground/state.py` |
| **Dashboard Server** | Server-Sent Events broadcast plus static file serving over stdlib `http.server` | `src/telemetry/ground/server.py` |
| **Dashboard UI** | Channel tabs, search, per-message/per-signal visibility toggles, range bars, staleness dimming, auto-reconnect | `src/telemetry/ground/static/dashboard.html` |
| **Simulator** | Drives DBC-shaped synthetic traffic through the real encode/batch/frame/link path — no car, no hardware, no radio needed to demo the dashboard | `src/telemetry/ground/simulate.py` |
| **Synthetic Frame Source** | The full-bus synthetic generator both `--source synthetic` and the simulator drive | `src/telemetry/synth/generator.py`, `rates.py`, `entropy.py` |
| **Measurement Tooling** | Phase 0's offline compression-ratio gate: rate model, structural classification, per-ablation CFR round-trip, the report artifacts | `src/telemetry/measure/cli.py`, `classify.py`, `report.py`, `config.py` |

## Pattern Overview

- **Multi-threaded, single-responsibility-per-thread**: hardware polling, archive writing, and telemetry batching each run on their own named thread, gated by a shared `threading.Event`.
- **Structurally asymmetric fan-out**: one producer (`FanOut.submit`), two consumers with opposite overflow policies — the archive path is fatal-on-overflow (never drops), the telemetry path is drop-oldest-and-counted, and the telemetry side holds no handle that can ever block the archive side.
- **Typed, fail-closed configuration**: every runtime setting comes from one checked-in JSON file per config domain, parsed once by a loader that raises rather than defaults on anything malformed.
- **Server-Sent Events for one-way live push**: data flows server→browser only, so `EventSource`'s built-in reconnect is simpler than a bidirectional channel this system never needs — zero new runtime dependency.
- **Swappable transport, unchanged layers above it**: `FrameSource` and `Link` are both minimal `Protocol`s, so hardware/synthetic/replay sources and loopback/UDP/(future serial) links are interchangeable with no change to encode, batch, frame, or decode.
- **Counted, never-silent failure**: every discard, decode failure, or overflow increments a named field on a subsystem counter dataclass and is logged once per offending key, not swallowed and not re-logged per occurrence.

## Layers

**Hardware capture** — Purpose: one device handle, both buses, one tagged frame stream. Location: `src/telemetry/capture/hardware_source.py`. Depends on: `python-ics`, injected lazily so importing the module never touches the SDK. Used by: `telemetry.logger.cli --source hardware`.

**Fan-out** — Purpose: split one frame stream into the archive path (never drops) and the telemetry path (drop-oldest, counted), with no handle from one side into the other. Location: `src/telemetry/capture/fanout.py`. Depends on: hardware or synthetic `FrameSource`. Used by: `telemetry.logger.cli`.

**Durable archive** — Purpose: crash-safe, complete local record of every captured frame. Location: `src/telemetry/archive/writer.py` (own the file descriptor, `fsync` on the configured cadence), `runner.py` (the archive queue's consumer thread), `session.py` (naming and the `.done` marker), `reader.py` (footer-less/crashed-file recovery). Depends on: `mcap`. Used by: `telemetry.logger.cli`; read back by `telemetry.capture.replay_source` and post-session tooling.

**Wire protocol** — Purpose: turn a raw CAN frame into wire bytes and back, per-ID, reversibly. Location: `src/telemetry/wire/encoder.py`, `decoder.py`, `dictionary.py` (the static DBC-derived ID table), `batcher.py`, `frame_source.py`. Depends on: the DBC via `cantools`. Used by: both the car-side telemetry pipeline and the ground station's deframe/decode path.

**Framing** — Purpose: make a byte stream resynchronizable after corruption. Location: `src/telemetry/framing/cobs_frame.py` (COBS with the CRC-16 trailer placed *inside* the COBS envelope, not after it — a deliberate correction of the original sketch, since a trailer outside the envelope could itself contain the delimiter byte and split one frame into two), `crc16.py`. Used by: the telemetry pipeline (encode) and `telemetry.ground.deframe` (decode).

**Link transport** — Purpose: one three-method `Protocol` (`send`/`recv`/`close`) satisfied by every transport. Location: `src/telemetry/link/base.py`, `loopback.py`, `udp.py`. Used by: both `telemetry.logger.cli` and `telemetry.ground.cli`, symmetrically.

**Ground-station state and serving** — Purpose: hold current signal values and push them to browsers. Location: `src/telemetry/ground/state.py` (`state[channel][msg_id].signals[name] = {value, unit, ts}`, one lock, written only from the decode thread, read via `snapshot()` from HTTP handler threads), `server.py` (`SseHub`/`DashboardServer`). Used by: `telemetry.ground.cli --serve`; rendered by `static/dashboard.html`.

## Data Flow

### Primary Path (Car → Pit Display)

`telemetry.capture.hardware_source` (or `--source synthetic`) → `telemetry.capture.fanout.FanOut` → telemetry deque → `telemetry.logger.pipeline.TelemetryPipeline` → `telemetry.wire.encoder` → `telemetry.wire.batcher` → `telemetry.framing.cobs_frame` (COBS+CRC) → `telemetry.link.{loopback,udp}.send()` → the link → `telemetry.ground.deframe.Deframer.feed()` → `telemetry.wire.decoder` → `telemetry.ground.cli`'s record handler → `telemetry.ground.state.SignalState.update()` → `telemetry.ground.server.SseHub.broadcast()` → browser `EventSource` → `dashboard.html`. State holders: the ground station's `SignalState.state` dict (in-memory, bounded by the DBC's own message count — no eviction logic needed); the browser holds a DOM-synchronized copy seeded by a full snapshot on connect.

### Secondary Path (Durable Archive)

The same `FanOut.submit()` call also enqueues onto the archive queue, independent of and never blocked by the telemetry path above → `telemetry.archive.runner.ArchiveRunner` → `telemetry.archive.writer.ArchiveWriter` → a session `.mcap` file on the onboard NVMe, flushed on a batched record-count-or-time cadence, marked `.done` only after a flushed close.

### Tertiary Path (Headless Output / Offline Re-Analysis)

`telemetry.ground.cli` always emits one JSON record per line on stdout (and optionally `--output-file`) regardless of `--serve` — `tests/test_end_to_end.py`'s two-process, no-hardware, no-radio proof of the full car→pit chain depends on this staying true. Separately, `telemetry.archive.reader.recover_session` → `telemetry.capture.replay_source.ArchiveReplaySource` lets `telemetry.measure.cli` re-run the compression-ratio gate against real captured traffic instead of the synthetic model.

## Key Abstractions

- **`FrameSource` Protocol** (`src/telemetry/wire/frame_source.py`) — hardware, synthetic, and archive-replay sources are interchangeable; `RawFrame` (timestamp_us, frame_id, is_extended, payload) is the one raw-frame shape every layer above a source agrees on, and `CapturedFrame` (`src/telemetry/capture/fanout.py`) tags it with the channel it arrived on without touching the frozen `RawFrame` contract.
- **`Link` Protocol** (`src/telemetry/link/base.py`) — `send`/`recv`/`close`, nothing more; loopback, UDP, and a future serial RFD900x transport all satisfy it identically.
- **Static ID dictionary** (`src/telemetry/wire/dictionary.py`) — a versioned `(frame_id, is_extended) -> id_index` table derived once from the DBC, never adaptively learned from the live stream.
- **`SignalState`** (`src/telemetry/ground/state.py`) — `state[channel][msg_id].signals[name] = {value, unit, ts}`; structurally bounded by the DBC's message count, so it needs no TTL or eviction logic.
- **Per-subsystem counters** (`FanOutCounters`, `DeframeCounters`, `GroundConsumerCounters`) — every discard, drop, or decode failure is a named, incremented field, never a silent no-op.

## Entry Points

- `python -m telemetry.logger.cli` — the car-side process (`src/telemetry/logger/cli.py`); `--source hardware|synthetic`, `--link-kind`, `--archive-root`, `--duration-s`; driven from `config/logger.json` with CLI flags overriding individual fields.
- `python -m telemetry.ground.cli` — the ground-station process (`src/telemetry/ground/cli.py`); headless JSON output always; `--serve` additionally starts the dashboard on `--http-host`/`--http-port`.
- `python -m telemetry.ground.simulate` — a car stand-in (`src/telemetry/ground/simulate.py`) for demoing/testing the dashboard with no car, no neoVI hardware, and no radio present.
- `python -m telemetry.measure.cli` — the Phase 0 offline compression-ratio gate measurement tool (`src/telemetry/measure/cli.py`).

## Architectural Constraints

- **Threading:** capture and telemetry-pipeline threads are daemons (background, lossy-at-stop by design); the archive writer thread is non-daemon so a flush completes before the process exits. The ground station is a single-threaded receive/decode loop plus, when `--serve` is set, one HTTP handler thread per connected browser — no asyncio anywhere in this codebase, by locked decision.
- **Structurally asymmetric overflow:** `FanOut.submit` can only `put_nowait` onto the bounded archive queue (full is fatal — logs critical, sets an overflow flag, sets the stop event) or append to the bounded telemetry deque (drop-oldest, counted). The telemetry side holds no handle that can reach into or block the archive side (CAP-04).
- **Global state:** none beyond a per-module `logger = logging.getLogger(__name__)`. All mutable state lives on an instance, behind either an explicit lock (documented by name in that module's own docstring) or a single-writer-thread discipline.
- **Circular imports:** `telemetry.archive` depends on `telemetry.capture` (for `CapturedFrame`); `telemetry.capture` never imports anything back from `telemetry.archive`. That one-directional dependency is what makes "flushing never stalls capture" and "the telemetry consumer cannot backpressure the archive path" structural facts, not promises.
- **Config-driven, not code-driven:** every channel, archive setting, queue depth, flush cadence, and the live-path critical-channel allowlist come from `config/logger.json`, read by one typed loader shared by both processes — no source edit needed to change any of them.

## Anti-Patterns

### Catching the Builtin Exception Instead of the SDK's Own Type

```python
# Wrong -- ics.RuntimeError is NOT a subclass of builtins.RuntimeError,
# verified directly against the installed SDK. This catches nothing on
# real hardware.
try:
    messages, error_count = sdk.get_messages(device)
except RuntimeError as exc:
    ...

# Right (src/telemetry/capture/hardware_source.py) -- catch the SDK's own
# exception object, injected so it's testable without the real SDK too.
try:
    messages, error_count = self._sdk.get_messages(self.device)
except self._sdk.RuntimeError as exc:
    ...
```

### Swallowing an Error Instead of Naming and Counting It

```python
# Wrong -- silent, unbounded, and re-logs the same failure forever.
try:
    handle(record)
except Exception:
    pass

# Right (src/telemetry/capture/fanout.py) -- specific exception type,
# counted, logged once per offending key, repeats suppressed-and-counted.
except UnknownFrameId as exc:
    self._record_telemetry_error(captured, "telemetry_unknown_id_count", exc)
```

### Defaulting Instead of Raising on Malformed Config

```python
# Wrong -- a typo silently changes what the pit sees.
queue_depth = raw.get("telemetry", {}).get("queue_depth", 1000)

# Right (src/telemetry/logger/config.py) -- raise, naming the offending
# key and value.
_require_positive_int(value["queue_depth"], "telemetry.queue_depth")
```

## Error Handling

- **Hardware errors:** caught via the SDK's own `RuntimeError` type, logged critical with the poll iteration, counted on `poll_exception_count`, and the stop event is set — fatal, never swallowed (`src/telemetry/capture/hardware_source.py`).
- **Config errors:** `LoggerConfigError` / `GateConfigError`, raised naming the offending key and value, never defaulted (`src/telemetry/logger/config.py`, `src/telemetry/measure/config.py`).
- **Framing/decode errors on receive:** `CobsDecodeFailed`, `CrcMismatch`, `BatchFormatError`, `DecodeError` — each caught by specific type, counted on `DeframeCounters`, and the corrupt batch is discarded; no unhandled exception can reach or kill the consumer loop (`src/telemetry/ground/deframe.py`).
- **Archive overflow:** fatal by locked decision (the archive consumer never drops) — logs critical, sets an overflow flag, sets the stop event.
- **Telemetry overflow:** drop-oldest, counted, structurally incapable of blocking or crashing the archive path.
- **Cleanup:** a session's `.done` marker is written only after the archive is closed and flushed — a crash before that point leaves a recoverable, footer-less file that `telemetry.archive.reader.recover_session` is the one supported way to read back.

## Cross-Cutting Concerns

- **Logging:** every module gets its own `logging.getLogger(__name__)`, to stderr; stdout is reserved exclusively for machine-readable output (JSON records or report files). No module under `telemetry` configures logging itself except the CLI entry points.
- **Config validation:** `config/logger.json` and the Phase 0 `gate.json` are both validated eagerly, once, at process start, by a typed loader — nothing downstream re-reads or re-validates them independently.
- **Historical citations:** several module docstrings under `src/telemetry/**` and `tests/**` cite the retired car-side loggers by name as historical design rationale for a deliberate departure in the current implementation. This is intentional prose, not stale documentation — those files remain fully readable in git history, and `tests/test_legacy_cutover.py` is the regression gate that keeps them out of the working tree while leaving that rationale text alone.
- **Transport isolation:** the `Link` Protocol means the same encode/batch/frame pipeline runs unchanged over an in-process loopback, a UDP/local-network hop, or (Phase 9) a serial RFD900x radio — no layer above the link boundary needs to know which one is underneath.

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
