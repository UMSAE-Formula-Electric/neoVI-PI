# Requirements: UMSAE neoVI PI Telemetry & Logging

**Defined:** 2026-07-30
**Core Value:** The pit sees what the car is doing while it is doing it, and no run's data is ever lost.

## v1 Requirements

Requirements for the current milestone. Each maps to exactly one roadmap phase.

### Validation Gate

- [x] **GATE-01**: Compression ratio is measured against a real captured CAN log, reported as bytes/frame overall and per CAN ID
- [x] **GATE-02**: Measurement includes worst-case IDs — rolling counters, checksums, multiplexed messages, and high-entropy analog channels — reported separately from the aggregate
- [x] **GATE-03**: A documented go/no-go decision records whether full-bus streaming is viable, or whether scope falls back to a critical-channels subset

### Capture

- [x] **CAP-01**: A single logger implementation captures both CAN buses concurrently; the duplicate implementation is removed from the repository
- [x] **CAP-02**: Capture sustains ~4,000 frames/s combined across both buses for a full session without dropping frames on the archive path
- [x] **CAP-03**: Capture fans out to two independent consumers whose overflow policies differ — the archive consumer never drops, the telemetry consumer never blocks
- [x] **CAP-04**: The telemetry consumer is structurally incapable of applying backpressure to the capture thread or the archive path
- [x] **CAP-05**: Frames the telemetry path discards are counted and reported, not silently dropped
- [x] **CAP-06**: Hardware and decode errors are logged with frame context rather than silently swallowed

### Archive

- [x] **ARCH-01**: Every captured frame is written to a local MCAP archive on the onboard NVMe
- [x] **ARCH-02**: The archive survives an abrupt power cut mid-session with all data written before the cut intact and readable
- [ ] **ARCH-03**: Archive durability is proven by a repeatable physical power-pull test, not by inspection
- [x] **ARCH-04**: Writes are flushed on a batched cadence rather than per record, so flushing never stalls capture
- [x] **ARCH-05**: A completed session is marked with a `.done` marker only after the archive is closed and flushed
- [ ] **ARCH-06**: An archived session can be converted to MDF4 for use in standard analysis tools

### Wire Protocol

- [ ] **PROTO-01**: CAN frames are encoded for the wire using delta timestamps, an arbitration-ID dictionary, and payload delta against the previous frame for the same ID
- [ ] **PROTO-02**: The ID dictionary is static, derived from the DBC, versioned, and carried out of band rather than built adaptively over the link
- [ ] **PROTO-03**: Compression state is isolated per CAN ID, so loss affecting one ID cannot corrupt decoding of any other
- [ ] **PROTO-04**: Each ID carries a sequence number allowing the receiver to detect exactly how many frames were lost
- [ ] **PROTO-05**: Periodic keyframes carry full non-delta state, so a receiver that missed data resynchronizes without a session restart
- [ ] **PROTO-06**: A receiver that misses an arbitrary burst of packets recovers automatically within a bounded time and never emits incorrect decoded values

### Link and Framing

- [x] **LINK-01**: The encoded stream is batched and framed with COBS plus a CRC, so a corrupted byte stream resynchronizes at the next frame delimiter
- [x] **LINK-02**: Frames failing CRC are discarded and counted, never passed upstream
- [x] **LINK-03**: Transport is abstracted so the same stream runs over loopback, UDP/Wi-Fi, or a serial port with no change to the layers above
- [x] **LINK-04**: The full chain runs end to end with no radio hardware present
- [ ] **LINK-05**: When the link saturates, the sender drops the oldest pending data rather than queuing it, so delivered data stays fresh
- [ ] **LINK-06**: A saturation test demonstrates that end-to-end latency stays flat at p99 as offered load exceeds link capacity

### Ground Station

- [x] **GND-01**: The ground station receives the framed stream, decompresses it, and decodes signals against the DBC
- [x] **GND-02**: The ground station runs as a single process serving both the decode pipeline and the browser dashboard
- [x] **GND-03**: The Node.js server is retired and removed from the repository
- [x] **GND-04**: The ground station maintains current signal state and pushes updates to connected browsers
- [x] **GND-05**: A newly connected browser receives a full state snapshot rather than waiting for each signal to next update

### Live Display

