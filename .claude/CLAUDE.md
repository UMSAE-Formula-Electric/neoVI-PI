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

- Python 3.x - Backend CAN logger and utility scripts (`src/`)
- JavaScript - Dashboard server and frontend display (`can-dashboard/`)
- HTML/CSS - Dashboard UI (`can-dashboard/dashboard.html`)

## Runtime

- Python 3.x - For CAN bus logging and data processing scripts
- Node.js 14+ - For real-time dashboard server and WebSocket communication
- pip (Python)
- npm (Node.js) - For WebSocket dependency
- Lockfile: Not present (minimal, single external npm dependency)

## Frameworks

- vspyx - Intrepid Control Systems neoVI SDK for Vehicle Spy X integration
- python-ics - Alternative python-ics library for neoVI Pi hardware interface
- cantools - DBC file parsing and CAN message decoding (`src/neoVI_logger.py`, `src/new_logger.py`)
- python-can - Python CAN bus interface library
- csv module (stdlib) - CSV logging format for data export
- json module (stdlib) - JSON interchange between Python logger and Node.js server
- Node.js http module (stdlib) - HTTP server for dashboard
- ws package - WebSocket server for real-time dashboard updates
- argparse (stdlib) - Command-line argument parsing for logger scripts

## Key Dependencies

- vspyx - Required for Vehicle Spy X integration and neoVI hardware communication. Used in `src/neoVI_logger.py` and `src/references.py`
- ics (python-ics) - Alternative/complementary library for neoVI Pi. Used in `src/new_logger.py`
- cantools - Essential for decoding CAN messages from DBC file (`epbr2026_DBC_v1.0.dbc`). Used across all logging scripts
- ws (WebSocket) - Required for dashboard real-time updates. Installed via `npm install` per `can-dashboard/README.md`
- python-can - Provides unified CAN bus interface across platforms

## Configuration

- Node.js PORT - Configurable via env var (defaults to 3000), specified in `can-dashboard/server.js` line 20
- Python debugging - Configured via `.vscode/launch.json` with debugpy
- No build pipeline - Scripts run directly (Python) or via Node.js
- Python loggers accept `--channels` and `--hardware_sn` CLI args for hardware selection
- Node.js server reads CAN data from stdin (piped from Python logger)

## Platform Requirements

- Python 3.x interpreter
- Node.js 14+ runtime
- neoVI Pi hardware or VSB buffer file for testing
- VS Code with Python extension (for debugging)
- Raspberry Pi (neoVI Pi target) or Linux/Windows with neoVI hardware
- Python 3.x
- Node.js 14+
- CAN bus hardware (neoVI Pi or compatible Intrepid device)

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- Python: `snake_case.py` (e.g., `neoVI_logger.py`, `new_logger.py`)
- JavaScript: `camelCase.js` or `snake_case.js` (e.g., `server.js`, `dashboard.html`)
- Use descriptive names indicating purpose (e.g., `neoVI_sender.py` for CAN sending, `simulate.js` for test data)
- **Python:** `snake_case` (e.g., `ensure_output_path()`, `attach_controllers()`, `build_dbc_index()`)
- **JavaScript:** `camelCase` (e.g., `buildChannelTabs()`, `renderSignalValue()`, `scheduleRender()`)
- Prefix helper functions or utilities with descriptive action verbs (e.g., `ensure_`, `build_`, `toggle_`, `render_`)
- **Python:** 
- **JavaScript:**
- **Python:** 
- **JavaScript:**
- **Python:** 
- **JavaScript:** 

## Code Style

- **Python:**
- **JavaScript:**
- **Python:**
- **JavaScript:**
- **Python:**
- **JavaScript:**

## Import Organization

- Not used in this codebase
- Relative paths used for file references (e.g., `path.join(__dirname, "dashboard.html")`)
- Absolute paths constructed from `Path(__file__).parent` in Python

## Error Handling

