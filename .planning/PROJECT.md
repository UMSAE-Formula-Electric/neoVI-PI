# UMSAE neoVI PI Telemetry & Logging

## What This Is

A telemetry and data-logging system for the UMSAE formula car, running on an Intrepid neoVI PI (Raspberry Pi CM4). It captures both vehicle CAN buses at full rate into a complete local archive on the onboard NVMe, and simultaneously streams the bus — compressed — over a low-bandwidth radio link to a laptop in the pit, where an engineer watches live plots and limit alarms while the car is on track.

It is used by the UMSAE team: the pit engineer during a run, and anyone doing post-session analysis afterward.

## Core Value

The pit sees what the car is doing *while it is doing it*, and no run's data is ever lost.

## Requirements

### Validated

<!-- Inferred from the existing codebase (see .planning/codebase/). Shipped and relied upon. -->

- ✓ Capture CAN frames from neoVI hardware on user-selected channels — existing (`src/new_logger.py`, python-ics)
- ✓ Decode frames against a DBC database (`epbr2026_DBC_v1.0.dbc`) via cantools — existing
- ✓ Write decoded frames to CSV for post-session analysis — existing
- ✓ Emit decoded signals as newline-delimited JSON on stdout — existing
- ✓ Node.js server ingests that stream and broadcasts signal updates over WebSocket — existing (`can-dashboard/server.js`)
- ✓ Browser dashboard displays live current values grouped by channel and message, with search, per-message/per-signal visibility toggles, min/max range bars, and auto-reconnect — existing (`can-dashboard/dashboard.html`)
- ✓ Transmit test CAN frames on a chosen bus for bench loopback — existing, but hardcoded
- ✓ Synthetic data generator for dashboard testing without hardware — existing (`can-dashboard/simulate.js`)

### Active

<!-- Current scope. Hypotheses until shipped and validated on the car. -->

**Local archive (durability path)**

- [ ] Capture both CAN buses at full rate (~4,000 frames/s combined) without frame loss under sustained load
- [ ] Write a complete local archive to onboard NVMe that survives an abrupt power cut mid-run
- [ ] Consolidate to a single logger implementation; retire the duplicate
- [ ] Surface decode and hardware errors instead of swallowing them silently

**Telemetry link (live path)**

- [ ] Compress raw CAN frames to ~5–8 bytes/frame (delta timestamps, arbitration-ID dictionary, payload XOR against last frame for same ID)
- [ ] Frame the compressed stream for a dumb byte-oriented serial pipe (resync after corruption, no assumption of message boundaries)
- [ ] Abstract the link so the same stream runs over loopback, UDP/Wi-Fi, or an RFD900x serial port without touching the compression or framing layers
- [ ] Ground-station receiver: deframe → decompress → DBC decode → feed the display

**Live display**

- [ ] Scrolling time-series plots of selected signals over a recent window
- [ ] Configurable limit alarms that fire loudly when a signal leaves its safe band (temperatures, cell voltages)

**Operations**

- [ ] Move runtime configuration (channels, transmit IDs, DBC path, alarm limits) out of source code and into config
- [ ] Automated archive pull: the car drains new logs to the pit laptop when it comes into Wi-Fi/Ethernet range
- [ ] Test suite covering capture → decode → compress → frame → transport → decode end to end, runnable with no radio and no vehicle hardware

### Out of Scope

- **Live video over the radio link** — 2–4 Mbit/s against a ~250 kbit/s budget; an order-of-magnitude problem, not a tuning problem. Record onboard, sync by timestamp post-session.
- **1.5 GHz or any licensed spectrum (the F1 approach)** — not an ISM band; in Canada largely allocated to aeronautical and mobile-satellite services. ISED will not license a student team. Confined to ISM.
- **Retransmit / ARQ / gap-backfill on the live link** — explicitly accepted that live frames may be dropped. Archive completeness is guaranteed by the local writer, which never depends on the radio. This removes an entire class of protocol complexity.
- **Wi-Fi diversity antenna pair on the car** — superseded by the RFD900x, which has diversity in firmware.
- **Alfa AWUS036ACM mounted on the car** — consumer USB hardware on a race car is a durability risk; the 900 MHz path removes the need for it. Base station only, if at all.
- **Multiple trackside receive sites** — valuable, but not needed at the link margins the 900 MHz option provides.

## Context

**Existing codebase.** A working but rough capture-and-display stack already exists (see `.planning/codebase/`). Its critical limitation for this project is architectural, not cosmetic: transport is Python `stdout` → Node `stdin`, so the logger and the dashboard must live in the same process tree on the same machine. There is no way to get data to a laptop that isn't the Pi. It also decodes DBC *on the car* and ships decoded signals — exactly backwards for a bandwidth-constrained link, where raw compressed frames should go over the wire and decoding should happen on the ground station where bandwidth is free.

