# Roadmap: UMSAE neoVI PI Telemetry & Logging

## Overview

The project starts with a cheap, offline measurement that decides whether the whole bandwidth premise holds, then immediately lands both halves of the core value on the car: a durable MCAP archive proven against a physical power pull, and a thin end-to-end live link that runs over loopback/UDP with no radio present. From there each phase adds one operationally useful layer to a system that is already running — a real pit view, unattended operation, a wire protocol that cannot silently lie after packet loss, a transmit path that degrades by dropping stale data instead of going quietly late, then plots, alarms, and automated archive retrieval. Radio integration is deliberately last and deliberately carries no v1 requirements, so unpurchased hardware can slip without blocking anything.

## Phases

**Phase Numbering:**

- Integer phases (0, 1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 0: Compression Ratio Gate** - Measure real bytes/frame against a captured log and decide go/no-go on full-bus streaming (completed 2026-08-01)
- [ ] **Phase 1: Dual-Path Capture — Durable Archive and Thin Live Link** - One logger, fan-out to a never-drop archive and a never-block telemetry path, end to end over loopback with no radio
- [x] **Phase 2: Python Ground Station and Dashboard Cutover** - One Python process on the pit laptop decodes the link and serves the browser; Node retired (completed 2026-08-08)
- [ ] **Phase 3: Unattended On-Car Operation** - The car logs on power-up with no keyboard, screen, or login, and says so
- [ ] **Phase 4: Wire Protocol Hardening** - Per-ID isolated state, sequence numbers, and keyframes so packet loss is reported, never silently decoded wrong
- [ ] **Phase 5: Transmit Shaping and Loss-Resilience Test Suite** - Drop-oldest leaky bucket with proven flat p99 latency, plus a hardware-free end-to-end test suite
- [ ] **Phase 6: Live Plots and Link Health** - Scrolling time-series with honest gaps, staleness marking, and a link-health indicator
- [ ] **Phase 7: Limit Alarms** - Config-driven safe bands with hysteresis and debounce that fire loudly and only on trustworthy data
- [ ] **Phase 8: Archive Retrieval and Interchange** - Completed sessions drain to the pit laptop automatically and open in standard analysis tools
- [ ] **Phase 9: RFD900x Radio Integration** - Swap the link for real 900 MHz hardware and characterize it on the bench and on the car

## Phase Details

### Phase 0: Compression Ratio Gate

**Goal**: The team knows what the planned encoding actually costs per frame on this car's real traffic, and has decided in writing whether the full bus fits over the radio
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: GATE-01, GATE-02, GATE-03
**Success Criteria** (what must be TRUE):

  1. A measurement report exists giving real bytes/frame for the planned encoding — delta timestamps, ID dictionary, per-ID payload delta, and the per-ID sequence byte — produced by running it over an already-captured log, aggregate and broken out per CAN ID
  2. The worst-case IDs — rolling counters or checksums, multiplexed messages, and the highest-entropy analog channels — appear in the report with their own numbers rather than folded into the average
  3. The report states the resulting average and peak bit rate for the combined ~4,000 frames/s bus, directly comparable to the ~200–250 kbit/s usable radio budget
  4. A written go/no-go decision records either "full-bus streaming is viable" or names the specific critical-channel subset that will be streamed instead, and that decision is the input every later phase's link scope is built against

**Plans**: 7/7 plans complete

Plans:
**Wave 1**

- [x] 00-01-PLAN.md — Toolchain bootstrap, `src/telemetry/` package skeleton, and executable DBC ground-truth assertions

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 00-02-PLAN.md — Tracer: end-to-end bytes/frame for one CAN ID with a byte-identical round trip
- [x] 00-03-PLAN.md — Structural signal classifier and worst-case category buckets (GATE-02)
- [x] 00-04-PLAN.md — Pre-registered pass threshold and checked-in modelling assumptions

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 00-05-PLAN.md — Full-bus synthetic stream: rate model, entropy brackets, multiplexer cycling

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 00-06-PLAN.md — Measurement engine: per-ID, per-category, worst-N, ablations, peak windows, bit rate

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 00-07-PLAN.md — Run the gate, publish the report, author the go/no-go decision

### Phase 1: Dual-Path Capture — Durable Archive and Thin Live Link

**Goal**: The car runs one logger that never loses a frame to disk and simultaneously delivers frames to a ground station over a swappable link, with no radio present
**Mode:** mvp
**Depends on**: Phase 0
**Requirements**: CAP-01, CAP-02, CAP-03, CAP-04, CAP-05, CAP-06, ARCH-01, ARCH-02, ARCH-03, ARCH-04, ARCH-05, LINK-01, LINK-02, LINK-03, LINK-04, GND-01, OPS-04, OPS-05, OPS-06
**Success Criteria** (what must be TRUE):

  1. One logger captures both CAN buses into a single MCAP archive on the onboard NVMe, the duplicate implementation is gone from the repository, and each run lands in its own discrete session rather than one unbounded file
  2. Power is physically pulled mid-session, repeatedly, and the archive reopens afterward with every record written before the cut intact and readable, and the interrupted session is not marked complete
  3. A sustained run at full combined bus load (~4,000 frames/s) reports zero frames dropped on the archive path, with queue high-water marks, telemetry-path discard counts, and any hardware or decode errors logged with frame context rather than swallowed
  4. A frame captured on the car arrives at the ground station decoded against the DBC, having crossed the batching, COBS+CRC framing, and link layers, with no radio hardware anywhere in the chain and corrupt batches discarded and counted instead of passed upstream
  5. Channels, DBC path, and link settings are read from a config file with no source edit, and a clean machine can be provisioned from the dependency manifest

**Plans**: 13/13 plans executed

> **Scope note on criterion 1:** the "duplicate implementation is gone from the repository"
> clause is deliberately NOT delivered in Phase 1. The user chose to keep
> `src/neoVI_logger.py`, `src/new_logger.py`, `src/references.py`, and `src/neoVI_sender.py`
> in place through Phase 1 for rollback safety (`01-CONTEXT.md` § Deferred Ideas). Phase 1
> delivers CAP-01's other half — one new implementation captures both buses concurrently —
> and the removal clause re-targets to Phase 2, which is already the retirement phase.

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Package legitimacy gate for mcap, cobs, crccheck, and python-ics (blocking human checkpoint)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — Pinned runtime manifest, slow marker, and placeholder test files for every Wave 0 gap
- [x] 01-03-PLAN.md — `config/logger.json` and its typed fail-closed loader, including the 12-message allowlist

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-04-PLAN.md — Tracer: one frame through capture → archive AND capture → encode → frame → link → deframe → DBC decode

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-05-PLAN.md — Crash-recovery read path, session naming fallback, and the physical power-pull procedure
- [x] 01-06-PLAN.md — Archive writer flush cadence, sync accounting, and the drain thread
- [x] 01-07-PLAN.md — Fan-out hardening: divergent overflow, exact discard counting, errors with frame context
- [x] 01-08-PLAN.md — Framing corruption and resync proofs, plus the UDP link
- [x] 01-09-PLAN.md — python-ics hardware capture source, proven with no device attached

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 01-10-PLAN.md — Car-side telemetry pipeline and logger CLI with a shutdown counters report
- [x] 01-11-PLAN.md — Headless ground station and the two-process capture-to-pit run over UDP
- [x] 01-12-PLAN.md — Archive replay frame source and a real-log input path for the Phase 0 gate

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 01-13-PLAN.md — Sustained full-rate soak with per-stage timing and reported counters

### Phase 2: Python Ground Station and Dashboard Cutover

**Goal**: The pit engineer opens a browser and watches the car's live signals arriving over the new link, served by one Python process
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: GND-02, GND-03, GND-04, GND-05, CAP-01

> **CAP-01 lands here, not in Phase 1.** Phase 1 delivered its "single implementation captures
> both buses" half; the "duplicate implementation is removed from the repository" half was
> deliberately deferred by user decision (`01-CONTEXT.md` § Deferred Ideas) to keep the legacy
> loggers for rollback safety. Phase 2 deletes `src/neoVI_logger.py`, `src/new_logger.py`,
> `src/references.py`, and `src/neoVI_sender.py` alongside the Node server (GND-03), so all
> legacy retirement lands together. `REQUIREMENTS.md` already records this; the requirement
> list above now matches it.
**Success Criteria** (what must be TRUE):

  1. A single Python process on the pit laptop receives the link, decodes signals, holds current state, and serves the browser dashboard — no second process, no same-machine pipe
  2. The browser shows live current values for both buses fed by the telemetry link rather than by a local stdout pipe, so the laptop no longer has to be the car
  3. A browser opened mid-session immediately shows every signal's current value instead of waiting for each signal to next update
  4. The Node.js server is removed from the repository and nothing in the system depends on it

**Plans**: 4/4 plans executed

Plans:

- [x] 02-01-PLAN.md — Tracer: one decoded signal travels link → state store → SSE → a connected client, in one process
- [x] 02-02-PLAN.md — Serve the ported dashboard over EventSource; staleness dimming and honest empty/no-results copy
- [x] 02-03-PLAN.md — Python simulator replacing simulate.js, driving the real wire path with no car or radio
- [x] 02-04-PLAN.md — Delete the Node directory and the four legacy loggers; update the instruction file; close GND-03 and CAP-01

**UI hint**: yes

### Phase 3: Unattended On-Car Operation

**Goal**: The car logs every run without anyone touching a keyboard, and anyone on the team can tell whether it is working
**Mode:** mvp
**UI hint**: no
**Depends on**: Phase 1
**Requirements**: OPS-01, OPS-02, OPS-03, OPS-07
**Success Criteria** (what must be TRUE):

  1. Applying power to the car is the entire startup procedure — no screen, no keyboard, no login — and the logger is capturing within seconds of boot
  2. Someone standing at the car can tell the logger is alive and capturing without opening a terminal
  3. Remaining NVMe space is surfaced while there is still time to act on it, not discovered when a session fails to write
  4. A team member who did not build the system can start a session, confirm it is healthy, and retrieve the data using only the written runbook

**Plans**: TBD

### Phase 4: Wire Protocol Hardening

**Goal**: A receiver that misses data knows exactly what it missed, recovers on its own, and never shows a wrong value in the meantime
**Mode:** mvp
**Depends on**: Phase 0, Phase 1
**Requirements**: PROTO-01, PROTO-02, PROTO-03, PROTO-04, PROTO-05, PROTO-06
**Success Criteria** (what must be TRUE):

  1. Dropping an arbitrary burst of packets never produces a plausible-but-wrong decoded value — affected IDs are held as unknown until they are genuinely recovered
  2. Loss affecting one CAN ID leaves every other ID decoding correctly, because compression state is isolated per ID
  3. The receiver reports how many frames were lost, per ID, rather than only that something was missing
  4. A receiver that missed data resynchronizes within a bounded time from periodic keyframes, with no session restart and no operator action
  5. Both ends derive the arbitration-ID dictionary from the same DBC at build time and refuse to decode when their dictionary versions disagree, instead of silently mismapping IDs

**Plans**: TBD

### Phase 5: Transmit Shaping and Loss-Resilience Test Suite

**Goal**: An overloaded link delivers fresh data late-free instead of going quietly stale, and the whole chain is provable on a laptop with no radio and no car
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: LINK-05, LINK-06, TEST-01, TEST-02, TEST-03
**Success Criteria** (what must be TRUE):

  1. Driving the pipeline past link capacity leaves p99 end-to-end latency flat over a sustained overload rather than climbing, and the same test fails against a plain FIFO
  2. Under saturation the data that arrives is the newest available, with the count of dropped-oldest batches reported rather than hidden
  3. The full capture → encode → frame → transport → deframe → decode chain, including injected packet loss, runs as an automated test suite on a laptop with no radio and no vehicle hardware, and the loss test asserts the receiver both recovers and reports the loss accurately
  4. A soak run at full frame rate for a realistic session duration reports frames captured, archived, transmitted, and dropped as explicit numbers

**Plans**: TBD

### Phase 6: Live Plots and Link Health

**Goal**: The pit engineer watches signals move over time and can always tell the difference between "steady" and "we stopped hearing from it"
**Mode:** mvp
**Depends on**: Phase 2, Phase 5
**Requirements**: VIEW-01, VIEW-02, VIEW-03, VIEW-04, VIEW-05, VIEW-06
**Success Criteria** (what must be TRUE):

  1. An engineer selects signals and watches them scroll as time-series plots over a recent window, with several signals overlaid on one plot for comparison
  2. A cursor placed in the visible window reads out the signal values at that instant
  3. A signal that has stopped updating is visibly marked stale and is never presented as a current value
  4. A gap in the data renders as a visible break in the trace, never as a line interpolated across the missing interval
  5. A link-health indicator shows frames/s being received and the count of detected gaps, so a degraded link is visible without inspecting any individual plot

**Plans**: TBD
**UI hint**: yes

### Phase 7: Limit Alarms

**Goal**: A signal leaving its safe band gets noticed immediately, and the alarm is trusted because it does not cry wolf
**Mode:** mvp
**Depends on**: Phase 6
**Requirements**: ALRM-01, ALRM-02, ALRM-03, ALRM-04, ALRM-05
**Success Criteria** (what must be TRUE):

  1. An engineer sets a safe band for any signal by editing a config file, with no code change and no redeploy of the car
  2. A signal leaving its safe band raises an alarm that is impossible to miss on the pit screen, and alarms never fire on values the receiver has flagged stale or unrecovered
  3. A signal hovering at its threshold holds a single steady alarm state instead of flickering in and out
  4. A single transient sample outside the band does not fire an alarm

**Plans**: TBD
**UI hint**: yes

### Phase 8: Archive Retrieval and Interchange

**Goal**: Session data gets off the car and into analysis tools without anyone remembering to do it
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: SYNC-01, SYNC-02, SYNC-03, SYNC-04, ARCH-06
**Success Criteria** (what must be TRUE):

  1. A car that comes back into pit network range transfers its completed sessions to the laptop with nobody doing anything
  2. A session still being written is never copied — only sessions marked complete move
  3. A transfer cut short by the car driving away resumes where it left off instead of restarting from the beginning
  4. A transferred archive is verified against the car-side original before the car-side copy becomes eligible for cleanup
  5. An archived session opens as MDF4 in a standard analysis tool

**Plans**: TBD

### Phase 9: RFD900x Radio Integration

**Goal**: The same unchanged stream runs over real 900 MHz hardware, with its actual throughput, latency, and on-car RF behaviour measured rather than assumed
**Mode:** mvp
**Depends on**: Phase 5, plus RFD900x hardware arrival (procurement, not engineering, is the blocker)
**Requirements**: None
**Why no requirements**: Deliberate — this phase is requirement-free so it can slip without blocking v1. It validates the serial transport implementation (built and proven against a PTY stand-in in Phase 1) against real radio hardware. Every v1 requirement is already satisfiable with loopback, PTY, or UDP transports.
**Success Criteria** (what must be TRUE):

  1. Two radios establish a link on a documented, versioned config — netid, air rate, ECC explicitly off — checked into the same config system the rest of the system uses, so a dead link is diagnosed by comparing config before suspecting hardware
  2. Measured bench throughput and latency under saturation are recorded against Phase 0's bandwidth budget, with the real radio substituted for the rate-limited stand-in and no change to any layer above the link
  3. The car streams to the pit over the radio during a run, and the pit view behaves the same as it did over UDP
  4. On-car link behaviour is characterized with the inverter and ignition off, then on, so EMI degradation is a known quantity rather than a surprise at competition

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

Phase 9 is hardware-gated and may slip past any later work without blocking it. Phase 8 depends only on Phase 1 and can be pulled earlier if archive retrieval becomes urgent.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Compression Ratio Gate | 7/7 | Complete    | 2026-08-01 |
| 1. Dual-Path Capture — Durable Archive and Thin Live Link | 13/13 | In Progress|  |
| 2. Python Ground Station and Dashboard Cutover | 4/4 | Complete    | 2026-08-08 |
| 3. Unattended On-Car Operation | 0/TBD | Not started | - |
| 4. Wire Protocol Hardening | 0/TBD | Not started | - |
| 5. Transmit Shaping and Loss-Resilience Test Suite | 0/TBD | Not started | - |
| 6. Live Plots and Link Health | 0/TBD | Not started | - |
| 7. Limit Alarms | 0/TBD | Not started | - |
| 8. Archive Retrieval and Interchange | 0/TBD | Not started | - |
| 9. RFD900x Radio Integration | 0/TBD | Not started | - |

## Coverage

All 57 v1 requirements map to exactly one phase. No orphans, no duplicates.

| Category | Requirements | Phase |
|----------|--------------|-------|
| GATE | GATE-01 … GATE-03 | 0 |
| CAP | CAP-01 … CAP-06 | 1 |
| ARCH | ARCH-01 … ARCH-05 | 1 |
| ARCH | ARCH-06 | 8 |
| LINK | LINK-01 … LINK-04 | 1 |
| LINK | LINK-05, LINK-06 | 5 |
| GND | GND-01 | 1 |
| GND | GND-02 … GND-05 | 2 |
| PROTO | PROTO-01 … PROTO-06 | 4 |
| VIEW | VIEW-01 … VIEW-06 | 6 |
| ALRM | ALRM-01 … ALRM-05 | 7 |
| OPS | OPS-04, OPS-05, OPS-06 | 1 |
| OPS | OPS-01, OPS-02, OPS-03, OPS-07 | 3 |
| SYNC | SYNC-01 … SYNC-04 | 8 |
| TEST | TEST-01 … TEST-03 | 5 |

## Structural Notes

**Why Phase 0 exists separately.** The compression ratio is the single unmeasured number the entire bandwidth premise rests on, and per-ID sequence numbers add a further ~12–15% on top of it. Measuring it needs no new infrastructure — it runs offline against an already-captured log — and its outcome changes the design downstream rather than just its tuning. If the measured ratio is materially worse than ~4:1, full-bus streaming is off and the live path narrows to a critical-channels subset while the archive stays full-rate.

**Why Phase 1 is large and is not split.** Archive durability and the live link share the capture fan-out primitive, and the fan-out only means anything when both consumers exist to prove the lossy one cannot backpressure the durable one. Splitting them would leave a phase that proves nothing on its own. Phase 1 will decompose into several plans, but its exit condition is single: both paths run on the car at full rate.

**Why the radio is last and carries no requirements.** The RFD900x is not purchased. Every v1 requirement is written to be satisfiable over loopback, a PTY-backed serial stand-in, or UDP. Phase 9 validates hardware behaviour that no software test can substitute for — real throughput, netid/ECC configuration, thermal duty-cycle throttling, on-car EMI — and can slip arbitrarily without stalling any other phase.

**Every phase leaves something runnable on the car.** Phase 0 leaves a decision and a measurement. Phase 1 leaves a logger that never loses data plus a link that reaches the ground. Phase 2 restores the pit view over the new architecture. Phase 3 makes it turnkey. Phases 4–5 make the link honest under loss and saturation. Phases 6–7 make the pit view useful. Phase 8 gets the data off the car. If testing season arrives mid-roadmap, stopping after any phase leaves a coherent working subset.

---
*Roadmap created: 2026-07-30*