- Try/except blocks for device initialization (see `attach_controllers()` in `neoVI_logger.py`)
- RuntimeError for critical initialization failures with descriptive messages
- Assert statements for type validation (e.g., `assert isinstance(channel, vspyx.Communication.Channel)`)
- Generic exception catch-all for hardware polling: `except Exception as e: print(f"error: {e}")`
- Best-effort cleanup in `finally` blocks (see `main()` in `neoVI_logger.py`)
- Try/catch for JSON parsing (see `server.js` line 71-76)
- Fallback parsing when primary format fails (see `parseFallback()`)
- Connection error handling with automatic reconnection: `setTimeout(connect, 2000)`
- Graceful degradation with null checks: `state[channel]?.[id]?.signals?.[sig]`
- **Python:** `exit(1)` for errors, rely on process termination
- **JavaScript:** Process exits on errors or completion, connection loss triggers auto-reconnect

## Logging

- **Python:** Custom `log()` and `debug()` functions wrapping `print()` to stderr
- **JavaScript:** `console.log()` and `process.stderr.write()`
- **Python:**
- **JavaScript:**

## Comments

- Explain non-obvious logic (e.g., "Zero decoding, zero I/O here" in `new_logger.py` function docstring)
- Document architecture decisions (e.g., "Sentinel pushed onto queue" comment)
- Mark intentional workarounds: Commented-out code shows alternative approaches
- Explain "why" not "what" — the code shows "what" already
- TODO/FIXME patterns not observed; architecture uses comments instead
- **Python:** Module-level docstrings for primary entry points:
- **JavaScript:** File header comments with usage examples:

## Function Design

- Functions kept focused on single responsibility
- Typical range: 20-100 lines for utility functions
- Longer functions for main loops (e.g., `consumer_thread()` in `neoVI_logger.py` is ~25 lines but handles queue draining)
- Keep parameter count low: most functions take 3-5 parameters
- Use dictionaries/objects for related parameters (e.g., `msg = {"channel": "CAN0", "id": "0x123", ...}`)
- Optional parameters with defaults (e.g., `prefix=None` in `list_discovery_channels()`)
- Shared state passed by reference: lists for mutable counters (`frame_counter = [0]`), Events for signaling
- Explicit return types in Python type hints
- Functions return meaningful values or None on failure
- Early returns to reduce nesting (e.g., `if not isinstance(point, ...): return`)
- Sentinel values for special cases (e.g., `_STOP = object()` to signal thread termination)

## Module Design

- Python: Functions defined at module level, `if __name__ == "__main__":` pattern for entry points
- JavaScript: No explicit exports; single-purpose files (server, simulator, dashboard UI)
- Not used in this codebase
- Each module is standalone and importable
- **Python:** 
- **JavaScript:**
- Thread naming for debugging: `name="capture"`, `name="writer"`
- Daemon vs non-daemon threads: capture=daemon (background), writer=non-daemon (must finish)
- Shared state via queues: `raw_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)`
- Synchronization via Event: `stop_event = threading.Event()`
- Clean shutdown: signal handlers set `stop_event`, threads poll `stop_event.is_set()`

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

```text

```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| **Hardware Abstraction** | Connect to neoVI hardware, enumerate channels, manage device lifecycle | `src/neoVI_logger.py`, `src/new_logger.py` |
| **Capture Thread** | Poll CAN messages from hardware, queue raw frames with minimal overhead | `src/new_logger.py` (lines 164–211) |
| **Writer Thread** | Decode raw CAN frames using DBC database, write CSV rows and JSON stdout | `src/new_logger.py` (lines 214–268) |
| **Transmit Thread** | Send test CAN messages on specified bus at configured frequency | `src/new_logger.py` (lines 145–161) |
| **DBC Decoder** | Load and index DBC database for signal decoding and unit conversion | `src/new_logger.py` (lines 135–139, 294–304) |
| **Server (HTTP/WS)** | Serve dashboard UI, accept stdin CAN data, broadcast updates to clients | `can-dashboard/server.js` |
| **Dashboard UI** | Display live signals grouped by channel/message, handle filtering and visibility | `can-dashboard/dashboard.html` |
| **Simulator** | Generate synthetic CAN data for testing dashboard without hardware | `can-dashboard/simulate.js` |

