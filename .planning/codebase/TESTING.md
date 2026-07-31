# Testing Patterns

**Analysis Date:** 2026-07-30

## Test Framework

**Runner:**
- **Not detected** — No test framework configured or in use
- Python: No pytest.ini, tox.ini, setup.cfg, or pyproject.toml found
- JavaScript: No jest.config.js, vitest.config.js, or test scripts in package.json

**Assertion Library:**
- **Not detected** — No assertion library imports found

**Run Commands:**
- **Manual verification only** — No test automation configured
- Hardware testing: Connect device and run logger scripts with `--channels` arguments
- Dashboard testing: Pipe simulator output to server (see `simulate.js` usage in comments)

## Test File Organization

**Location:**
- **No test files found** in repository
- No `__tests__`, `tests/`, `test/`, or `.test`/`.spec` directories
- Files searched:
  - Python: `*.test.py`, `*.spec.py`, `test_*.py`, `*_test.py`
  - JavaScript: `*.test.js`, `*.spec.js`, `test_*.js`, `*_test.js`

**Naming Convention:**
- Not applicable — no existing tests to establish pattern

**Structure:**
- Not applicable — no test suites defined

## Test Structure

**Suite Organization:**
- Not applicable — no test infrastructure exists

**Patterns:**
- Not applicable — no test patterns established

## Mocking

**Framework:**
- **Not detected** — No mocking library (unittest.mock, sinon, jest.mock, etc.) imports found

**Patterns:**
- **Manual simulation only:**
  - `simulate.js` (`/c/Users/ethan/Documents/UMSAE/neoVI-PI/can-dashboard/simulate.js`) provides test data generation
  - Hardware can be mocked via buffer files: `TESTING_MODE = True` in `neoVI_logger.py` uses buffer files instead of live devices
  - Example: `hardware_sn = str(Path('./src/Vehicle Can.vsb').resolve())` for testing without hardware

**What to Mock:**
- Hardware device initialization: Use buffer files (see `TESTING_MODE` pattern in `neoVI_logger.py`)
- CAN bus communication: Use simulator for test data (see `simulate.js`)
- External dependencies: DBC database can be loaded from test fixture files

**What NOT to Mock:**
- File I/O: Tests should verify actual CSV/VSB output is written correctly
- Threading behavior: Thread synchronization with Events and Queues is critical to verify
- JSON parsing: Real JSON format validation is important for WebSocket communication

## Fixtures and Factories

**Test Data:**
- **Simulator (`simulate.js`):**
  ```javascript
  const SIGNALS = [
    { channel: "CAN0", id: "0x100", name: "EngineControl", signal: "RPM", unit: "rpm", min: 700, max: 7000, freq: 50 },
    { channel: "CAN0", id: "0x101", name: "TransmissionControl", signal: "Gear", unit: "", min: 1, max: 6, freq: 200 },
    // ... 15+ test signal definitions
  ];
  ```
  Usage: `node simulate.js | node server.js` pipes generated data to dashboard

- **Buffer files:**
  - Test data stored in `.vsb` files (Vehicle Spy buffers)
  - Example: `Vehicle Can.vsb` referenced in `TESTING_MODE` (see `neoVI_logger.py` line 29)

- **DBC fixture:**
  - `epbr2026_DBC_v1.0.dbc` in project root
  - Used by logger for message decoding
  - Must be present for CAN signal interpretation

**Location:**
- Fixtures not centralized in dedicated directory
- `epbr2026_DBC_v1.0.dbc` at `/c/Users/ethan/Documents/UMSAE/neoVI-PI/epbr2026_DBC_v1.0.dbc`
- Buffer files in project root or test directories (not yet organized)

## Coverage

**Requirements:**
- **Not enforced** — No coverage tracking configured
- No `.coveragerc`, `pytest.ini`, or coverage thresholds defined

**View Coverage:**
- Not applicable — no coverage tools configured

## Test Types

**Unit Tests:**
- **Not implemented**
- Candidates for unit testing:
  - `build_dbc_index()` in `new_logger.py` — DBC parsing and indexing
  - `resolve_net_ids()` in `new_logger.py` — Channel name to network ID resolution
  - `parseFallback()` in `server.js` — CAN dump format parsing
  - `renderSignalValue()` in `dashboard.html` — Signal value formatting and display

**Integration Tests:**
- **Not implemented**
- Candidates for integration testing:
  - `capture_thread()` + `writer_thread()` in `new_logger.py` — Queue-based producer/consumer with CSV output
  - `server.js` + `dashboard.html` WebSocket communication — Real-time updates
  - End-to-end: `simulate.js | server.js` with browser client — Full stack
  - Device initialization + channel attachment in `neoVI_logger.py` — Hardware integration

**E2E Tests:**
- **Not detected** — No E2E framework (Playwright, Cypress, etc.)
- Manual E2E workflow exists (documented in server.js comments):
  ```
  Usage: node server.js < can_log.jsonl
  Or: your-can-logger | node server.js
  Then: Open http://<your-ip>:3000 on browser
  ```

## Common Patterns

**Async Testing (Python):**
- Not applicable — no async/await code found
- Threading used instead of asyncio (see `threading.Thread` in `new_logger.py`)
- Queue-based communication between threads (see `capture_thread()` and `writer_thread()`)

**Error Testing (Python):**
- Critical error paths tested via argument validation:
  - `neoVI_sender.py` line 19-22: Device initialization failure handling
  - `new_logger.py` line 108-111: Device not found error with helpful message
  - `neoVI_logger.py` line 70-74: RuntimeError with context about valid hardware selectors

- Exception handling in production code (see `new_logger.py` line 244-247):
  ```python
  try:
      decoded = msg_def.decode(data)
  except Exception:
      pass
  ```

**Manual Testing Checklist (Recommended):**
- [ ] Device detection: Does logger find connected neoVI device?
- [ ] Channel attachment: Can all specified CAN channels be opened?
- [ ] CSV output: Is output file created with correct headers and format?
- [ ] Dashboard connection: Does WebSocket connect and receive data?
- [ ] Signal filtering: Do channel-specific signals filter correctly?
- [ ] Graceful shutdown: Do Ctrl+C and thread joins complete without hanging?
- [ ] Error recovery: Does reconnection logic work when server restarts?

## Testing Strategy Recommendations

**For immediate setup:**

1. **Unit test suite (pytest):**
   - Test DBC parsing: `test_build_dbc_index()` — verify message indexing
   - Test channel mapping: `test_resolve_net_ids()` — channel name to ID resolution
   - Test data parsing: `test_parseFallback()` — CAN dump format handling

2. **Integration test suite (pytest + threading):**
   - Mock `ics.get_messages()` to feed test frames
   - Verify CSV output format and content
   - Test queue overflow handling

3. **Dashboard test (manual or Playwright):**
   - Connect to test server running `simulate.js`
   - Verify real-time updates display correctly
   - Test search/filter functionality

4. **Hardware acceptance tests:**
   - Run on actual neoVI Pi with test data
   - Verify CSV output matches expected signal values
   - Test with real CAN bus if available

---

*Testing analysis: 2026-07-30*
