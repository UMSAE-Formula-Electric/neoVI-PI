# Project Research Summary

**Project:** UMSAE neoVI PI Telemetry & Logging
**Domain:** FSAE / student motorsport vehicle CAN telemetry over a constrained lossy radio link
**Researched:** 2026-07-30
**Confidence:** MEDIUM-HIGH

## Executive Summary

This project must deliver two independent data paths off a Raspberry Pi CM4 at ~4,000 CAN frames/s: a **durable MCAP archive** that survives abrupt power loss, and a **lossy 200–250 kbit/s radio live link** feeding 10–20 Hz pit monitoring. Research confirms the architecture is sound and the stack is mature — the risks are operational and measurement-based, not technology-choice-based.

The single biggest correction research makes to the original plan is where the language boundary sits. The existing split (Python logger → Node dashboard) should collapse into **Python end to end**. The deciding fact is that no JavaScript equivalent to `cantools` exists, so DBC decoding must be Python; and since `server.js` is only a ~20-line WebSocket server, porting it to Python `websockets` eliminates the process split entirely — directly fixing the "same process tree" flaw PROJECT.md flagged. `dashboard.html` survives nearly unchanged.

**The highest risk by a wide margin is the unverified 4:1–8:1 compression ratio.** The entire "full bus fits over 900 MHz" conclusion rests on it, it has never been measured against this team's real traffic, and every failure mode that would break it (noisy analog channels dithering low bits, rolling counters and checksums in payloads, multiplexed messages) is plausibly present on an FSAE bus. Architecture research further found that adding per-ID sequence numbers — mandatory for loss detection — costs another ~12–15% on top of the 5–8 bytes/frame estimate. This must be measured against a real log **before** the framing and radio work is committed, and it deserves to be a go/no-go gate rather than a task.

## Key Findings

### Recommended Stack

Mature, boring choices throughout. The compression is the one place where a domain-specific encoder beats any off-the-shelf library — delta timestamps, an ID dictionary, and payload XOR against the last frame for the same ID are the load-bearing mechanism, with a generic compressor only useful as an optional batched second pass.

**Core technologies:**
- **Python end-to-end** — car side and ground station — because `cantools` has no JS equivalent and the Node server is trivial to replace. Collapses the pipeline into one process.
- **MCAP** (`mcap` 1.4.0) — on-car archive format. Crash-safe append-only. Chosen because Vector BLF's append mode is an open bug (python-can #1751) and MDF4 has no append support at all — both are wrong as a live write target. Convert to MDF4/ASC/BLF post-session for tool compatibility.
- **COBS + CRC-16** (`cobs` 1.2.2) over **batched** packets — self-resynchronizing after corruption at the next zero delimiter. Batched, not per-frame: a 4-byte CRC32 per frame would consume most of the 5–8 byte budget by itself.
- **ext4 + batched `fdatasync`** (~100–200 ms cadence) — chosen over F2FS, whose power-loss story is weaker and whose wear-levelling advantage doesn't apply to NVMe the way it does to SD/eMMC. Never fsync per record.
- **uPlot** — browser plotting. Cited benchmarks show ~4–7× lower CPU and memory than Plotly/Chart.js at streaming multi-signal update rates.
- **pyserial** + SiK firmware with **`ECC=0`** — spending half the throughput budget on forward error correction to protect data you have already decided is droppable is the wrong trade.
- **rsync over SSH**, triggered on network availability — not Syncthing (solves a harder bidirectional problem) and not rclone (no cloud target). Critically: sync only after a `.done` marker confirms the session archive is closed and flushed.

### Expected Features

**Must have (table stakes):**
- Scrolling multi-signal time-series plots with overlay and cursor readout — universal across MoTeC i2/T2, AiM, and RaceCapture
- Limit alarms **with hysteresis and debounce** — not a refinement. The most common failure across motorsport, process-industry, and medical telemetry is shipping a naive threshold alarm and adding hysteresis "later," which produces alarm fatigue and trains operators to ignore it
- Stale-data indication — the display must never present old values as current
- Minimal link health: frames/s and gap count — **requires sequence numbers designed into the wire framing now**; this cannot be retrofitted
- Logger heartbeat and disk-space alert
- Session segmentation, headless auto-start on power-up, configuration out of source code