## Pattern Overview

- **Multi-threaded capture**: Separate threads for hardware polling (high frequency), message decoding (CPU-bound), and file/socket I/O (I/O-bound)
- **Queue-based decoupling**: Raw frames passed through `queue.Queue` to separate capture from decode/write concerns
- **Loose coupling**: Python loggers pipe JSON to stdout; Node.js server consumes stdin independently
- **Real-time broadcast**: WebSocket allows many simultaneous viewers without polling
- **Stateless processing**: Each frame decoded independently; no frame correlation or state machines

## Layers

- Purpose: Connect to neoVI device, manage channels, handle device lifecycle
- Location: `src/new_logger.py` (lines 96–118), `src/neoVI_logger.py` (lines 40–90)
- Contains: Device initialization, channel enumeration, resolver patterns from vspyx SDK
- Depends on: `vspyx`, `ics` (python-ics)
- Used by: Capture thread to poll messages, Sender thread to transmit
- Purpose: High-frequency polling of raw CAN frames, network-ID filtering
- Location: `src/new_logger.py` (lines 164–211)
- Contains: `capture_thread()` function, channel mapping, raw tuple packing
- Depends on: Hardware abstraction (device, net_ids)
- Used by: Main thread signals capture thread; queue receives raw frames
- Purpose: Parse raw CAN bytes using DBC database, produce CSV rows and JSON
- Location: `src/new_logger.py` (lines 214–268)
- Contains: `writer_thread()`, DBC message lookup, CSV writer, JSON emit
- Depends on: DBC index, timestamp calculation
- Used by: File output (CSV), stdout (JSON), Node.js server (stdin)
- Purpose: Move formatted signals from Python logger to Node.js server
- Location: stdout (JSON lines) → stdin (server.js lines 64–100)
- Contains: newline-delimited JSON objects with channel, id, signal, value, unit
- Depends on: Python process stdout; Node.js stdin
- Used by: WebSocket broadcast layer
- Purpose: Maintain live state of all signals per channel/message
- Location: `can-dashboard/server.js` (lines 22–24, 85–88)
- Contains: `state[channel][msgId].signals[signalName] = { value, unit, ts }`
- Depends on: Transport (stdin updates), WebSocket broadcast
- Used by: Snapshot-on-connect (line 60), broadcast (line 90)
- Purpose: Distribute signal updates to all connected browsers in real-time
- Location: `can-dashboard/server.js` (lines 48–56, 90–99)
- Contains: `broadcast()` function, WebSocket message type routing
- Depends on: Server state (what to send), client connections
- Used by: Browser dashboard to receive updates
- Purpose: Render live signals grouped by channel and message, handle user interaction
- Location: `can-dashboard/dashboard.html`
- Contains: Channel tabs, message/signal toggles, search, range bars, status indicators
- Depends on: WebSocket (receive updates), browser DOM/CSS
- Used by: End users viewing CAN data

## Data Flow

### Primary Request Path (Hardware → Display)

- Python logger holds: DBC index, frame queue (transient)
- Server holds: `state[channel][msgId].signals` (in-memory, volatile)
- Browser holds: same state copy, DOM-synchronized

### Secondary Flow: Transmit (Python → Hardware)

### Tertiary Flow: Analysis/Debugging (Buffer → Signal Trace)

## Key Abstractions