- [ ] **VIEW-01**: An engineer can view scrolling time-series plots of selected signals over a recent time window
- [ ] **VIEW-02**: Multiple signals can be overlaid on one plot for comparison
- [ ] **VIEW-03**: A cursor reads out signal values at a chosen point in the visible window
- [ ] **VIEW-04**: Signals that have stopped updating are visibly marked as stale, never shown as current
- [ ] **VIEW-05**: Data gaps are shown as gaps, not interpolated across
- [ ] **VIEW-06**: A link-health indicator shows frames/s received and count of detected gaps

### Alarms

- [ ] **ALRM-01**: An engineer can configure a safe band for any signal
- [ ] **ALRM-02**: A signal leaving its safe band raises a visually prominent alarm
- [ ] **ALRM-03**: Alarms apply hysteresis so a signal hovering at a threshold does not flicker
- [ ] **ALRM-04**: Alarms apply a debounce interval so a single transient sample does not fire an alarm
- [ ] **ALRM-05**: Alarm limits are configured in a config file, not in source code

### Operations

- [ ] **OPS-01**: The logger starts automatically on power-up with no keyboard, screen, or login
- [x] **OPS-02**: The logger exposes a heartbeat indicating it is alive and capturing
- [ ] **OPS-03**: Remaining disk space is monitored and surfaced before it becomes critical
- [x] **OPS-04**: Captured data is segmented into discrete sessions rather than one unbounded file
- [x] **OPS-05**: Channels, DBC path, alarm limits, and link settings are read from configuration, not hardcoded
- [x] **OPS-06**: A `requirements.txt` (or equivalent) lets the system be installed on a clean machine
- [ ] **OPS-07**: A written runbook covers starting a session, checking health, and retrieving data

### Archive Retrieval

- [ ] **SYNC-01**: When the car reaches pit network range, completed sessions transfer to the laptop without manual intervention
- [ ] **SYNC-02**: Only sessions marked complete are transferred; an in-progress session is never copied mid-write
- [ ] **SYNC-03**: Transfers resume after interruption rather than restarting
- [ ] **SYNC-04**: Transferred archives are verified against the source before the car-side copy is eligible for cleanup

### Validation

- [ ] **TEST-01**: An automated test suite covers capture → encode → frame → transport → deframe → decode end to end, with no hardware
- [ ] **TEST-02**: A test injects packet loss and asserts the receiver recovers and reports the loss accurately
- [ ] **TEST-03**: A soak test sustains full frame rate for a realistic session duration and reports frames captured, archived, transmitted, and dropped

## v2 Requirements

Acknowledged, deferred, not in this roadmap.

### Live Display

- **VIEW-07**: Pause and scrub back through recent history on a live stream
- **VIEW-08**: Session and lap markers

### Alarms

- **ALRM-06**: Alarm severity tiers
- **ALRM-07**: Latched versus momentary alarm semantics
- **ALRM-08**: Alarm history log

### Archive

- **ARCH-07**: Session metadata tagging (driver, event, setup, conditions)
- **ARCH-08**: Time alignment of multiple recording sources
- **ARCH-09**: Video synchronization by timestamp

## Out of Scope

| Feature | Reason |
|---------|--------|
| Live video over the radio link | 2–4 Mbit/s against a ~250 kbit/s budget — an order-of-magnitude problem, not a tuning problem. Record onboard, sync post-session. |
| Retransmit / ARQ / gap backfill on the live link | Live frames are explicitly droppable. Archive completeness comes from the local writer, which never depends on the radio. Removes an entire class of protocol complexity. |
| 1.5 GHz or any licensed spectrum | Not an ISM band; ISED will not license a student team. |
| Configurable dashboard layout designer | Consistently built and consistently unused. Fixed sensible layouts instead. |
| Bespoke binary format as the archive of record | The compact format stays strictly on the wire. Archives must be readable by asammdf, MoTeC i2, and MATLAB. |
| Alerting that duplicates ECU or BMS fault flags | Duplicated logic drifts out of sync with the authoritative source. |
| Kafka / Postgres / Grafana-style stack | A documented FSAE cautionary case — heavier architecture that does not fix the actual pain, which is trackside connectivity. |
| Wi-Fi diversity antenna pair on the car | Superseded by the RFD900x, which has diversity in firmware. |
| Consumer USB Wi-Fi adapter mounted on the car | Durability risk on a race car; the 900 MHz path removes the need. |
| Multiple trackside receive sites | Not needed at the link margins the 900 MHz option provides. |

## Traceability

