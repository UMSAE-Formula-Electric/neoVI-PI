# Feature Research

**Domain:** Vehicle telemetry / motorsport data-logging (FSAE student team, live pit monitoring + post-session archive)
**Researched:** 2026-07-30
**Confidence:** MEDIUM (web-sourced, cross-checked across multiple commercial/OSS systems; no primary-source manuals fetched in full)

## Scope Note

This project already has CAN capture, DBC decode, CSV logging, and a live current-values dashboard (see PROJECT.md "Validated"). This research does **not** re-litigate basic capture — it focuses on what a telemetry system is expected to *do* beyond that: the live pit-monitoring experience, alarms, and the post-session archive/analysis experience, under a hard ~200-250 kbit/s link budget with lossy live frames and a guaranteed-complete local archive.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features a pit engineer or post-session analyst assumes exist. Missing these = the tool is not trusted trackside.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Scrolling time-series plot of selected signals, recent window | Every reviewed system (MoTeC i2, AiM, RaceCapture) leads with this; a table of current values (already built) is not enough to see a trend developing (temp climbing, cell voltage sagging) | MEDIUM | uPlot is well-suited (per project constraint) — canvas-based, handles high point counts. Needs a ring-buffer of recent samples per signal, not the whole session. |
| Multi-signal overlay on one plot | Pit engineers correlate signals (e.g. throttle vs. wheel speed vs. brake pressure) — single-signal-at-a-time views are why MoTeC/AiM/RaceCapture all support overlay | LOW-MEDIUM | uPlot supports multiple series natively; mainly a UI/selection problem, not a plotting-engine problem |
| Cursor / hover readout of exact value + timestamp | Standard in every reviewed analysis tool (MoTeC i2 channel reports, AiM); "eyeball the line" is not sufficient when deciding whether to pull the car in | LOW | uPlot has built-in cursor/sync support |
| Configurable per-signal limit alarms (safe band) with audible + visual alert | Explicitly named as a PROJECT.md Active requirement; every commercial system (MoTeC alarm bar+sound, AiM RGB alarm LEDs, RaceCapture pit-to-car alerts) treats this as core, not optional | MEDIUM | See Alarms section below — the naive version (fire every sample out of band) is an anti-pattern (alarm fatigue); hysteresis/debounce is table stakes, not a differentiator |
| Stale-data / "no signal" indication per plot or per panel | If a signal stops updating (dropped frames, sensor fault, ECU offline) and the UI just freezes the last value with no visual cue, the pit engineer makes decisions on data that is silently wrong — this is a known trap distinct from "signal out of range" | LOW-MEDIUM | Simplest form: gray/dim a value or trace after N seconds without a fresh sample. Cheap, high value, easy to skip by accident. |
| Link-health indicator (packet loss / frames-per-second / staleness of link, at minimum) | Every RC/UAV telemetry link (SiK/RFD900, ExpressLRS, Crossfire) and every cellular telemetry app (RaceCapture) surfaces link status because a lossy link left unindicated is indistinguishable from "car has stopped sending this signal" | LOW-MEDIUM | RSSI is a nice-to-have (SiK radios report it natively per the telemetry_conversation.md architecture) but the load-bearing number for this project is **frames/s received vs. expected** and **gap count**, since the link is explicitly lossy/unacknowledged by design. Full RSSI/LQI split is a differentiator, not required for v1. |
| Session/run segmentation on the archive | Post-session, nobody wants to grep one giant CSV for "the third run after lunch" — MoTeC, AiM, RaceCapture, and CANedge/asammdf workflows all key on discrete sessions/files | LOW-MEDIUM | Cheapest version: one file (or file set) per logger start/stop cycle, named with a timestamp. Formal "session" metadata (driver, event) can be a thin layer on top. |
| Export to a format downstream tools actually read (CSV at minimum; MF4 if feasible) | asammdf, MoTeC i2, MATLAB, and pandas all consume CSV or MDF/MF4 natively; a bespoke format nobody else can open is a dead end (see Anti-Features) | LOW (CSV, already exists) / MEDIUM (MF4 via asammdf) | CSV already shipped. MF4 export via `asammdf`'s Python API is a thin additional writer once decoded signals exist — worth it because it's the one format MoTeC i2 and asammdf both import natively, unlocking tools this team doesn't have to build. |
| Logger heartbeat / "is it actually running and writing" health check | Universally cited in embedded/data-logger practice (heartbeat metrics, missed-heartbeat alarms) — without it a silently-dead logger produces a confident-looking but empty archive, discovered only after the run is over | LOW | A periodic self-check (disk writable, frames/s > 0, disk space remaining) surfaced on the dashboard or a simple status LED/log line. Directly serves PROJECT.md's "no run's data is ever lost" core value. |
| Disk-space management / log rotation so the logger can't silently stop for lack of space | Standard embedded-logger practice; a full NVMe mid-session is a "no run's data is ever lost" violation exactly like the power-cut case already in scope | LOW-MEDIUM | Simplest: check free space at startup and periodically, refuse silent failure — alert instead. Full rotation/pruning policy can come later; the alert-on-low-space is the load-bearing table-stakes piece. |
| Automatic start on power-up, no keyboard/monitor needed | PROJECT.md constraint: "buildable, testable, demonstrable" and testing season is weeks away — a system that needs a laptop plugged into the car to start logging is unusable on an actual test day | LOW-MEDIUM | systemd service on boot; this is ops plumbing, not a data-viz feature, but every reviewed embedded/headless-logger reference treats it as baseline |
| Config outside source code (channels, alarm limits, DBC path) | Already an explicit PROJECT.md Active requirement; also universal across MoTeC/AiM (all config-file or app-driven, no source edits) | LOW | Straightforward YAML/JSON config file, already scoped in this milestone |