- Purpose: Fast message ID → definition lookup without repeated database traversal
- Examples: `src/new_logger.py` lines 135–139, 304–312
- Pattern: Dictionary `{frame_id: cantools.Message}`
- Purpose: User-friendly channel names (e.g., "HSCAN2") ↔ ics NetworkID enums
- Examples: `src/new_logger.py` lines 41–59
- Pattern: Two-way dictionary mapping for CLI argument→hardware resolution
- Purpose: Minimal overhead passing of CAN frames between threads
- Structure: `(timestamp, arb_id, network_id, dlc, data_bytes)`
- Used in: `src/new_logger.py` lines 202–208, 238
- Purpose: Maintain live signals per channel/message for snapshot-on-connect and broadcast
- Structure: `state[channel][msgId] = { name, signals: {sigName: {value, unit, ts}} }`
- Used in: `can-dashboard/server.js` lines 22–24, 85–88

## Entry Points

- Location: `src/new_logger.py` lines 274–446
- Triggers: Command-line invocation with `--channels` argument
- Responsibilities:
- Location: `src/neoVI_logger.py` lines 92–223
- Triggers: Command-line invocation with `--channels` argument
- Responsibilities:
- Location: `src/neoVI_sender.py` lines 7–50
- Triggers: Command-line invocation with `--hardware_sn` and `--channels`
- Responsibilities:
- Location: `can-dashboard/server.js` lines 111–125
- Triggers: `node server.js` with stdin piped from logger
- Responsibilities:
- Location: `can-dashboard/dashboard.html`
- Triggers: Browser open of server URL
- Responsibilities:

## Architectural Constraints

- **Threading:** Python loggers use daemon threads for capture/transmit; non-daemon writer thread ensures file flush before exit. Node.js is single-threaded event loop with `readline` for blocking stdin.
- **Global state:** `src/new_logger.py` has module-level globals: `db` (DBC), `CHANNEL_MAP`, `NET_ID_TO_NAME`, `_STOP` sentinel. Server.js: `state` object holds all signal values in memory.
- **Circular imports:** None detected.
- **Pipe coupling:** Python logger output is ordered (timestamps monotonic per thread), but Node.js server must handle out-of-order updates or duplicates if multiple loggers pipe to same server.
- **Memory:** Server state grows with unique (channel, msgId, signal) tuples. No automatic cleanup; state persists until server restart.
- **Sampling:** Capture thread polls at configurable interval (default 10ms). Missed frames if capture falls behind—requires queue sizing tuning.

## Anti-Patterns

### Hardcoded Transmit Configuration

```python

```

### Frame Count Tracking via Mutable List Hack

```python

```

### Silent Fallback in DBC Decode

```python

```

### Duplicate Channel Name in Transmit Threads

```python

```

## Error Handling

- **Hardware errors:** Tracked in `hw_errors[0]` counter; logged at shutdown (line 442). Capture continues unless exception is caught and `stop_event` set (lines 184–186).
- **DBC decode errors:** Silent fallback with empty decoded field (line 247). Recommend: log first decode failure per message ID, then mute repeat errors.
- **I/O errors:** CSV write failures propagate (no catch). File closure is implicit on loop exit.
- **Device not found:** Raises `RuntimeError` with helpful message (lines 108–111). Caller must handle.
- **Queue full:** Logged and dropped frame (line 172). No backpressure; writer must keep up.
- **Cleanup:** Best-effort shutdown (lines 435–438): close device, join threads with timeout. Errors ignored.

## Cross-Cutting Concerns

- Python: `log()` to stderr (prefix `[LOG]`); `debug()` conditional on `DEBUGGING` flag. Stdout reserved for JSON output.
- Node.js: `console.log()` to stderr (lines 120–124); stdout only used for JSON piping.
- DBC file must exist at path (line 297). No validation of DBC against hardware.
- Channel names must map to known NetworkID (lines 121–133). Warn if unknown.
- Device serial/path must resolve (lines 107–111). Fail fast.
- None. Local hardware connection assumed. Network isolation is physical (local Wi-Fi).

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