Populated during roadmap creation (2026-07-30). Every v1 requirement maps to exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| GATE-01 | Phase 0 | Complete |
| GATE-02 | Phase 0 | Complete |
| GATE-03 | Phase 0 | Complete |
| CAP-01 | Phase 1 | Complete |
| CAP-02 | Phase 1 | Complete |
| CAP-03 | Phase 1 | Complete |
| CAP-04 | Phase 1 | Complete |
| CAP-05 | Phase 1 | Complete |
| CAP-06 | Phase 1 | Complete |
| ARCH-01 | Phase 1 | Complete |
| ARCH-02 | Phase 1 | Complete |
| ARCH-03 | Phase 1 | Pending |
| ARCH-04 | Phase 1 | Complete |
| ARCH-05 | Phase 1 | Complete |
| ARCH-06 | Phase 8 | Pending |
| LINK-01 | Phase 1 | Complete |
| LINK-02 | Phase 1 | Complete |
| LINK-03 | Phase 1 | Complete |
| LINK-04 | Phase 1 | Complete |
| LINK-05 | Phase 5 | Pending |
| LINK-06 | Phase 5 | Pending |
| GND-01 | Phase 1 | Complete |
| GND-02 | Phase 2 | Complete |
| GND-03 | Phase 2 | Complete |
| GND-04 | Phase 2 | Complete |
| GND-05 | Phase 2 | Complete |
| PROTO-01 | Phase 4 | Pending |
| PROTO-02 | Phase 4 | Pending |
| PROTO-03 | Phase 4 | Pending |
| PROTO-04 | Phase 4 | Pending |
| PROTO-05 | Phase 4 | Pending |
| PROTO-06 | Phase 4 | Pending |
| VIEW-01 | Phase 6 | Pending |
| VIEW-02 | Phase 6 | Pending |
| VIEW-03 | Phase 6 | Pending |
| VIEW-04 | Phase 6 | Pending |
| VIEW-05 | Phase 6 | Pending |
| VIEW-06 | Phase 6 | Pending |
| ALRM-01 | Phase 7 | Pending |
| ALRM-02 | Phase 7 | Pending |
| ALRM-03 | Phase 7 | Pending |
| ALRM-04 | Phase 7 | Pending |
| ALRM-05 | Phase 7 | Pending |
| OPS-01 | Phase 3 | Pending |
| OPS-02 | Phase 3 | Complete |
| OPS-03 | Phase 3 | Pending |
| OPS-04 | Phase 1 | Complete |
| OPS-05 | Phase 1 | Complete |
| OPS-06 | Phase 1 | Complete |
| OPS-07 | Phase 3 | Pending |
| SYNC-01 | Phase 8 | Pending |
| SYNC-02 | Phase 8 | Pending |
| SYNC-03 | Phase 8 | Pending |
| SYNC-04 | Phase 8 | Pending |
| TEST-01 | Phase 5 | Pending |
| TEST-02 | Phase 5 | Pending |
| TEST-03 | Phase 5 | Pending |

**Coverage:**

- v1 requirements: 57 total (count corrected from 55 — the original total was understated; no requirements were added or removed)
- Mapped to phases: 57
- Unmapped: 0 ✓

**Notes on placement:**

- **OPS-05** (config not hardcoded) lands in Phase 1 for channels, DBC path, and link settings. The alarm-limits portion of the same sentence is delivered by **ALRM-05** in Phase 7, when alarm limits first exist.
- **CAP-02** (no dropped frames at full rate) is proven in Phase 1 as a property of the capture path; **TEST-03** in Phase 5 makes that proof a repeatable automated soak that also reports transmitted and dropped counts on the live path.
- **CAP-01 was deliberately left Pending at the Phase 1 → 2 boundary (user decision, 01-CONTEXT.md `<deferred>`), and completed in Phase 2 as planned.** Phase 1 satisfied its "single implementation captures both buses" half; its "duplicate implementation removed from the repository" half was deliberately deferred — the four legacy modules were kept through Phase 1 for rollback safety. Phase 2 plan 04 deleted all four (alongside the Node server, GND-03), re-ran the deletion blast-radius import check immediately beforehand, and added a regression test (`tests/test_legacy_cutover.py`) that fails if any of the deleted paths reappears, is imported again, or is documented again. Both halves of CAP-01 are now true. (A prior plan marked this row Complete in error before the deletion landed; corrected in 01-13, closed for real in 02-04.)
- **Phase 9 (RFD900x Radio Integration) carries no requirements by design** — every v1 requirement is satisfiable with loopback, PTY, or UDP transports, so unpurchased radio hardware cannot block v1 completion.

---
*Requirements defined: 2026-07-30*
*Last updated: 2026-07-30 after roadmap creation*
