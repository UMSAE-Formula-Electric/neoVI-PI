# Coding Conventions

**Analysis Date:** 2026-07-30

## Naming Patterns

**Files:**
- Python: `snake_case.py` (e.g., `neoVI_logger.py`, `new_logger.py`)
- JavaScript: `camelCase.js` or `snake_case.js` (e.g., `server.js`, `dashboard.html`)
- Use descriptive names indicating purpose (e.g., `neoVI_sender.py` for CAN sending, `simulate.js` for test data)

**Functions:**
- **Python:** `snake_case` (e.g., `ensure_output_path()`, `attach_controllers()`, `build_dbc_index()`)
- **JavaScript:** `camelCase` (e.g., `buildChannelTabs()`, `renderSignalValue()`, `scheduleRender()`)
- Prefix helper functions or utilities with descriptive action verbs (e.g., `ensure_`, `build_`, `toggle_`, `render_`)

**Variables:**
- **Python:** 
  - `snake_case` for general variables (e.g., `output_path`, `frame_count`, `stop_event`)
  - Single letter for loop iterators when in tight scopes (e.g., `for ch in channels:`, `for c in args.channels:`)
  - Underscores for unused variables (e.g., `except Exception as e:` when error not used becomes `except Exception:`)
- **JavaScript:**
  - `camelCase` for general variables (e.g., `msgCount`, `activeChannel`, `visibilityMsg`)
  - Abbreviated keys for maps/dicts (e.g., `sigKey = ch + '|' + id + '|' + sig`, `groupKey = ch + '|' + id`)
  - Prefixed state objects for domain clarity (e.g., `visibilityMsg`, `visibilitySig`, `collapsed`, `signalMins`)

**Types/Classes:**
- **Python:** 
  - Type hints in function signatures (e.g., `def attach_controllers(app:"vspyx.Core.Application", channels: List[str], listen_only:bool=True)`)
  - Union types for optional returns (e.g., `-> dict[int, object] | None`)
- **JavaScript:**
  - JSDoc comments for complex types (e.g., `// Structure: state[channel][messageId] = { name, signals: { signalName: { value, unit, ts } } }`)

**Constants:**
- **Python:** 
  - UPPERCASE_WITH_UNDERSCORES (e.g., `TESTING_MODE`, `QUEUE_MAXSIZE`, `DBC_FILE`)
  - Module-level constants at top (e.g., `DEFAULT_OUTPUT_DIR`, `CHANNEL_MAP`)
  - `_STOP = object()` for sentinel values
- **JavaScript:** 
  - UPPERCASE for config values (e.g., `PORT = process.env.PORT || 3000`)
  - Descriptive uppercase for magic numbers where appropriate

## Code Style

**Formatting:**
- **Python:**
  - 4-space indentation (standard Python)
  - Line length: no strict limit observed, but kept under 120 characters in most cases
  - Space around operators: `result = x + y` not `result=x+y`
  - No semicolons (Python convention)
- **JavaScript:**
  - 2-space or variable indentation observed in dashboard.html
  - Space around operators: `let x = 1;`
  - Semicolons used at end of statements
  - Trailing semicolons on object literals

**Comments:**
- **Python:**
  - `#` for single-line comments, typically inline or above code
  - Multi-line comments use `"""` for module docstrings
  - Section dividers: `# ---` followed by descriptive text (e.g., `# --- Helpers`)
  - Comment explains "why" not "what" (e.g., `# Sentinel pushed onto queue to tell writer_thread to exit cleanly`)
- **JavaScript:**
  - `//` for single-line comments
  - `/** ... */` for JSDoc file headers (e.g., in `server.js`, `simulate.js`)
  - Comments above code blocks explaining logic
  - Code sections marked with `// --- Section Name ---`

**Logging:**
- **Python:**
  - Custom logging functions in `new_logger.py`: `log()` for info, `debug()` for debug-level
  - `print()` statements for simple output
  - Logging prefixes: `[LOG]`, `[DEBUG]`, `[WARN]`, `[tx error]`, `[capture]`, `[stats]`
  - Conditional debug output: `if DEBUGGING: print(...)`
  - Logging to stderr for structured output (`sys.stderr.write()`, `print(..., file=sys.stderr)`)
- **JavaScript:**
  - `console.log()` and `console.error()` for logging
  - Structured messages with emojis in user-facing output (e.g., `console.log('🚗  CAN Dashboard running')`)
  - Error messages to stderr (`process.stderr.write()`)

## Import Organization

**Order (Python):**
1. Standard library imports (e.g., `import time`, `import argparse`, `from pathlib import Path`)
2. Third-party library imports (e.g., `import vspyx`, `import cantools`, `import ics`)
3. Typing imports (e.g., `from typing import List, Tuple, Optional`)
4. Local module imports (rarely used, not observed in this codebase)

Example from `neoVI_logger.py`:
```python
import vspyx
import argparse
import time
import can
import cantools
from typing import List,Tuple,Optional
from datetime import datetime
from pathlib import Path
import queue
import threading
```

**Order (JavaScript):**
1. Built-in Node.js modules: `require()` calls
2. Local imports (not observed in this codebase)
3. Script execution code (callbacks, listeners)

Example from `server.js`:
```javascript
const http = require("http");
const fs = require("fs");
const path = require("path");
const { WebSocketServer } = require("ws");
const readline = require("readline");
```

**Path Aliases:**
- Not used in this codebase
- Relative paths used for file references (e.g., `path.join(__dirname, "dashboard.html")`)
- Absolute paths constructed from `Path(__file__).parent` in Python