**Should have (competitive):**
- Alarm severity tiers and latched-vs-momentary semantics
- Session metadata tagging (driver, event, setup, conditions)
- MF4 export for downstream tools

**Defer (v1.x+):**
- Scrub-back / pause on a live stream
- Alarm history
- Event and lap markers

**Anti-features — deliberately not building:**
- Live video over the radio link (order-of-magnitude over budget)
- A dashboard layout designer (nobody configures it)
- A bespoke binary archive format — keep the compact format strictly on the wire. CANedge's entire ecosystem strategy is standardizing on MDF4 precisely so MoTeC i2, asammdf, and MATLAB can all read it
- Alerting that duplicates what the ECU or BMS already does
- A Kafka/Postgres/Grafana-style stack — a documented FSAE cautionary tale where the team's stated pain was "spotty trackside connectivity," which a heavier architecture does not fix

### Architecture Approach

Two paths fan out from a single capture source with deliberately asymmetric guarantees, and the guarantee that the lossy path can never backpressure the durable one comes from **choosing data structures where backpressure isn't an available code path** — not from scheduling or priority tricks.

**Major components:**
1. **Capture + fan-out** — `queue.Queue(maxsize=N)` with `put_nowait` for the archive path; `collections.deque(maxlen=N)` (auto-evicting) for telemetry. The deque physically cannot block.
2. **Archive writer** — MCAP append with batched fdatasync. Must survive a real power-pull test.
3. **Wire encoder** — domain-specific compression with four recovery mechanisms: a static DBC-derived versioned ID dictionary, per-ID isolated state, per-ID sequence numbers for gap detection, and periodic per-ID keyframes.
4. **Batcher + leaky bucket** — two-stage: pre-batch drop-oldest deque, then a paced-drain outbound queue with byte-budget-triggered drop-oldest.
5. **Link abstraction** — swappable across loopback, UDP/Wi-Fi, and RFD900x serial without leaking into layers above.
6. **Ground station** — deframe → decompress → DBC decode → state store → asyncio WebSocket push.

On **Python viability**: the GIL is not the real constraint at 4,000 fps. Every stage except the pure-Python domain encoder is dominated by C-extension or syscall work that releases the GIL. Threads are correct car-side, asyncio correct ground-station-side. Multiprocessing is a documented, not-yet-needed escape hatch.

On **time**: the monotonic clock is load-bearing for all correctness; wall-clock is only ever used for human labelling. This makes the CM4's missing battery-backed RTC a non-issue rather than a recurring hazard.

### Critical Pitfalls

1. **The compression ratio is unmeasured** — and everything rests on it. Measure real bytes/frame per CAN ID against an existing log, including worst-case IDs (rolling counters, multiplexed messages, high-entropy analog), before committing framing and radio work.
2. **Stateful compression + accepted frame loss is a designed-in desync trap** — a receiver that misses a packet emits garbage until restart. Per-ID state isolation, a static ID dictionary, and periodic keyframes are cheap now and expensive to retrofit.
3. **Bufferbloat is the most dangerous failure because it is invisible** — the link looks healthy while data arrives seconds stale. The RFD900x's SiK firmware has anti-bufferbloat throttling built in, **but it is MAVLink-specific**; a non-MAVLink stream gets none of it and must implement its own drop-oldest policy. Prove it with a saturation test showing flat p99 latency, not climbing.
4. **The archive's power-loss safety is unverified** — yet the entire no-retransmit decision depends on it holding. Real power-pull testing, not assumption.
5. **Radio procurement is a parallel-track risk, not a phase** — with the RFD900x unpurchased, bench RF work cannot start until hardware arrives. A loopback test suite proves the software contract, not the radio.

## Implications for Roadmap

### Phase 0: Compression Measurement Gate
**Rationale:** Go/no-go. Everything downstream assumes a ratio nobody has measured.
**Delivers:** Real bytes/frame per CAN ID against a captured log; a decision on whether full-bus streaming is viable.
**Avoids:** Building a framing layer and buying a radio against a false bandwidth premise.
**Fallback if <4:1:** Drop to critical-channels-only streaming.