### Differentiators (Worth Building If Time Allows)

Not expected by default, but valuable given this team's specific constraints (lossy link, single ground station, weeks to test season).

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Pause / scrub-back on the live stream (rewind the last N minutes without leaving live mode) | Lets the pit engineer catch something they noticed a beat late ("wait, did that temp just spike?") without waiting for post-session analysis; MoTeC/AiM don't strongly need this because their links are less lossy, but on a link that's explicitly allowed to drop frames, being able to scrub back through what *did* arrive is high value for cheap | MEDIUM | Natural extension of the ring-buffer already needed for scrolling plots — extend retention window and add a scrub control. Do this after basic live plotting works, not before. |
| Session/lap markers (manual "mark this moment" button, or auto lap-detect if a lap signal exists) | Speeds up finding "the interesting bit" in archive later; MoTeC/AiM/RaceCapture all support this but it requires either a manual trigger UI or a beacon/GPS source this team doesn't have yet | LOW (manual marker) / HIGH (auto lap detection, needs GPS or a track-position proxy) | Do the manual marker (pit engineer hits a key, timestamp gets written to a small events log) — cheap and useful. Skip auto lap-detect; no GPS/beacon in this project's scope. |
| Alarm history / log (what fired, when, how long, severity) | Lets the team review after a session whether the alarm scheme is actually catching real problems vs. crying wolf — this is the feedback loop that prevents alarm fatigue from creeping in unnoticed | LOW-MEDIUM | Append alarm transitions (armed→fired, fired→cleared) to a small log file alongside the session archive. Natural pairing with the alarm engine itself. |
| Metadata tagging on archived sessions (driver, event, setup notes, conditions) | MoTeC/AiM/RaceCapture workflows all support this; valuable once the team has more than a handful of session files and needs to find "the wet-weather run with driver X" | LOW-MEDIUM | A small sidecar JSON/YAML per session, editable after the fact. Don't build a database — a session directory with a metadata file is sufficient at this scale. |
| Time alignment across multiple sources (e.g. onboard video timestamp vs. CAN log) | Explicitly named in the question and PROJECT.md's out-of-scope note ("record onboard, sync by timestamp post-session") already commits to *doing* the sync post-session even though live video is out of scope | LOW-MEDIUM | If the logger writes a wall-clock or monotonic timestamp per frame and any onboard video/GoPro is timestamp-stable, alignment is a post-processing script, not new capture infrastructure. Cheap once both timestamps exist; not worth building proactively before there's a second data source to align against. |
| MF4/MDF export for MoTeC i2 / asammdf / MATLAB interop | See table-stakes note above — listed again here because it may reasonably slip to "differentiator" if time is short, since CSV export already unblocks pandas/Excel | LOW-MEDIUM | `asammdf`'s Python MDF-writer API makes this a bounded, well-scoped addition once signals are decoded on the ground station |
| Frames/s, packet-loss %, and gap-count trend (not just instantaneous) shown over the session | A single live number ("current fps: 480") hides intermittent problems; a small sparkline/history of link health lets the engineer distinguish "brief notch as the car went behind the pit wall" from "link is degrading all session" | LOW-MEDIUM | Reuses the same ring-buffer/plotting machinery already built for signal traces — treat "link health" as just another time series to plot |
| Remote status check / "is the car logging" from off the car (e.g. simple query over the existing radio or Wi-Fi bulk-pull path) | Useful for pre-run checks without physically walking to the car, but overlaps heavily with the heartbeat feature and the already-scoped Wi-Fi archive pull — most of the value is already delivered by heartbeat + archive-pull | LOW, once heartbeat exists | Don't build a separate remote-status protocol; piggyback a heartbeat byte on the existing live-link framing or the Wi-Fi pull mechanism |

