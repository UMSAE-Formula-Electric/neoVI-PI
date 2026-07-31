<!-- refreshed: 2026-07-30 -->
# Architecture

**Analysis Date:** 2026-07-30

## System Overview

```text
┌──────────────────────────────────────────────────────────┐
│           CAN Hardware Interface (neoVI-PI)              │
│              via vspyx / python-ics SDK                   │
└──────────────────────┬───────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
┌───────▼──────────────┐   ┌─────────▼──────────────┐
│   Python Loggers     │   │   Python Sender       │
│   `src/`             │   │   `src/`              │
│                      │   │                       │
│ • new_logger.py      │   │ • neoVI_sender.py     │
│ • neoVI_logger.py    │   │                       │
│ • references.py      │   │   Transmits CAN msgs  │
│                      │   │   on specified buses  │
│ Capture & decode     │   │                       │
│ CAN messages to CSV  │   │                       │
│ + JSON stream        │   │                       │
└───────┬──────────────┘   └───────────────────────┘
        │
        │ stdout (newline-delimited JSON)
        │
┌───────▼──────────────────────────────────────┐
│   Node.js Web Server                          │
│   `can-dashboard/server.js`                   │
│                                               │
│ • Listens on stdin for CAN signals            │
│ • HTTP server: serves dashboard.html          │
│ • WebSocket broadcasts signal updates         │
│ • Maintains state[channel][msgId].signals     │
└───────┬──────────────────────────────────────┘
        │
        │ WebSocket: JSON updates
        │
┌───────▼──────────────────────────────────────┐
│   Browser Dashboard                           │
│   `can-dashboard/dashboard.html`              │
│                                               │
│ • Real-time signal monitoring                 │
│ • Channel tabs & search filtering             │
│ • Message/signal visibility toggles           │
│ • Min/max range indicators                    │
│ • Auto-reconnect on server restart            │
└───────────────────────────────────────────────┘
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

**Overall:** Producer-Consumer with External Binding

**Key Characteristics:**
- **Multi-threaded capture**: Separate threads for hardware polling (high frequency), message decoding (CPU-bound), and file/socket I/O (I/O-bound)
- **Queue-based decoupling**: Raw frames passed through `queue.Queue` to separate capture from decode/write concerns
- **Loose coupling**: Python loggers pipe JSON to stdout; Node.js server consumes stdin independently
- **Real-time broadcast**: WebSocket allows many simultaneous viewers without polling
- **Stateless processing**: Each frame decoded independently; no frame correlation or state machines

## Layers

**Hardware Abstraction Layer:**
- Purpose: Connect to neoVI device, manage channels, handle device lifecycle
- Location: `src/new_logger.py` (lines 96–118), `src/neoVI_logger.py` (lines 40–90)
- Contains: Device initialization, channel enumeration, resolver patterns from vspyx SDK
- Depends on: `vspyx`, `ics` (python-ics)
- Used by: Capture thread to poll messages, Sender thread to transmit

**Capture & Filtering Layer:**
- Purpose: High-frequency polling of raw CAN frames, network-ID filtering
- Location: `src/new_logger.py` (lines 164–211)
- Contains: `capture_thread()` function, channel mapping, raw tuple packing
- Depends on: Hardware abstraction (device, net_ids)
- Used by: Main thread signals capture thread; queue receives raw frames

**Decode & Format Layer:**
- Purpose: Parse raw CAN bytes using DBC database, produce CSV rows and JSON
- Location: `src/new_logger.py` (lines 214–268)
- Contains: `writer_thread()`, DBC message lookup, CSV writer, JSON emit
- Depends on: DBC index, timestamp calculation
- Used by: File output (CSV), stdout (JSON), Node.js server (stdin)

**Transport Layer:**
- Purpose: Move formatted signals from Python logger to Node.js server
- Location: stdout (JSON lines) → stdin (server.js lines 64–100)
- Contains: newline-delimited JSON objects with channel, id, signal, value, unit
- Depends on: Python process stdout; Node.js stdin
- Used by: WebSocket broadcast layer

**Server State Layer:**
- Purpose: Maintain live state of all signals per channel/message
- Location: `can-dashboard/server.js` (lines 22–24, 85–88)
- Contains: `state[channel][msgId].signals[signalName] = { value, unit, ts }`
- Depends on: Transport (stdin updates), WebSocket broadcast
- Used by: Snapshot-on-connect (line 60), broadcast (line 90)

**WebSocket Broadcast Layer:**
- Purpose: Distribute signal updates to all connected browsers in real-time
- Location: `can-dashboard/server.js` (lines 48–56, 90–99)
- Contains: `broadcast()` function, WebSocket message type routing
- Depends on: Server state (what to send), client connections
- Used by: Browser dashboard to receive updates

**Dashboard Presentation Layer:**
- Purpose: Render live signals grouped by channel and message, handle user interaction
- Location: `can-dashboard/dashboard.html`
- Contains: Channel tabs, message/signal toggles, search, range bars, status indicators
- Depends on: WebSocket (receive updates), browser DOM/CSS
- Used by: End users viewing CAN data

## Data Flow

### Primary Request Path (Hardware → Display)

1. **Hardware poll** (`capture_thread`, `src/new_logger.py` line 182)
   - `ics.get_messages(device)` returns raw CAN frames
   - Frame tuple queued: `(timestamp, arb_id, network_id, dlc, data_bytes)`

2. **Decode & format** (`writer_thread`, `src/new_logger.py` lines 238–262)
   - Lookup message definition in DBC index by arb_id
   - Decode data bytes to signal values using `msg_def.decode(data)`
   - Emit JSON for each signal via `emit_signal()` (line 254)
   - Write CSV row for archival

3. **JSON emission** (`src/new_logger.py` lines 77–86)
   ```json
   {"channel": "MAIN", "id": "0x18f02a80", "name": "MessageName", "signal": "SignalName", "value": 42.5, "unit": "rpm", "timestamp": 1234567890.123}
   ```

4. **Server ingestion** (`can-dashboard/server.js` lines 66–100)
   - Server reads from stdin (piped from Python logger)
   - Parses JSON, updates state: `state[channel][id].signals[signal] = {value, unit, ts}`
   - Broadcasts update message to all WebSocket clients

5. **WebSocket delivery** (`can-dashboard/server.js` lines 90–99)
   ```json
   {"type": "update", "channel": "MAIN", "id": "0x18f02a80", "name": "MessageName", "signal": "SignalName", "value": 42.5, "unit": "rpm", "ts": 1234567890.123}
   ```

6. **Dashboard render** (`can-dashboard/dashboard.html`)
   - JavaScript receives update via `ws.onmessage`
   - Updates DOM: signal value text, range bar, timestamp
   - No database lookup or computation—just display update

**State Management:**
- Python logger holds: DBC index, frame queue (transient)
- Server holds: `state[channel][msgId].signals` (in-memory, volatile)
- Browser holds: same state copy, DOM-synchronized

### Secondary Flow: Transmit (Python → Hardware)

1. **Transmit thread** (`transmit_can()`, `src/new_logger.py` lines 145–161)
   - Constructs `ics.SpyMessage()` with arb_id, dlc, random data
   - Calls `ics.transmit_messages(device, msg)` at configured frequency

2. **Hardware transmission**
   - Device queues message on specified NetworkID (e.g., `NETID_HSCAN2`)
   - CAN bus broadcasts frame

3. **Loopback capture** (optional)
   - Transmitted frames may be captured by `capture_thread` if NetworkID matches filter
   - Closes the loop for testing

### Tertiary Flow: Analysis/Debugging (Buffer → Signal Trace)

`src/references.py` provides post-analysis:
1. Load VSB buffer file (`app.VehicleSpy.AddSource(buffer_path)`)
2. Attach controllers to channels
3. Subscribe to specific signals via resolver
4. Replay buffer through observers; print decoded values

## Key Abstractions

**DBC Index:**
- Purpose: Fast message ID → definition lookup without repeated database traversal
- Examples: `src/new_logger.py` lines 135–139, 304–312
- Pattern: Dictionary `{frame_id: cantools.Message}`

**Channel Map:**
- Purpose: User-friendly channel names (e.g., "HSCAN2") ↔ ics NetworkID enums
- Examples: `src/new_logger.py` lines 41–59
- Pattern: Two-way dictionary mapping for CLI argument→hardware resolution

**Raw Frame Tuple:**
- Purpose: Minimal overhead passing of CAN frames between threads
- Structure: `(timestamp, arb_id, network_id, dlc, data_bytes)`
- Used in: `src/new_logger.py` lines 202–208, 238

**State Dictionary:**
- Purpose: Maintain live signals per channel/message for snapshot-on-connect and broadcast
- Structure: `state[channel][msgId] = { name, signals: {sigName: {value, unit, ts}} }`
- Used in: `can-dashboard/server.js` lines 22–24, 85–88

## Entry Points

**`src/new_logger.py` (main):**
- Location: `src/new_logger.py` lines 274–446
- Triggers: Command-line invocation with `--channels` argument
- Responsibilities:
  - Parse CLI args (device serial, channels, output path, polling interval)
  - Load DBC database
  - Open device and resolve network IDs
  - Start capture and writer threads
  - Handle SIGINT/SIGTERM gracefully
  - Wait for duration or Ctrl+C; join threads; output summary stats

**`src/neoVI_logger.py` (main):**
- Location: `src/neoVI_logger.py` lines 92–223
- Triggers: Command-line invocation with `--channels` argument
- Responsibilities:
  - Initialize vspyx Application
  - Attach hardware controllers to specified channels
  - Set up on_point callback to queue raw frames
  - Log frames to VSB buffer file
  - Handle consumer thread for frame processing
  - Clean up on Ctrl+C

**`src/neoVI_sender.py` (main):**
- Location: `src/neoVI_sender.py` lines 7–50
- Triggers: Command-line invocation with `--hardware_sn` and `--channels`
- Responsibilities:
  - Initialize vspyx Application
  - Resolve channel
  - Create CAN bus interface via python-can
  - Send hardcoded test message in loop until Ctrl+C

**`can-dashboard/server.js` (listen):**
- Location: `can-dashboard/server.js` lines 111–125
- Triggers: `node server.js` with stdin piped from logger
- Responsibilities:
  - Bind HTTP server to `0.0.0.0:PORT`
  - Listen for WebSocket connections
  - Read stdin lines, parse JSON, update state
  - Serve dashboard.html on GET /
  - Return current state on GET /state (for snapshot-on-connect)
  - Broadcast updates to all connected clients

**`can-dashboard/dashboard.html` (window):**
- Location: `can-dashboard/dashboard.html`
- Triggers: Browser open of server URL
- Responsibilities:
  - Connect WebSocket to server
  - Subscribe to full state snapshot on connect
  - Handle incoming update/snapshot messages
  - Render channel tabs, messages, signals with visibility toggles
  - Implement search/filter, min/max range bars

## Architectural Constraints

- **Threading:** Python loggers use daemon threads for capture/transmit; non-daemon writer thread ensures file flush before exit. Node.js is single-threaded event loop with `readline` for blocking stdin.
- **Global state:** `src/new_logger.py` has module-level globals: `db` (DBC), `CHANNEL_MAP`, `NET_ID_TO_NAME`, `_STOP` sentinel. Server.js: `state` object holds all signal values in memory.
- **Circular imports:** None detected.
- **Pipe coupling:** Python logger output is ordered (timestamps monotonic per thread), but Node.js server must handle out-of-order updates or duplicates if multiple loggers pipe to same server.
- **Memory:** Server state grows with unique (channel, msgId, signal) tuples. No automatic cleanup; state persists until server restart.
- **Sampling:** Capture thread polls at configurable interval (default 10ms). Missed frames if capture falls behind—requires queue sizing tuning.

## Anti-Patterns

### Hardcoded Transmit Configuration

**What happens:** `src/new_logger.py` lines 347–376 create multiple transmit threads with hardcoded arbitration IDs and frequencies (e.g., `0x18f02a80 @ 1 fps`, `0xA7 @ 10 fps`).

**Why it's wrong:** Configuration is embedded in code. Changing transmit IDs, frequencies, or adding new signals requires code edits and restart. No way to configure per-run without editing source.

**Do this instead:** Move transmit config to JSON file or CLI args. Example:
```python
--transmit '[{"id": "0x18f02a80", "dlc": 8, "freq": 1}, {"id": "0xA7", "dlc": 8, "freq": 10}]'
```

### Frame Count Tracking via Mutable List Hack

**What happens:** `src/new_logger.py` lines 322–323 use `frame_counter = [0]` and `hw_errors = [0]` as mutable containers to share counters across threads.

**Why it's wrong:** Looks like a workaround; unclear intent. Thread-unsafe if multiple writers increment simultaneously (though GIL mitigates in practice). Harder to reason about than `threading.Lock()` or `queue.Queue`.

**Do this instead:** Use explicit thread-safe counter:
```python
import threading
frame_counter = 0
counter_lock = threading.Lock()
# In writer_thread:
with counter_lock:
    frame_counter += 1