Known debt carried in: two parallel logger implementations, commented-out transmitter threads, hardcoded CAN IDs and frequencies, silent decode-exception swallowing, no dependency manifests (`requirements.txt` / `package.json` both absent), and no tests anywhere.

**RF and link design.** Recorded in `telemetry_conversation.md` at the repo root. Key conclusions that shape the software:

- Both buses run classic CAN at 500 kbps — bus 1 at ~70% load (~2,900 frames/s), bus 2 at ~20% (~830 frames/s), combined ~3,700–4,000 frames/s.
- Naive 24-byte wire records would need ~780 kbit/s. Compressed to 5–8 bytes/frame that becomes ~130–160 kbit/s average, peaking ~220 kbit/s.
- An RFD900x at 500 kbit/s air rate yields ~200–250 kbit/s usable — so the **full bus fits over 900 MHz with roughly 40% headroom.** The radio is therefore the primary full-bus link, not a critical-channels fallback.
- The neoVI PI's onboard CM4 Wi-Fi is effectively 1×1 (the two antenna paths are an RF switch, not two chains), so Wi-Fi diversity would have required an external USB radio on the car. The RFD900x sidesteps this.
- Link margin at 300 m is roughly 48 dB even at the degraded 500 kbit/s sensitivity — range is not the binding constraint. Bandwidth is.

**Unverified assumption.** The 4:1–8:1 compression ratio is estimated, not measured. It should be validated early against a real log file — noisy analog channels whose low bits dither will compress worse than assumed, and the whole "full bus fits" conclusion rests on this number.

## Constraints

- **Tech stack**: neoVI PI (Raspberry Pi CM4), python-ics / vspyx for hardware access, cantools for DBC decode, `epbr2026_DBC_v1.0.dbc` — the hardware SDK dictates Python on the car side.
- **Bandwidth**: ~200–250 kbit/s usable radio payload against ~4,000 frames/s of CAN. Compression is load-bearing, not an optimization.
- **Latency**: live view must be useful during a run — sub-second end to end.
- **Hardware availability**: the RFD900x is not purchased. Everything must be buildable, testable, and demonstrable with no radio present.
- **Timeline**: testing season is weeks away, not months. Every phase must leave something runnable on the car.
- **Environment**: vehicle vibration, −20 °C to +80 °C, and broadband RF noise from the inverter, HV cabling, and ignition. Abrupt power loss is a normal shutdown mode, not an exception.
- **Regulatory**: ISM 902–928 MHz, license-free under ISED in Canada.
- **Competition rules**: no antenna above the main roll hoop plane.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Live link is lossy and unacknowledged | Archive completeness comes from the local NVMe writer, which never depends on the radio. Removes retransmit, ARQ, and gap-backfill entirely — the single largest available scope reduction. | — Pending |
| Compress raw frames on the car, decode DBC on the ground station | Bandwidth is scarce on the car and free on the laptop. Inverts the existing architecture, which decodes on the car and ships decoded signals. | — Pending |
| Transport abstracted behind a swappable link | RFD900x is not purchased and testing season is close. Loopback and UDP/Wi-Fi stand-ins let the full chain be built and tested now. | — Pending |
| 900 MHz (RFD900x) over 2.4/5 GHz Wi-Fi | ~34 dB total link advantage, firmware diversity, no consumer USB hardware on the car — and the compressed full bus still fits. | — Pending |
| Whole-stack rebuild rather than bolting transport onto the existing code | The existing seams (same-machine pipe, decode-on-car) are in the wrong places for this system. | — Pending |
| Ground station is Python end-to-end; retire the Node server | No JS equivalent to `cantools` exists, so DBC decode must be Python. `server.js` is a ~20-line WebSocket server, so porting it to Python `websockets` collapses the pipeline into one process and removes the same-machine constraint. `dashboard.html` survives nearly unchanged. | ✓ Good |
| MCAP as the on-car archive format | Crash-safe append-only. Vector BLF's append mode is an open bug (python-can #1751) and MDF4 has no append at all — both are wrong as a live write target. Convert post-session for tool compatibility. | — Pending |
| Compression ratio becomes a go/no-go gate before transport work | The "full bus fits over 900 MHz" conclusion rests entirely on an unmeasured 4:1–8:1 assumption, and per-ID sequence numbers add a further ~12–15%. A bad ratio invalidates the transport design, not just its tuning. | — Pending |
| Own bufferbloat control required on the live path | The RFD900x's SiK anti-bufferbloat throttling is MAVLink-specific; a non-MAVLink stream gets none of it. Without a drop-oldest policy the link looks healthy while data arrives seconds stale. | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-30 after initialization*