### Anti-Features (Commonly Built, Often Wasted Effort)

Features that look good on a feature-comparison sheet but are a poor match for this team's constraints — or that other teams/products have visibly burned time on for little payoff.

| Feature | Why Requested | Why Problematic Here | Alternative |
|---------|---------------|-----------------------|-------------|
| Live video over the radio link | "Wouldn't it be cool to *see* the car while watching the data" — F1-style broadcast intuition | Already explicitly out of scope in PROJECT.md and for good reason: 480p compressed video alone is 0.5–1 Mbit/s against a ~200-250 kbit/s budget that's already fully committed to the CAN stream. This is an order-of-magnitude bandwidth problem, and live video is rarely actionable in the moment anyway — nobody changes a setup decision because they watched the onboard feed live | Record video onboard (already the plan), sync by timestamp post-session. This is the universal answer across every source reviewed, including F1's own approach for anything beyond their licensed-spectrum broadcast feed. |
| Over-elaborate configurable dashboard builder (drag-and-drop layout designer, arbitrary widget library, saved layout marketplace) | AiM and RaceCapture both ship this, so it looks like "the pros have it" | For a single team with one pit laptop and one dashboard user, a general-purpose layout *designer* is speculative infrastructure — the real requirement is "show these N signals as scrolling plots plus alarms," which is a fixed or lightly-parameterized layout, not a WYSIWYG editor. Building the editor is classic scope creep: teams that build it often end up with one layout anyone ever uses. | Ship one well-designed default layout (or 2-3 presets: "pre-run check," "live run," "post-run review"). Make the *signal selection* configurable (already scoped), not the whole visual layout engine. |
| Custom binary wire/archive format that no external tool reads | Tempting because it's "more efficient" and the team already needs a compact wire format for the radio link | The compact format is correct and necessary *for the radio link specifically* (that's the whole point of the compression work already scoped) — but it must not leak into the archive. If the local NVMe archive is also written in that bespoke format, every downstream tool (MATLAB, pandas, MoTeC i2, asammdf) needs a custom reader nobody else has, and the team becomes the sole maintainer of a file-format spec forever. This is a well-known trap: several hobbyist/small-team telemetry writeups reviewed here converged on MDF4/CSV specifically because it's what the tooling already reads. | Decode DBC signals into standard CSV (already shipped) and optionally MDF4 (via asammdf) for the durable archive. Reserve the bespoke compressed format strictly for the wire protocol between car and ground station; never persist it as the archive of record. |
| Alerting logic that duplicates what the ECU/BMS already does | Feels safer to double-check everything in the telemetry layer too | The ECU/BMS almost certainly already has its own protection thresholds and fault flags on the bus (e.g. a BMS overtemp fault bit). Rebuilding equivalent threshold logic in the dashboard from raw analog channels risks disagreeing with the authoritative source, or duplicating tuning effort every time a limit changes in two places. It also multiplies alarm-fatigue risk — two systems each crying wolf independently. | Where the bus already carries a fault/warning flag from the ECU/BMS, alarm directly on that flag (it's the authoritative signal). Reserve telemetry-layer threshold alarms for the signals that have no equivalent onboard protection or for a "second pair of eyes" case explicitly decided with the team, not by default. |
| Full alarm-management framework (shelving, escalation workflows, acknowledgement audit trail, role-based alarm routing) | ISA-18.2 process-industry alarm management, which is where the reviewed "avoid alarm fatigue" literature comes from, includes a lot of ceremony (shelving, escalation, RCA workflow) | This is built for control rooms with shift handovers and regulatory audit requirements. A student team has one pit engineer watching one laptop for the duration of a run — there's no handover, no compliance audit, no need for role-based routing | Take only the two mechanisms that generalize to this scale: hysteresis/deadband and debounce/delay-before-fire (see Alarms section). Skip shelving, escalation, and audit trail machinery entirely. |
| Auto lap-detection / GPS-based track position and multi-vehicle track map | MoTeC/AiM/RaceCapture all show a track map with car position — looks impressive and matches what "real" systems have | Requires a GPS or lap-beacon data source this project doesn't have in scope, and the "avoid alarm fatigue / see the car in trouble" core value doesn't depend on knowing *where on the track* it happened, just *when*. This is a differentiator for lap-time optimization products, not for a durability/safety-monitoring pit tool. | Manual event/lap marker (pit engineer presses a key) gets 80% of the practical value for a fraction of the effort. Revisit GPS/track-map only if lap-time analysis becomes an explicit goal in a future milestone. |
| General-purpose time-series database + dashboard framework (InfluxDB/Grafana or Kafka-based stack) as the live path | Several hobbyist and even one FSAE team's telemetry writeup (Kafka + Postgres + Grafana + Next.js) went this route, and it's a legitimate architecture at larger scale | For this project it's a heavyweight dependency footprint (multiple services, a message broker, a real database) to stand up and keep alive on a laptop in a pit tent, when the actual live-data volume after compression is a handful of signals at low Hz over a serial-rate link — the FSAE team that built the Kafka stack explicitly flagged "spotty trackside connectivity" as the real operational pain, which a heavier stack doesn't fix and arguably makes harder to keep running reliably in the field. The project's own stack decision (Python + uPlot in a browser) already reflects this — don't drift toward it under "more scalable" pressure. | Keep the live path simple: Python ground-station process deframes/decodes and pushes over WebSocket to a browser dashboard using uPlot, exactly as scoped. Reach for a real time-series DB only if/when multi-session historical querying at scale becomes a real, felt need — and even then, evaluate against just keeping per-session files plus asammdf/pandas for analysis before adding a server. |
| Real-time compression tuning / adaptive bitrate on the live link | Sounds sophisticated — "adapt to link conditions like video streaming does" | Explicitly cut by an existing Key Decision: the live link is lossy and unacknowledged by design, with archive completeness guaranteed by the local writer instead. Adaptive bitrate reintroduces exactly the class of protocol complexity (feedback loop, ack/nack, rate negotiation) that decision was written to avoid, for marginal benefit given the ~40% headroom already calculated in telemetry_conversation.md | If the fixed compressed format ever doesn't fit, address it by trimming which signals go over the live link (already an explicit design lever — "stream a selected subset live"), not by building adaptive transport logic. |

---

## Feature Dependencies

```
Scrolling time-series plot (uPlot, ring buffer)
    └──requires──> Decoded signal stream on ground station (already scoped: deframe → decompress → DBC decode)

Multi-signal overlay
    └──enhances──> Scrolling time-series plot (same ring buffer, same uPlot instance)

Cursor readout
    └──enhances──> Scrolling time-series plot (uPlot built-in)

Pause / scrub-back on live stream
    └──requires──> Scrolling time-series plot's ring buffer (extend retention window)

Configurable limit alarms (safe band)
    └──requires──> Decoded signal stream
    └──requires──> Hysteresis + debounce logic (else = anti-pattern: alarm chatter)

Alarm history log
    └──requires──> Configurable limit alarms (logs alarm engine's state transitions)

Stale-data indication
    └──requires──> Per-signal last-updated timestamp (cheap addition to existing signal store)

Link-health indicator (frames/s, gap count)
    └──requires──> Frame sequence numbers or timestamps surviving the compression/framing layer
                       (must be designed into the wire framing now — hard to retrofit later)

Session segmentation (archive)
    └──requires──> Logger start/stop lifecycle already exists

Metadata tagging on sessions
    └──enhances──> Session segmentation (adds a sidecar file per session)

Session/event markers
    └──enhances──> Session segmentation + archive (writes into the same per-session directory)

MF4/MDF export
    └──requires──> DBC-decoded signals (already scoped on ground station)
    └──enhances──> Archive (existing CSV output; MF4 is an additional writer, not a replacement)

Logger heartbeat
    └──enhances──> "no run's data is ever lost" core value (PROJECT.md)
    └──conflicts-if-skipped──> Disk-space management (a full disk without an alert IS a silent data-loss failure)

Remote status check ──subset-of──> Logger heartbeat + already-scoped Wi-Fi archive pull
    (do not build as a separate feature/protocol)

Auto lap-detection / track map ──requires──> GPS or lap-beacon data source (NOT in current project scope — hard blocker, not a complexity issue)
```

### Dependency Notes

- **Link-health indicator requires frame sequence numbers surviving compression/framing:** this is the one dependency that must be decided *now*, in the framing-layer design already active in this milestone, not bolted on later — if the compressed frame format has no sequence/counter field, the ground station cannot distinguish "no data arrived" from "nothing changed," and gap/loss counting becomes a guess.
- **Alarms require hysteresis+debounce before shipping, not after:** shipping a naive threshold alarm first and adding hysteresis "later" is the single most common alarm-fatigue trap in every domain reviewed (process industry, medical telemetry, RC/UAV). Treat the debounce/hysteresis logic as part of the alarm feature's definition of done, not a follow-up.
- **MF4 export enhances but does not replace CSV:** CSV already ships and is what a spreadsheet or a quick pandas script reaches for first; MF4 is additive for MoTeC i2 / asammdf interop specifically.
- **Remote status check is a subset, not a new feature:** building a bespoke "ping the car" protocol duplicates what heartbeat + the already-scoped Wi-Fi bulk-pull mechanism can answer for free.

---

## MVP Definition

### Launch With (v1) — trackside for the first test day

- [ ] Scrolling time-series plot of selected signals (uPlot), recent window, multi-signal overlay, cursor readout — the core "see it happening" experience
- [ ] Configurable per-signal limit alarms with hysteresis + debounce, audible + visual — table stakes and an existing Active requirement
- [ ] Stale-data indication per signal/panel — cheap, prevents the single worst failure mode (trusting frozen data)
- [ ] Minimal link-health indicator: frames/s received vs. expected, gap count since session start — requires only that sequence numbers exist in the frame format
- [ ] Logger heartbeat + disk-space alert — directly serves "no run's data is ever lost"
- [ ] Session segmentation (one archive per logger start/stop) — already close to what exists; just needs consistent naming/directory structure

### Add After Validation (v1.x)

- [ ] Pause/scrub-back on the live stream — once the ring buffer and plotting are proven, extend retention and add a scrub control
- [ ] Alarm history log — once the alarm engine exists, log its transitions
- [ ] Manual session/event markers — cheap once session segmentation exists
- [ ] Metadata tagging on sessions (driver, event, conditions) — valuable once there are enough session files to need finding one
- [ ] MF4 export via asammdf — once the team actually wants to open a session in MoTeC i2 or needs asammdf's richer analysis than a CSV/pandas script gives

### Future Consideration (v2+)

- [ ] Time alignment / sync of onboard video against the CAN archive — valuable once video capture is actually wired up on the car (currently just "record onboard" in scope, not yet built)
- [ ] Richer link-health (RSSI/LQI split, not just frames/s) — nice-to-have once basic frames/s-and-gaps proves insufficient in practice
- [ ] Remote pre-run status check — likely falls out for free once heartbeat + Wi-Fi pull both exist; revisit only if it doesn't

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|----------------------|----------|
| Scrolling time-series plot + overlay + cursor | HIGH | MEDIUM | P1 |
| Configurable limit alarms w/ hysteresis+debounce | HIGH | MEDIUM | P1 |
| Stale-data indication | HIGH | LOW | P1 |
| Link-health indicator (frames/s, gaps) | HIGH | LOW-MEDIUM | P1 |
| Logger heartbeat + disk-space alert | HIGH | LOW | P1 |
| Session segmentation | MEDIUM-HIGH | LOW-MEDIUM | P1 |
| Automatic start / headless operation | HIGH | LOW-MEDIUM | P1 |
| Config outside source code | MEDIUM | LOW | P1 |
| Pause/scrub-back on live stream | MEDIUM-HIGH | MEDIUM | P2 |
| Alarm history log | MEDIUM | LOW-MEDIUM | P2 |
| Session/event markers (manual) | MEDIUM | LOW | P2 |
| Metadata tagging on sessions | MEDIUM | LOW-MEDIUM | P2 |
| MF4/MDF export | MEDIUM | LOW-MEDIUM | P2 |
| Video/CAN time alignment | MEDIUM | LOW-MEDIUM | P3 |
| RSSI/LQI-grade link health | LOW-MEDIUM | MEDIUM | P3 |
| Remote pre-run status check | LOW | LOW (piggybacks P1 items) | P3 |
| Live video over radio | — | — (out of scope) | Anti-feature |
| Drag-drop dashboard layout designer | LOW (1 user) | HIGH | Anti-feature |
| Custom binary archive format | — | — | Anti-feature |
| Duplicate ECU/BMS alerting | LOW | MEDIUM | Anti-feature |
| Full ISA-18.2-style alarm management | LOW (1 user, no handover) | HIGH | Anti-feature |
| Auto lap-detect / GPS track map | MEDIUM | HIGH (blocked: no GPS in scope) | Anti-feature (for now) |
| InfluxDB/Grafana/Kafka live stack | LOW (this scale) | HIGH | Anti-feature |
| Adaptive-bitrate live link | LOW | HIGH | Anti-feature |

**Priority key:**
- P1: Must have for the first test day on the car
- P2: Should have, add once P1 is proven on real data
- P3: Nice to have, revisit only if a concrete need appears

---

## Competitor Feature Analysis

| Feature | MoTeC i2 / T2 Telemetry | AiM (MXm/MXS + AiM app) | RaceCapture (Autosport Labs) | CSS Electronics CANedge + asammdf | This project's approach |
|---------|--------------------------|--------------------------|-------------------------------|-------------------------------------|--------------------------|
| Live pit view | Telemetry Monitor: track map, live maths (lap time/fuel), flashing-bar+sound alarms | RGB alarm LEDs on the dash itself + app; less oriented at a separate pit-side live plotter | Browser/mobile app, drag-drop dashboard, live-stream to cloud (Podium) | Not a live-telemetry product — archive/analysis focused | Browser dashboard (uPlot) fed by Python ground station over WebSocket; scrolling plots + alarms, no track map (no GPS in scope) |
| Alarms | User-defined conditions, severity via flashing/sound, momentary alarm transitions | Fully configurable RGB LED alarms: color, solid/flash, frequency, priority, text message | Pit-to-car alerts for known failure modes (overheat, coolant, oil starvation) | N/A (archive tool) | Per-signal band + hysteresis + debounce; audible + visual; alarm history log (v1.x) |
| Link-health display | Not prominently documented in sources reviewed | Not prominently documented | LED + app connection-state indicator (4-color) | N/A | Frames/s vs. expected + gap count (P1); RSSI/LQI split deferred (P3) |
| Archive format | Proprietary MoTeC log format, i2 reads it | Proprietary, AiM Race Studio reads it | Proprietary + cloud (Podium) | **MDF4 (MF4)** — open, ASAM-standard, read by MoTeC i2, asammdf, MATLAB | CSV (already shipped) + MF4 via asammdf (P2) — deliberately avoiding a proprietary/bespoke format, following CANedge's model |
| Post-session analysis | i2 Pro: overlay, X-Y plots, channel/section reports, synced video | Race Studio equivalent (not deeply reviewed) | Podium web analysis | asammdf GUI/API: cut/convert/export/filter/merge, DBC decode, plots | pandas / asammdf / MoTeC i2 (if MF4 exported) — reuse existing tools rather than building an analysis UI |
| Operational/headless | Dedicated hardware loggers, purpose-built | Dedicated hardware loggers | Dedicated hardware + app | Purpose-built SD loggers, some models auto-upload via WiFi/LTE | Raspberry-Pi-based (neoVI PI): systemd auto-start, heartbeat, disk-space alert — general-purpose OS needs this ops layer explicitly built, unlike purpose-built hardware loggers |

---

## Sources

- [MoTeC T2 Telemetry Features](https://www.motec.com.au/t2telemetry/features/) — MEDIUM confidence (single vendor page, cross-checked against i2 feature pages)
- [MoTeC i2 Features](https://www.motec.com.au/i2/i2features/) / [i2 Overview](https://www.motec.com.au/i2/i2overview/) — MEDIUM confidence
- AiM product/reseller pages (Wine Country Motor Sports, Evasive Motorsports, aimtechnologies.com) — MEDIUM confidence, consistent across multiple resellers
- [RaceCapture App User's Guide](https://wiki.autosportlabs.com/RaceCapture_App_User's_Guide) and [RaceCapture real-time telemetry](https://wiki.autosportlabs.com/RaceCapture_real_time_telemetry) — MEDIUM confidence, primary vendor wiki
- [CSS Electronics CANedge product pages](https://www.csselectronics.com/products/can-logger-sd-canedge1) and [MF4/MDF4 explainer](https://www.csselectronics.com/pages/mf4-mdf4-measurement-data-format) — MEDIUM confidence
- [asammdf GitHub](https://github.com/danielhrisca/asammdf) and [CSS Electronics asammdf GUI/API page](https://www.csselectronics.com/pages/asammdf-gui-api-mdf4-mf4) — MEDIUM confidence
- [SavvyCAN via CSS Electronics / fossengineer.com](https://fossengineer.com/savvycan-canbus-reverse-engineering/) — MEDIUM confidence
- Alarm-fatigue / ISA-18.2 pattern sources: [Tractian — Preventing Alert Fatigue](https://tractian.com/en/blog/how-to-prevent-alert-fatigue-in-condition-monitoring), medical-telemetry alarm literature (ECRI/PMC) — MEDIUM confidence (cross-domain, principles generalize, not motorsport-specific)
- RC/UAV link-health conventions: [ExpressLRS Signal Health](https://www.expresslrs.org/info/signal-health/), [Oscar Liang — LQ, RSSI, SNR explained](https://oscarliang.com/lq-rssi/), [ArduPilot RSSI docs](https://ardupilot.org/rover/docs/common-rssi-received-signal-strength-indication.html) — MEDIUM confidence; directly relevant since this project's link is SiK/RFD900-family, the same radio family ArduPilot documents
- [Gray Marshall — Formula SAE EV Telemetry System](https://www.graymarshall.dev/projects/fsae) — MEDIUM confidence, single team's writeup, useful as a cautionary example of a heavier architecture and its stated operational pain point (trackside connectivity)
- [Grafana Labs — Real-time F1 telemetry on Kubernetes with Kafka/Strimzi](https://grafana.com/blog/2021/02/02/real-time-monitoring-of-formula-1-telemetry-data-on-kubernetes-with-grafana-apache-kafka-and-strimzi/) — MEDIUM confidence, illustrates the heavier-stack pattern flagged as an anti-feature at this project's scale
- Embedded/headless logger heartbeat practice: [Interrupt/Memfault — Monitoring Fleet Health with Heartbeat Metrics](https://interrupt.memfault.com/blog/device-heartbeat-metrics), [Log rotation (Wikipedia)](https://en.wikipedia.org/wiki/Log_rotation) — MEDIUM confidence
- `.planning/PROJECT.md` and `telemetry_conversation.md` (this repo) — HIGH confidence, primary project source defining hard constraints (bandwidth, lossy link, out-of-scope items)

---
*Feature research for: vehicle telemetry / motorsport data-logging (FSAE)*
*Researched: 2026-07-30*
