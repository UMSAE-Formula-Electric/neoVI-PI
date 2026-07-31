# Requirements: UMSAE neoVI PI Telemetry & Logging

**Defined:** 2026-07-30
**Core Value:** The pit sees what the car is doing while it is doing it, and no run's data is ever lost.

## v1 Requirements

Requirements for the current milestone. Each maps to exactly one roadmap phase.

### Validation Gate

- [ ] **GATE-01**: Compression ratio is measured against a real captured CAN log, reported as bytes/frame overall and per CAN ID
- [ ] **GATE-02**: Measurement includes worst-case IDs — rolling counters, checksums, multiplexed messages, and high-entropy analog channels — reported separately from the aggregate
- [ ] **GATE-03**: A documented go/no-go decision records whether full-bus streaming is viable, or whether scope falls back to a critical-channels subset

### Capture

- [ ] **CAP-01**: A single logger implementation captures both CAN buses concurrently; the duplicate implementation is removed from the repository
- [ ] **CAP-02**: Capture sustains ~4,000 frames/s combined across both buses for a full session without dropping frames on the archive path
- [ ] **CAP-03**: Capture fans out to two independent consumers whose overflow policies differ — the archive consumer never drops, the telemetry consumer never blocks
- [ ] **CAP-04**: The telemetry consumer is structurally incapable of applying backpressure to the capture thread or the archive path
- [ ] **CAP-05**: Frames the telemetry path discards are counted and reported, not silently dropped
- [ ] **CAP-06**: Hardware and decode errors are logged with frame context rather than silently swallowed

### Archive

- [ ] **ARCH-01**: Every captured frame is written to a local MCAP archive on the onboard NVMe
- [ ] **ARCH-02**: The archive survives an abrupt power cut mid-session with all data written before the cut intact and readable
- [ ] **ARCH-03**: Archive durability is proven by a repeatable physical power-pull test, not by inspection
- [ ] **ARCH-04**: Writes are flushed on a batched cadence rather than per record, so flushing never stalls capture
- [ ] **ARCH-05**: A completed session is marked with a `.done` marker only after the archive is closed and flushed
- [ ] **ARCH-06**: An archived session can be converted to MDF4 for use in standard analysis tools

### Wire Protocol

- [ ] **PROTO-01**: CAN frames are encoded for the wire using delta timestamps, an arbitration-ID dictionary, and payload delta against the previous frame for the same ID
- [ ] **PROTO-02**: The ID dictionary is static, derived from the DBC, versioned, and carried out of band rather than built adaptively over the link
- [ ] **PROTO-03**: Compression state is isolated per CAN ID, so loss affecting one ID cannot corrupt decoding of any other
- [ ] **PROTO-04**: Each ID carries a sequence number allowing the receiver to detect exactly how many frames were lost
- [ ] **PROTO-05**: Periodic keyframes carry full non-delta state, so a receiver that missed data resynchronizes without a session restart
- [ ] **PROTO-06**: A receiver that misses an arbitrary burst of packets recovers automatically within a bounded time and never emits incorrect decoded values

### Link and Framing

- [ ] **LINK-01**: The encoded stream is batched and framed with COBS plus a CRC, so a corrupted byte stream resynchronizes at the next frame delimiter
- [ ] **LINK-02**: Frames failing CRC are discarded and counted, never passed upstream
- [ ] **LINK-03**: Transport is abstracted so the same stream runs over loopback, UDP/Wi-Fi, or a serial port with no change to the layers above
- [ ] **LINK-04**: The full chain runs end to end with no radio hardware present
- [ ] **LINK-05**: When the link saturates, the sender drops the oldest pending data rather than queuing it, so delivered data stays fresh
- [ ] **LINK-06**: A saturation test demonstrates that end-to-end latency stays flat at p99 as offered load exceeds link capacity

### Ground Station

- [ ] **GND-01**: The ground station receives the framed stream, decompresses it, and decodes signals against the DBC
- [ ] **GND-02**: The ground station runs as a single process serving both the decode pipeline and the browser dashboard
- [ ] **GND-03**: The Node.js server is retired and removed from the repository
- [ ] **GND-04**: The ground station maintains current signal state and pushes updates to connected browsers
- [ ] **GND-05**: A newly connected browser receives a full state snapshot rather than waiting for each signal to next update

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
- [ ] **OPS-02**: The logger exposes a heartbeat indicating it is alive and capturing
- [ ] **OPS-03**: Remaining disk space is monitored and surfaced before it becomes critical
- [ ] **OPS-04**: Captured data is segmented into discrete sessions rather than one unbounded file
- [ ] **OPS-05**: Channels, DBC path, alarm limits, and link settings are read from configuration, not hardcoded
- [ ] **OPS-06**: A `requirements.txt` (or equivalent) lets the system be installed on a clean machine
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

Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| (pending roadmap) | — | Pending |

**Coverage:**
- v1 requirements: 55 total
- Mapped to phases: 0
- Unmapped: 55 ⚠️

---
*Requirements defined: 2026-07-30*
*Last updated: 2026-07-30 after initial definition*
