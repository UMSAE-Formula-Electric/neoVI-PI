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
- ✓ Compression ratio measured against the planned encoding and ruled on in writing — Phase 0 (`00-DECISION.md`, `00-REPORT.json`)

### Active

<!-- Current scope. Hypotheses until shipped and validated on the car. -->

**Local archive (durability path)**

- [ ] Capture both CAN buses at full rate (~4,000 frames/s combined) without frame loss under sustained load
- [ ] Write a complete local archive to onboard NVMe that survives an abrupt power cut mid-run
- [ ] Consolidate to a single logger implementation; retire the duplicate
- [ ] Surface decode and hardware errors instead of swallowing them silently

**Telemetry link (live path)**

- [ ] Frame the compressed stream for a dumb byte-oriented serial pipe (resync after corruption, no assumption of message boundaries)
- [ ] Abstract the link so the same stream runs over loopback, UDP/Wi-Fi, or an RFD900x serial port without touching the compression or framing layers
- [ ] Ground-station receiver: deframe → decompress → DBC decode → feed the display
- [ ] Live path carries the named critical-channel subset, not the full bus — membership read from a config allowlist at startup, never baked into code
- [ ] Dictionary/allowlist version negotiation so a car and a pit laptop on different subset revisions cannot silently decode to wrong values

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
- Naive 24-byte wire records would need ~780 kbit/s.
- The neoVI PI's onboard CM4 Wi-Fi is effectively 1×1 (the two antenna paths are an RF switch, not two chains), so Wi-Fi diversity would have required an external USB radio on the car. The RFD900x sidesteps this.
- Link margin at 300 m is roughly 48 dB even at the degraded 500 kbit/s sensitivity — range is not the binding constraint. Bandwidth is.

**Superseded by measurement (Phase 0).** The prose above originally concluded that compression to 5–8 bytes/frame would yield ~130–160 kbit/s average and that the **full bus fits over 900 MHz with roughly 40% headroom**, making the radio a primary full-bus link rather than a critical-channels fallback. Phase 0 measured the planned encoding and **disconfirmed that conclusion**:

- Measured **10.22 bytes/frame all-in** (typical entropy bracket), not 5–8.
- Measured **305.13 kbit/s average / 313.55 kbit/s 1-second peak** against a pre-registered ceiling of 120 / 170 kbit/s — a failure by ~2.5×.
- The binding constraint is the fixed **6 B/frame CFR header**, which at ~3,730–4,000 frames/s costs ~179–192 kbit/s on its own, before any payload byte. Payload compressibility was never the deciding variable.

The live path therefore carries a **named 12-message critical-channel subset (74.62 kbit/s)**, not the full bus. The full-rate NVMe archive is unaffected — "no run's data is ever lost" is untouched by this outcome. See `phases/00-compression-ratio-gate/00-DECISION.md` for the signed verdict and `00-REPORT.json` for the measurement.

**Known modelling caveat carried into Phase 1.** Phase 0's stream was synthesized from `epbr2026_DBC_v1.0.dbc` (decision D-01), not captured from the car. Two inputs remain `confirmed: false` — the per-message bus assignment and the total bus frame rate. Separately, the team confirmed the EMUS BMS runs **standard-ID only**, so the 34 `_Ext` messages the model included are not on the real bus; removing them lowers the modelled typical bracket to ~261.85 kbit/s, which does not change the verdict. Phase 1's first bench or track session should re-measure against real captured traffic.

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
| 900 MHz (RFD900x) over 2.4/5 GHz Wi-Fi | ~34 dB total link advantage, firmware diversity, no consumer USB hardware on the car. The original rationale also cited "and the compressed full bus still fits" — Phase 0 disconfirmed that clause, but the link-budget and hardware reasons stand on their own and the 74.62 kbit/s subset fits comfortably. | — Pending |
| Live path carries a critical-channel subset, not the full bus | Phase 0 measured 305.13 kbit/s against a pre-registered 120 kbit/s ceiling. The 6 B/frame CFR header floor alone exceeds the bar at full bus rate, so no payload tuning closes the gap. Subset is 12 messages at 74.62 kbit/s. | ✓ Signed — [00-DECISION.md](phases/00-compression-ratio-gate/00-DECISION.md) |
| Subset membership is a config allowlist, not code | The verdict (D-14) and the encoded byte layout (D-05) are both expensive to reverse; subset *membership* must not be. Membership changes should cost a config edit plus a restart of both ends, which keeps the list tunable once the team learns what the pit engineer actually watches. | — Pending (Phase 1 builds it, Phase 4 versions it) |
| Whole-stack rebuild rather than bolting transport onto the existing code | The existing seams (same-machine pipe, decode-on-car) are in the wrong places for this system. | — Pending |
| Ground station is Python end-to-end; retire the Node server | No JS equivalent to `cantools` exists, so DBC decode must be Python. `server.js` is a ~20-line WebSocket server, so porting it to Python `websockets` collapses the pipeline into one process and removes the same-machine constraint. `dashboard.html` survives nearly unchanged. | ✓ Good |
| MCAP as the on-car archive format | Crash-safe append-only. Vector BLF's append mode is an open bug (python-can #1751) and MDF4 has no append at all — both are wrong as a live write target. Convert post-session for tool compatibility. | — Pending |
| Compression ratio becomes a go/no-go gate before transport work | The "full bus fits over 900 MHz" conclusion rests entirely on an unmeasured 4:1–8:1 assumption, and per-ID sequence numbers add a further ~12–15%. A bad ratio invalidates the transport design, not just its tuning. Measured in `00-REPORT.json`: typical bracket 305.13 kbit/s avg / 313.55 kbit/s peak against pre-registered ceilings of 120 / 170 kbit/s — both fail. | No-go — see [00-DECISION.md](phases/00-compression-ratio-gate/00-DECISION.md); live path carries a named 12-message critical-channel subset (74.62 kbit/s), full-rate archive unaffected |
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
*Last updated: 2026-08-01 after Phase 0*