### Phase 1: Capture Fan-out + Archive + Thin Live Link
**Rationale:** The user requires phase 1 to deliver both paths together, and the fan-out is the shared foundation.
**Delivers:** Durable MCAP archive path **and** a thin end-to-end live link over loopback.
**Implements:** Capture fan-out, archive writer, link abstraction.
**Exit criteria:** Power-pull tests pass; 4,000 fps soak test passes; per-frame encoder CPU cost measured on real hardware.

### Phase 2: Protocol Hardening
**Rationale:** Depends on the Phase 0 measurement and the Phase 1 skeleton.
**Delivers:** Per-ID state isolation, keyframes, sequence numbers, leaky-bucket shaping, automated frame-drop and saturation harnesses.
**Exit criteria:** Frame-drop test recovers cleanly; saturation test shows flat p99 latency.

### Phase 3: Live Display
**Rationale:** Needs a trustworthy stream underneath before UI work is meaningful.
**Delivers:** uPlot scrolling plots, alarms with hysteresis and debounce, staleness indication, link-health banner.

### Phase 4: Radio Integration
**Rationale:** Gated on hardware arrival; runs parallel and lands after Phase 3.
**Delivers:** Bench RF test, NETID/ECC verification, measured real throughput, on-car EMI characterization.

### Phase 5: Operations
**Rationale:** Lowest urgency; valuable but nothing depends on it.
**Delivers:** Automated rsync pull, GPS/time sync, runbook, connector hardening.

### Phase Ordering Rationale

- The compression gate precedes everything because a bad ratio invalidates the transport design, not just its tuning.
- Archive and live link ship together in Phase 1 per explicit user requirement, and they share the fan-out primitive anyway.
- Protocol hardening precedes UI because a display fed by a desynchronizing stream teaches you nothing.
- Radio work is decoupled and parallel because procurement, not engineering, is its blocker.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** Compression measurement may surface per-ID patterns requiring protocol refinement.
- **Phase 4:** SiK firmware configuration needs cross-checking against the RFD900x spec.

Phases with standard patterns (skip research-phase):
- **Phases 1, 3, 5** — established patterns, well documented.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Verified against competing options; risk is integration and measurement, not choice |
| Features | MEDIUM-HIGH | Derived from commercial systems; anti-features justified by a concrete FSAE cautionary case |
| Architecture | HIGH | Fan-out, threading, protocol, link abstraction, and leaky-bucket are established practice |
| Pitfalls | MEDIUM | Well documented and testable, but performance claims need Cortex-A72 measurement |

**Overall confidence:** MEDIUM-HIGH — high on structural decisions, medium on every number not yet measured on this hardware.

### Gaps to Address

- **Compression ratio on real data** — Phase 0 gate. No external source measures this on an FSAE DBC.
- **python-ics frame-loss threshold** — no benchmark exists for this specific stack (as opposed to python-can or socketCAN). Measure during Phase 1 soak.
- **Sequence-number overhead (~12–15%)** — first place to trim if margin proves tight after Phase 0.
- **Keyframe cadence** — "≈1/second of that ID's own traffic" is a starting point, not a tuned value.
- **RFD900x real throughput and EMI behaviour** — unknowable until hardware arrives.
- **Whether the bus already carries ECU/BMS fault flags** — needs a look at the DBC; affects whether alarm logic would duplicate existing signals.

## Sources

### Primary (HIGH confidence)
- PyPI / npm registries — current versions for `mcap`, `cobs`, `zstandard`, `cantools`, `pyserial`, `websockets`, `uplot`, `ws`
- ArduPilot and PX4 documentation — SiK firmware buffer behaviour, ECC, netid, duty cycle
- python-can issue #1751 — BLF append-mode bug
- CPython documentation — GIL release semantics, `queue.Queue` / `collections.deque` overflow behaviour

### Secondary (MEDIUM confidence)
- MoTeC i2/ADL, AiM, RaceCapture, CSS Electronics CANedge feature documentation
- Process-industry and medical alarm-fatigue literature — hysteresis/debounce principles
- Published FSAE telemetry writeups, including a Kafka/Grafana stack retrospective

### Tertiary (LOW confidence)
- x86 compression benchmarks used as a headroom argument for Cortex-A72 — not ARM-measured
- RFD900x usable-throughput figures — vendor/community claims, not independently benchmarked

---
*Research completed: 2026-07-30*
*Ready for roadmap: yes*