```

### Silent Fallback in DBC Decode

**What happens:** `src/new_logger.py` lines 244–247 catch all exceptions during DBC decode and silently set `decoded = ""`.

**Why it's wrong:** Hides decode failures (bad data, malformed DBC, unknown message ID). User sees blank decoded field without knowing why.

**Do this instead:** Log decode errors with frame details:
```python
except Exception as e:
    log(f"[WARN] Failed to decode arb_id=0x{arb_id:08x}: {e}")
    decoded = {}
```

### Duplicate Channel Name in Transmit Threads

**What happens:** `src/new_logger.py` lines 347–376 create multiple transmit threads, all named `"transmitter"` (line 356–357, etc.). Commented-out `.start()` calls (lines 380–384) make it unclear which threads are active.

**Why it's wrong:** Hard to debug which transmit thread failed (no unique names in traceback). Commented code suggests incomplete refactoring.

**Do this instead:** Unique thread names and cleaner activation:
```python
threads = [
    ("transmitter_0x18f02a80", 0x18f02a80, 1),
    ("transmitter_0xa7", 0xA7, 10),
]
for name, msg_id, freq in threads:
    t = threading.Thread(target=transmit_can, args=(device, msg_id, 8, freq, stop_event), name=name, daemon=False)
    t.start()