## Error Handling

**Patterns (Python):**
- Try/except blocks for device initialization (see `attach_controllers()` in `neoVI_logger.py`)
- RuntimeError for critical initialization failures with descriptive messages
- Assert statements for type validation (e.g., `assert isinstance(channel, vspyx.Communication.Channel)`)
- Generic exception catch-all for hardware polling: `except Exception as e: print(f"error: {e}")`
- Best-effort cleanup in `finally` blocks (see `main()` in `neoVI_logger.py`)

**Patterns (JavaScript):**
- Try/catch for JSON parsing (see `server.js` line 71-76)
- Fallback parsing when primary format fails (see `parseFallback()`)
- Connection error handling with automatic reconnection: `setTimeout(connect, 2000)`
- Graceful degradation with null checks: `state[channel]?.[id]?.signals?.[sig]`

**Exit Strategy:**
- **Python:** `exit(1)` for errors, rely on process termination
- **JavaScript:** Process exits on errors or completion, connection loss triggers auto-reconnect

## Logging

**Framework:** 
- **Python:** Custom `log()` and `debug()` functions wrapping `print()` to stderr
- **JavaScript:** `console.log()` and `process.stderr.write()`

**Patterns:**
- **Python:**
  - Info messages via `log()` function output to stderr
  - Debug messages controlled by `DEBUGGING` global flag
  - Status messages with prefixes: `[LOG]`, `[DEBUG]`, `[WARN]`, `[stats]`
  - Signal decoding output: `print(f"{id} - {sig}:{decoded[sig]:.2f}")`
  - Example: `log(f"Opened: {device}  (serial {device.SerialNumber})")`
- **JavaScript:**
  - Server startup messages: `console.log('CAN Dashboard running')`
  - Line-by-line output: `process.stdout.write(JSON.stringify(msg) + "\n")`
  - Status to stderr: `process.stderr.write("CAN simulator running…\n")`

## Comments

**When to Comment:**
- Explain non-obvious logic (e.g., "Zero decoding, zero I/O here" in `new_logger.py` function docstring)
- Document architecture decisions (e.g., "Sentinel pushed onto queue" comment)
- Mark intentional workarounds: Commented-out code shows alternative approaches
- Explain "why" not "what" — the code shows "what" already
- TODO/FIXME patterns not observed; architecture uses comments instead

**JSDoc/TSDoc:**
- **Python:** Module-level docstrings for primary entry points:
  ```python
  """
  neoVI Pi CAN logger — python-ics edition
  No Vehicle Spy X license required.
  
  Output: timestamped CSV (timestamp_s, arb_id_hex, network_id, dlc, data_hex, decoded)
  
  Architecture:
    capture_thread  — polls ics.get_messages() as fast as possible...
    writer_thread   — drains the queue, decodes with cantools...
    main thread     — handles timing, stats, and shutdown signalling.
  """
  ```
- **JavaScript:** File header comments with usage examples:
  ```javascript
  /**
   * CAN Bus Live Dashboard — Server
   *
   * Pipe your CAN logger output to stdin in newline-delimited JSON:
   *   node server.js < can_log.jsonl
   *
   * Expected JSON format (one object per line):
   *   { "channel": "CAN0", "id": "0x123", ... }
   */
  ```

## Function Design

**Size:** 
- Functions kept focused on single responsibility
- Typical range: 20-100 lines for utility functions
- Longer functions for main loops (e.g., `consumer_thread()` in `neoVI_logger.py` is ~25 lines but handles queue draining)

**Parameters:**
- Keep parameter count low: most functions take 3-5 parameters
- Use dictionaries/objects for related parameters (e.g., `msg = {"channel": "CAN0", "id": "0x123", ...}`)
- Optional parameters with defaults (e.g., `prefix=None` in `list_discovery_channels()`)
- Shared state passed by reference: lists for mutable counters (`frame_counter = [0]`), Events for signaling

**Return Values:**
- Explicit return types in Python type hints
- Functions return meaningful values or None on failure
- Early returns to reduce nesting (e.g., `if not isinstance(point, ...): return`)
- Sentinel values for special cases (e.g., `_STOP = object()` to signal thread termination)

## Module Design

**Exports:**
- Python: Functions defined at module level, `if __name__ == "__main__":` pattern for entry points
- JavaScript: No explicit exports; single-purpose files (server, simulator, dashboard UI)

**Barrel Files:**
- Not used in this codebase
- Each module is standalone and importable

**Global State:**
- **Python:** 
  - Module-level constants and initialization (e.g., `db = cantools.database.load_file()`)
  - Globals set to None, loaded in main: `db = None` then `db = cantools.database.load_file()`
  - Shared mutable state passed to threads as lists: `frame_counter = [0]`
- **JavaScript:**
  - Global state object at top: `let state = {}`, `let activeChannel = null`
  - Module-level variables for timing/performance: `let msgCount = 0, lastMsgCountTs = Date.now()`
  - Preserved across function calls via closure

**Threading (Python):**
- Thread naming for debugging: `name="capture"`, `name="writer"`
- Daemon vs non-daemon threads: capture=daemon (background), writer=non-daemon (must finish)
- Shared state via queues: `raw_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)`
- Synchronization via Event: `stop_event = threading.Event()`
- Clean shutdown: signal handlers set `stop_event`, threads poll `stop_event.is_set()`

---

*Convention analysis: 2026-07-30*