```

## Error Handling

**Strategy:** Log errors to stderr; continue processing where safe; exit cleanly on critical failures.

**Patterns:**
- **Hardware errors:** Tracked in `hw_errors[0]` counter; logged at shutdown (line 442). Capture continues unless exception is caught and `stop_event` set (lines 184–186).
- **DBC decode errors:** Silent fallback with empty decoded field (line 247). Recommend: log first decode failure per message ID, then mute repeat errors.
- **I/O errors:** CSV write failures propagate (no catch). File closure is implicit on loop exit.
- **Device not found:** Raises `RuntimeError` with helpful message (lines 108–111). Caller must handle.
- **Queue full:** Logged and dropped frame (line 172). No backpressure; writer must keep up.
- **Cleanup:** Best-effort shutdown (lines 435–438): close device, join threads with timeout. Errors ignored.

## Cross-Cutting Concerns

**Logging:**
- Python: `log()` to stderr (prefix `[LOG]`); `debug()` conditional on `DEBUGGING` flag. Stdout reserved for JSON output.
- Node.js: `console.log()` to stderr (lines 120–124); stdout only used for JSON piping.

**Validation:**
- DBC file must exist at path (line 297). No validation of DBC against hardware.
- Channel names must map to known NetworkID (lines 121–133). Warn if unknown.
- Device serial/path must resolve (lines 107–111). Fail fast.

**Authentication:**
- None. Local hardware connection assumed. Network isolation is physical (local Wi-Fi).

---

*Architecture analysis: 2026-07-30*
