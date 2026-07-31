# Pitfalls Research

**Domain:** FSAE vehicle CAN telemetry over a constrained lossy radio link, with onboard logging on a Raspberry Pi (Intrepid neoVI PI / CM4) in a race car
**Researched:** 2026-07-30
**Confidence:** MEDIUM overall (HIGH for radio/SiK firmware behavior and filesystem power-loss mechanics, which have primary vendor/kernel documentation; MEDIUM for CAN-specific compression numbers, which come from a patent example and general log-compression literature rather than a paper measuring *this* team's DBC; LOW for anything claiming a specific frame-loss threshold for Python on a Pi — no source gives a hard number for this exact workload)

Priority ordering below is by (likelihood × damage) **for this project specifically**, given: testing season is weeks away, the RFD900x is unpurchased, the team is students with turnover, and the compression ratio the whole link-budget argument rests on is estimated, not measured.

## Critical Pitfalls

### Pitfall 1: The compression ratio is a made-up number and the architecture is committed to it

**What goes wrong:**
`telemetry_conversation.md` assumes 4:1–8:1 compression (5–8 bytes/frame) from three techniques: delta timestamps, an ID dictionary, and payload-XOR-against-last-frame-for-same-ID. That number was never run against a real log. If real compression lands at, say, 2:1 instead of 6:1, the "full bus fits with 40% headroom" conclusion — the entire justification for choosing the RFD900x as the *primary* full-bus link rather than a critical-channels-only fallback — collapses, and average throughput could exceed the ~200–250 kbit/s usable payload.

**Why it happens, with evidence:**
- Payload-XOR-against-last-frame only compresses well when most bytes in the payload are *static or slowly varying between consecutive frames of the same ID*. This is true for state flags and coarse setpoints, but breaks down for:
  - **Noisy analog channels.** ADC-sampled sensor values (wheel speed from a raw pulse count, strain gauges, unfiltered temperature/pressure ADC counts) dither in their low bits from sensor noise, not signal change. XOR against the previous frame produces a non-zero, effectively random low byte on almost every frame — the exact opposite of the assumption.
  - **Rolling counters and checksums.** Many CAN payloads carry a message counter or a per-frame checksum byte (common on any bus with safety-relevant frames, and both are near-universal on OEM/automotive CAN and increasingly common on FSAE-built ECUs to catch bus errors). A rolling counter *by construction* differs from the previous frame in a way that doesn't compress with delta/XOR — you're compressing what is functionally random data in that byte position.
  - **Multiplexed messages.** cantools and the DBC multiplex spec both document that a single arbitration ID can carry structurally different signal layouts depending on a multiplexor selector value (see [cantools#300](https://github.com/cantools/cantools/issues/300), [Vector's Extended Signal Multiplexing spec](https://cdn.vector.com/cms/content/know-how/_application-notes/AN-ION-1-0521_Extended_Signal_Multiplexing.pdf)). "Same ID as last frame" is not "same layout as last frame" for a muxed message — naive payload-XOR against the prior frame of that ID can XOR two semantically unrelated bit layouts together, producing a large non-zero delta that compresses badly *and*, if you're being clever and re-deriving the mux selector from delta bits, produces subtly wrong decoded values downstream.
  - Independent research on CAN signal properties backs this up structurally: floating-point signal mantissas carry higher entropy than their exponents, and integer signal low bits carry higher entropy than high bits — i.e., compressibility is not uniform across a CAN payload, it depends entirely on which signals are packed into which bytes on *this* DBC. (Referenced in CAN signal-grouping/entropy compression literature.)
- On the optimistic side: a real patented CAN-bus compression method reports 96–98% size reduction (down to 2.4–3.4% of original — roughly 25:1–40:1) on buses running ~2000 msg/s, by exploiting exactly the counter-run-length structure this team is *not* yet using (run-length-encoding repeated counter sequences rather than raw delta/XOR). That means well-designed CAN compression can beat the 4:1–8:1 assumption by a wide margin — but "well-designed" here specifically targets counter/state structure, which is a different technique than the XOR-only approach currently planned. This is evidence the ceiling is high, not evidence the current design will reach it.
- General-purpose compressors (gzip/lzma/zstd) on structured log-like data show huge sensitivity to method: lzma commonly beats gzip significantly, and specialized log compressors can hit 5–25x over generic gzip on the *same* data. This means "run it through zstd" and "run it through the planned delta/XOR scheme" can produce very different ratios on the same CAN capture — the two are not proxies for each other, and neither has been tried yet on this bus.

**How to avoid:**
1. **Before committing to the compression architecture**, take an existing CSV/log capture from the current logger (or capture 5–10 minutes fresh from the car on the bench) and actually build the planned encoder — delta timestamp + ID dictionary + payload XOR — offline in a throwaway script. Measure real bytes/frame, not estimated.
2. Break the measurement down **per CAN ID**, not as one aggregate number. A handful of high-frequency, high-entropy IDs (wheel speed, IMU, raw ADC channels) will dominate the average; if those don't compress, average bytes/frame will be much worse than the "typical" ID suggests. Identify and specifically test the worst-offender IDs.
3. Specifically test: (a) at least one ID known to carry a rolling counter or checksum byte, (b) at least one multiplexed message if the DBC has any, (c) the highest-frequency raw sensor ID.
4. If measured compression is materially worse than 4:1, the fallback is already implied in the team's own research: drop to "critical channels only" live streaming (30–50 channels at 10–20 Hz, as sized in `telemetry_conversation.md`'s F1-comparison section) rather than the full bus, with the full bus staying full-rate on the local NVMe archive only. Decide the trigger threshold for this fallback *before* the season, not during it.
5. Consider adding a lightweight run-length pass for counter/near-static bytes specifically (the technique the patented 96–98% result relies on) rather than pure XOR, since it directly targets the failure mode most likely to blow the budget.

**Warning signs:**
- Anyone says "compression should be around 4-8x" without a number from an actual measurement run.
- The offline measurement script doesn't exist yet by the time framing/radio-abstraction work starts.
- Per-ID compression isn't broken out — only an aggregate ratio is reported.

**Phase to address:** Should be the *first* piece of work in the telemetry-link track, before framing or radio abstraction are built around it — this is a go/no-go input to the rest of the link design, not a task that can happen in parallel with it.

---

### Pitfall 2: Stateful compression desyncs after a dropped frame and silently emits garbage

**What goes wrong:**
Any compression scheme that references "the last frame" (payload XOR, adaptive ID dictionaries, LZ-style back-references) requires the decoder to hold the same state as the encoder. On a link that is explicitly designed to drop frames (per the project's own decision to accept live-link loss and skip ARQ/retransmit), a dropped compressed frame means the receiver's "last known state" for that CAN ID silently falls behind the transmitter's. The next frame it decodes references a delta against the wrong baseline, producing corrupted signal values — not an error, not a crash, a **plausible-looking wrong number**. For a system whose stated purpose includes limit alarms on temperatures and cell voltages, a garbage-but-plausible value is worse than a dropped frame: it can either mask a real fault or trigger a false alarm.

**Why it happens:**
This is documented as a known, general failure mode of stateful/dictionary compression over lossy networks, not something specific to this project: notification/resync schemes exist precisely because "one lost packet... causes the receiver to lose many packets," and even with a resync protocol there is "loss of data between the loss of the first packet and re-synchronization," plus degraded compression for a period after every resync while dictionaries rebuild (Stanford's delayed-dictionary compression paper on lossy packet networks; general LZ77-over-lossy-link literature). The project's own framing requirement ("resync after corruption, no assumption of message boundaries") acknowledges *byte-level* framing resync but doesn't yet address *semantic* state resync — those are two different problems.

**How to avoid — standard mitigations and their costs:**
1. **Bound the blast radius to one CAN ID.** Keep per-ID "last known payload" state (a table indexed by arbitration ID) rather than one running byte-stream compression state. A dropped frame for ID 0x100 then only means the next 0x100 frame decodes wrong — every other ID is unaffected. This is nearly free and should be the default design, not an optimization.
2. **Self-healing by construction: periodic full-value frames.** Every N frames (or every T milliseconds) per ID, send the full uncompressed/undelta'd payload instead of a delta, regardless of whether it changed. This bounds how long a desync can persist — same idea as a video codec's I-frame. Cost: slightly reduces average compression (worth quantifying against the Pitfall 1 measurement — if margin is tight, this cost matters).
3. **Detect, don't trust.** Attach a cheap integrity check (e.g., a short frame sequence number, or a CRC over the decompressed payload where the DBC already defines one) so a receiver that decodes garbage from a desynced delta can flag/drop it instead of feeding it to alarms and plots. Cost: a few bits per frame; cheap relative to a wrong alarm.
4. **Never build the ID dictionary adaptively from the live stream if it can be avoided.** If arbitration IDs are known ahead of time (they are — there's a DBC), ship a static ID→index table as configuration rather than building it adaptively on first-seen-in-stream. An adaptive dictionary reintroduces exactly the resync problem for the dictionary itself; a static table sidesteps it entirely for that one component.
5. Explicitly test this: build a loopback harness that randomly drops N% of frames and verify decoded output either recovers within a bounded time or is flagged/suppressed, never displayed as silently-wrong.

**Warning signs:**
- Compression state is a single running structure shared across all CAN IDs rather than partitioned per ID.
- No periodic full-frame ("keyframe") mechanism exists.
- The test suite (already an Active requirement) doesn't include a frame-drop scenario.
- Alarms can fire off decompressed data with no integrity check.

**Phase to address:** Telemetry-link phase, at the same time as framing — this is a design decision baked into the compression/framing protocol, not a bolt-on fix after the fact.

---

### Pitfall 3: Saturated link produces a "live" view that is quietly minutes stale, not visibly broken

**What goes wrong:**
This is the single most dangerous failure mode for the stated core value ("the pit sees what the car is doing *while it is doing it*"), because it doesn't look broken. If every queue in the transmit path — the compression/encode queue, the OS serial TX buffer, and critically the **radio's own internal 2048-byte serial buffer** — is allowed to grow unbounded when input arrives faster than the air-rate can drain it, the system doesn't drop frames, it *delays* them. Throughput can look fine (data eventually arrives) while latency balloons. The team's own out-of-scope note about F1 ("onboard buffering... dropouts become latency rather than data loss") is the right idea for the *archive backfill* path but the *wrong* behavior for the *live* path if it happens implicitly rather than by design — a live dashboard showing 10-second-old data with no indication it's stale is far worse than one that visibly drops frames, because the pit engineer will act on it as if it's current.

**Why it happens, with evidence:**
- This is textbook bufferbloat: "a first-in first-out queuing system [with] overly large buffers results in longer queues and higher latency, and does not improve network throughput" (bufferbloat.net / Wikipedia). Radio links are explicitly called out as *worse* for this than wired links because "available bandwidth... can vary by an order of magnitude... in under a second," so a buffer sized for the good case backs up badly in the bad case.
- The SiK/RFD900x firmware itself has a real, documented instance of this: each radio holds a 2048-byte serial input buffer, and the vendor's own fix for it is telling — ArduPilot's SiK docs describe MAVLink-aware adaptive rate throttling (`RADIO` status packets reporting buffer-fullness percentage back to the sender) specifically "to prevent the buffer from getting too much data (which increases latency and risks overflow)." **This project is not sending MAVLink**, so it does not get this adaptive throttling for free — it has to be designed in, or the exact failure the SiK firmware authors already had to engineer around will recur here.
- The same ArduPilot documentation shows the tradeoff is tunable and known: reducing `MAX_WINDOW` from 131ms to 33ms is described explicitly as a "low latency mode" — improving latency at the cost of average bandwidth. This confirms the general principle: you cannot maximize both throughput and low latency on the same fixed-capacity link without an explicit policy choice.

**How to avoid — design for graceful degradation, and prove it:**
1. **Treat the live path as a leaky bucket showing "now," not a FIFO archive.** When the outbound queue (encoder → serial write) is backed up beyond a small, defined latency budget (e.g., a few hundred milliseconds' worth of frames), the correct behavior is to **drop the oldest queued frames and always transmit the newest available data**, not queue everything and let it drain in order. This directly contradicts a naive FIFO queue and must be an explicit implementation choice, not a default.
2. **Budget every buffer in the path in milliseconds, not bytes.** Convert the radio's fixed serial buffer, the OS's TTY output buffer, and any application-level queue into "how many milliseconds of frames can sit here before showing up on screen," and cap all of them. If the radio buffer alone can hold ~2048 bytes and the compressed frame is ~7 bytes, that's ~290 frames — at 100% link utilization that's a nontrivial fixed latency floor before any application-level queuing is even considered.
3. **The archive (NVMe) and the live view must use different queuing policies for the same underlying data.** Archive: never drop, always keep up, backpressure is fine (nothing there is time-sensitive). Live: always prefer newest, drop-oldest under pressure, because stale-but-complete is worse than current-but-incomplete for a screen someone is actively watching. Conflating these two policies into one pipeline is the trap.
4. **Prove the degradation is graceful with a synthetic saturation test**, not by trying it on the car. Build a loopback or rate-limited link (a serial port artificially throttled to the RFD900x's actual usable rate, e.g. via a byte-rate-limiting pipe) and push more data than it can carry. Measure end-to-end latency **percentiles** (p50/p95/p99), not just "did data arrive" — a system that's fine on average but has a p99 latency of 8 seconds fails the "live" requirement even though it "works."
5. Surface link health on the display itself (queue depth / staleness indicator), so a saturated link is visibly saturated to the pit engineer rather than silently stale.

**Warning signs:**
- Outbound queues have no maximum depth, or the maximum is defined in frame-count rather than time.
- No saturation/load test exists before radio hardware arrives — this can and should be tested entirely without a radio using a rate-limited pipe (also required by the constraint that the radio isn't purchased yet).
- The live display has no way to indicate "this data is stale" — silence there is exactly how this failure mode goes unnoticed.

**Phase to address:** Telemetry-link phase (queue policy is part of the framing/transport design) and Live-display phase (staleness indication). The saturation test itself should be part of the test-suite requirement already listed as Active scope, and should specifically target this — not just "does the pipeline work end to end," but "what does it do when overloaded."

---

### Pitfall 4: Local archive isn't actually power-loss safe despite being the durability guarantee the whole design leans on

**What goes wrong:**
The project explicitly delegates data-loss protection to the local NVMe writer ("Archive completeness is guaranteed by the local writer, which never depends on the radio" — a Key Decision the whole retransmit-free live-link design rests on). If that writer isn't actually power-loss safe, the one thing this architecture guarantees turns out not to be guaranteed. Abrupt power loss is explicitly listed as "a normal shutdown mode, not an exception" for this vehicle, and the CONCERNS.md audit of the *existing* codebase already shows the current writer has no graceful degradation on error and no config for durability behavior.

**Why it happens, with evidence:**
- Filesystems remounting read-only after power loss is the kernel's *safe* failure behavior, not a bug: "when the filesystem detects a serious problem with filesystem metadata during runtime that it cannot fix automatically... it remounts read-only to avoid writing and prevent further corruption." That's good for the filesystem, bad for a logger that doesn't check for it — every subsequent write silently fails or throws, and the existing codebase's documented pattern of silently swallowing exceptions (CONCERNS.md: "Silent Decode Exception," "No Graceful Degradation") means this failure mode is already structurally present and would likely recur in a rewrite unless explicitly designed against.
- "Journaled filesystems like ext3/ext4... are less prone to corruption but are far from immune." Journaling protects filesystem *metadata* consistency, not necessarily the payload of a file that was mid-write when power dropped.
- Consumer NVMe/SSDs without power-loss protection have write caching in firmware; a `write()` or even a buffered `fsync()` doesn't guarantee data has actually reached persistent media before power cut, and fsync latency itself can spike into multi-millisecond ranges under sustained write load on consumer drives without PLP — meaning "call fsync often" has both a durability benefit and a real performance cost that needs to be budgeted against the ~4,000 frames/s capture rate, not assumed free.

**How to avoid:**
1. Use an append-only, crash-safe log format for the raw capture file (e.g., write fixed-size, self-describing records so a partially-written record at the tail is trivially detectable and discarded on next read, rather than a format like CSV where a half-written final line can corrupt parsing of the whole file or the reader silently or loudly needs bespoke recovery logic).
2. Tune fsync/flush interval deliberately as a durability-vs-write-amplification tradeoff, not default settings: e.g., fsync every N frames or every T ms, sized against measured fsync latency on the actual NVMe hardware — not assumed instantaneous.
3. **Detect and alert on filesystem going read-only**, don't let it fail silently — this is a direct instance of the "surface decode and hardware errors instead of swallowing them silently" requirement already listed as Active scope, and should explicitly include a periodic writability check (e.g., attempt a small canary write) with a loud local indicator (the driver/pit crew need to know logging has stopped *during* the session, not after).
4. Test this for real: pull power mid-write on the bench repeatedly and verify the archive is recoverable up to the last complete record, not "usually fine."
5. If budget/complexity allows, a supercapacitor or small UPS providing even 1–2 seconds of hold-up on power loss converts "abrupt power cut" into "clean shutdown signal," which is a much easier problem than true async power loss — worth a line-item cost/benefit given how central this guarantee is.

**Warning signs:**
- No canary-write / writability check exists in the running logger.
- No power-pull test has been performed on the bench.
- The archive file format doesn't self-describe record boundaries (making partial-write recovery ambiguous).

**Phase to address:** Local-archive/durability phase — this should be verified before the telemetry-link work is trusted to skip retransmit, since that decision's soundness depends on this guarantee actually holding.

---

### Pitfall 5: Radio hardware isn't purchased, and the live path never gets tested against real RF before competition

**What goes wrong:**
Testing season is weeks away and the RFD900x isn't bought yet. If procurement, configuration, and on-car RF validation (antenna placement, actual link margin, netid/duty-cycle configuration) happen late, the team ends up testing the *software* chain thoroughly on loopback/UDP stand-ins but never validates the actual radio behavior — its buffer/latency characteristics, its response to the car's RF-noisy environment (inverter, HV cabling, ignition — all explicitly named as broadband noise sources in this project's own context), and its physical durability — until it's too late to change course.

**Why it happens, with evidence:**
- This project's own architecture decision explicitly anticipates and mitigates *part* of this risk well: "Transport abstracted behind a swappable link... Loopback and UDP/Wi-Fi stand-ins let the full chain be built and tested now" — that's the right call, and it should be leaned on hard. But a swappable transport interface tests the *software contract*, not the *radio's actual behavior* — netid mismatches, ECC-halved throughput if accidentally left enabled, thermal duty-cycle throttling, and the 2048-byte-buffer latency behavior described in Pitfall 3 are all radio-specific and cannot be exercised by a loopback pipe.
- SiK radio behavior has real gotchas documented directly by the vendor/ArduPilot ecosystem that a UDP stand-in won't reproduce: NETID must match exactly between both ends or the link doesn't establish at all (silent, no partial connectivity to debug against); duty cycle auto-throttles based on radio temperature (relevant in "a hot car"); enabling ECC halves usable throughput and current docs actively recommend against it; air-rate options are discrete steps (2–250 kbps range on the underlying SiK firmware family, up to 500 kbit/s on the RFD900x specifically per vendor spec), not a continuously tunable number, so the "usable throughput" figure depends on which discrete step is actually configured, not the theoretical maximum quoted in planning documents.

**How to avoid:**
1. Order the radios now, in parallel with software work, specifically because "weeks away" leaves little slack for shipping/configuration surprises — this is a procurement-timeline risk independent of the engineering plan.
2. As soon as radios arrive, run a **bench RF test in isolation** (radios a few meters apart, no vehicle) before ever integrating with the car: confirm actual achieved throughput at the intended air rate, confirm netid/duty-cycle config matches on both ends, and measure real latency under saturation (Pitfall 3's synthetic saturation test, but now with real hardware instead of a rate-limited pipe) — this closes the gap between "the swappable-transport interface works" and "the radio works."
3. Then test **on the car with the engine/inverter off, then on**, specifically to characterize whether the HV/ignition EMI this project already flags as a risk actually degrades the link in practice — this is cheap to test early and expensive to discover during a competition run.
4. Keep the loopback/UDP path as the CI-testable default for the software test suite regardless — that requirement doesn't go away, it's just not sufficient on its own for radio-specific behavior.

**Warning signs:**
- Radios haven't been ordered while other phases are underway.
- The transport-abstraction test suite is treated as "proof the radio will work" rather than "proof the software contract is radio-agnostic."
- No bench RF test happens before first on-car integration.

**Phase to address:** Telemetry-link phase for the abstraction (already planned), but the *procurement* action itself is not a phase — it's a parallel-track logistics item that should start immediately regardless of software sequencing, given the "weeks away" constraint.

---

### Pitfall 6: Real-time Python capture drops frames under full 4,000 fps combined bus load, and it's discovered on the car

**What goes wrong:**
The hardware SDK dictates Python on the car side (python-ics/vspyx), and Python is not a real-time environment: GC pauses are unpredictable, the general-purpose Linux scheduler doesn't guarantee the capture thread gets the CPU when a frame arrives, and the existing codebase already shows a queue-based capture/writer split with a documented failure mode ("queue can fill faster than writer thread can drain... no backpressure or graceful degradation" — CONCERNS.md). Adding compression and network transport work into the pipeline (this milestone's whole point) adds more work per frame on a CPU that already has to sustain ~4,000 frames/s combined.

**Why it happens, with evidence:**
- General guidance from the Python/Raspberry Pi community is explicit that this class of workload is risky: Python is "generally unsuitable for real-time or timing critical applications" because GC is unpredictable and "Linux is a multitasking OS where other processes may be given priority over the CPU, causing jitter" (Raspberry Pi Forums / RPi.GPIO docs consensus).
- Concretely for CAN: python-can (a comparable pure-Python CAN library to python-ics) has been measured with dramatically higher per-frame latency than kernel-native tooling — reported figures show raw socketCAN in compiled C achieving ~102µs round-trip on a Pi 4B versus tens of milliseconds for a Python-level read/decode path, and some USB-serial CAN adapters (not the neoVI's own interface, but a class of hardware with the same integration risk) add their own 100+ ms bridge latency on top. **Treat the specific millisecond figures as indicative of the scale of the gap, not as validated numbers for this exact python-ics/neoVI stack — this should be measured on the actual hardware, not assumed from a different library.**
- This project's own CONCERNS.md already documents the exact failure shape in the *existing, simpler* logger: a 50k-frame queue that fills in ~5 seconds if the writer thread stalls under sustained >1,000 fps load, with only a printed warning at 80% full and no backpressure. Adding a compression/encode stage and a network-send stage to the pipeline only adds more per-frame work competing for the same thread budget.

**How to avoid:**
1. **Separate capture from everything else at the thread/process level**, and give the capture path the smallest possible amount of work: read the frame, timestamp it, push raw bytes onto a queue, done. Do compression, DBC-adjacent work (none should happen on the car per this project's own architecture decision), and network I/O in a different thread/process entirely, so a GC pause or scheduler hiccup in the encoder never blocks the thread actually pulling frames off the CAN interface.
2. **Preallocate buffers/queues** rather than allocating per-frame — allocation pressure is a direct driver of GC pause frequency; a fixed-size ring buffer avoids this.
3. **Tune or disable the GC deliberately** on the capture-critical path (e.g., `gc.freeze()` after startup allocations settle, `gc.disable()` with a manual periodic collection scheduled off the hot path) rather than leaving default generational GC running interleaved with frame capture.
4. **Consider SCHED_FIFO (or at least elevated niceness) for the capture thread**, and if headroom allows, core isolation (`isolcpus`) so the capture thread has a CPU core the general scheduler won't preempt for unrelated work — standard real-time Linux techniques, appropriate here given the Pi's quad-core CM4 has cores to spare for this kind of pinning.
5. **Measure, don't assume, on the actual neoVI/python-ics stack** at full combined bus load (~4,000 fps) before trusting the design: run a soak test with a saturated bench bus (or the transmitter/loopback capability the existing codebase already has, once its commented-out transmitter threads are restored per CONCERNS.md) and record dropped-frame counts and queue high-water marks over an extended run, not just a quick smoke test.
6. Keep the existing queue-fill warning but turn it into the graceful-degradation-with-logged-statistics behavior CONCERNS.md already recommends — know exactly how much is being dropped and when, don't just warn once at 80%.

**Warning signs:**
- No soak test at realistic combined bus load exists before season.
- Capture, compression, and network send all happen in a single thread or a single blocking call chain.
- Queue high-water marks aren't logged/monitored during test runs.

**Phase to address:** Local-archive/durability phase for the capture-path hardening itself (it's needed regardless of the radio), verified again once compression/network stages are added in the telemetry-link phase (their added per-frame work could newly overload a capture path that was fine before).

---

## Moderate Pitfalls

### Pitfall 7: Vibration, connector, and EMI failures kill the logger in ways that look like software bugs

**What goes wrong:**
Race-car vibration causes intermittent connector contact loss, which under load can starve the logger's power or a USB-CAN connection just long enough to corrupt an in-progress write or crash a thread — and it will present as an intermittent, hard-to-reproduce "bug" rather than an obvious hardware fault, because it often is transient enough to self-recover before anyone investigates on the bench.

**Why it happens:**
"Mechanical impulses and vibrations force power source terminals to intermittently make and break contact... depriv[ing] the data logger's volatile memory of the energy needed to maintain its proper contents," and "engine vibration, thermal stress... or accidental physical contact can bend pins, crack solder joints, or loosen spring tension holding pins in sockets, causing intermittent contact loss." Vibrating connectors under load are also themselves a documented EMI source, compounding the risk near the inverter/HV cabling this project already calls out as broadband noise sources.

**How to avoid:**
- Strain-relieve every connector on the car-side hardware, not just the antenna (the antenna strain-relief advice already present in `telemetry_conversation.md` should extend to power and USB connectors).
- Treat brief power/USB glitches as expected, not exceptional: this reinforces Pitfall 4's power-loss-safe archive design and Pitfall 6's thread-isolation design — a logger that assumes clean, continuous power will misattribute connector flakiness as software defects.
- Prefer locking/latching connectors (not friction-fit USB-A) for any car-side USB-to-CAN or USB-to-radio link, given USB is explicitly the transport chosen for the CM4's ports.

**Phase to address:** Durability/hardening pass, ideally informed by actual on-car shakedown testing rather than bench testing alone.

---

### Pitfall 8: The existing codebase's silent-failure habits get carried into the rebuild

**What goes wrong:**
CONCERNS.md documents a consistent pattern in the current code: decode exceptions caught and passed silently, no null-check before DBC iteration, no validation of hardware/config at startup, any hardware error terminating the whole logger rather than degrading gracefully. A "whole-stack rebuild" (this project's own stated approach) can easily reproduce the same habits in new code if this isn't treated as a first-class requirement rather than incidental cleanup — new code written under deadline pressure defaults to the path of least resistance, which is exactly these silent-failure patterns.

**Why it happens:**
Silent failure is the easiest thing to write under time pressure — a bare `except: pass` takes one line and never crashes a demo. It's specifically dangerous *here* because this project already depends on error visibility for two of its own core guarantees: "surface decode and hardware errors instead of swallowing them silently" is explicitly Active scope, and Pitfall 4's read-only-filesystem detection and Pitfall 3's link-saturation detection both require the same discipline (fail loud, don't fail silent) to be effective.

**How to avoid:**
- Make "no bare except, no silent pass" a written project convention from the start of the rebuild, not a lint pass at the end.
- Specifically re-verify each of CONCERNS.md's five documented bug/debt items (DBC NoneType risk, silent decode exception, sender channel bug, mismatched start/stop, no graceful degradation) gets a *deliberate* decision in the new code — fixed, or consciously deferred with a reason — rather than silently reproduced by copy-adjacent-pattern.

**Phase to address:** Should be a design convention set at the very start of the rebuild (architecture/scaffolding), enforced across every subsequent phase rather than owned by one.

---

### Pitfall 9: No dependency manifest means the system can't be reliably rebuilt at the track

**What goes wrong:**
Both `requirements.txt`/`pyproject.toml` and `package.json` are absent (confirmed in CONCERNS.md). If a Pi SD card/NVMe needs re-imaging, a laptop needs re-provisioning, or a new team member needs to get a dev environment running — all realistic scenarios in the "weeks away, testing season" window — there's no reproducible way to do it except tribal knowledge of which packages happened to be installed.

**Why it happens:**
This is a known common failure mode for small/student teams: dependencies get installed ad hoc during development and never captured, because the running system "just works" until it's rebuilt from scratch under time pressure — exactly the moment a manifest is needed most.

**How to avoid:**
- Generate `requirements.txt` (or `pyproject.toml`) and `package.json` as one of the very first tasks of the rebuild, not a cleanup item at the end — CONCERNS.md already has a draft dependency list (`vspyx`, `python-ics`, `cantools`, `ws`) to start from.
- Pin versions once things are working — vspyx/python-ics in particular are hardware-SDK-tied and version drift can silently change device behavior.

**Phase to address:** First phase of the rebuild — this is nearly free to do early and expensive to reconstruct later from memory.

---

### Pitfall 10: Single-operator system — one person can run it, nobody else can

**What goes wrong:**
Student teams turn over every year; a system that only the person who built it can operate (undocumented startup sequence, hardcoded paths/IDs requiring source edits to change — both already present per CONCERNS.md's "Hardcoded CAN Message IDs" and "Hard-coded DBC File Path" findings) becomes unusable the season after its author graduates, or even mid-season if that person is unavailable on a race weekend.

**Why it happens:**
It's faster to hardcode a value than to build config for it, and the person who wrote it doesn't need documentation to remember how it works — the cost is entirely externalized onto future operators, which for a one-year student team is often literally a different person.

**How to avoid:**
- This project's own Active scope already includes "Move runtime configuration... out of source code and into config" — treat this as load-bearing for team continuity, not just code cleanliness.
- Write down the operational sequence (how to start a logging session, how to check it's working, how to recover from the read-only-filesystem and link-saturation failure modes above) somewhere a non-author can follow under race-day time pressure.

**Phase to address:** Operations phase, but the config-over-hardcoding part should land before first on-car testing, not after.

---

## Minor Pitfalls

### Pitfall 11: Thermal duty-cycle throttling degrades the radio mid-session without an obvious cause

**What goes wrong:** SiK-family radios (including the RFD900x) auto-throttle duty cycle based on radio temperature to avoid overheating. In "a hot car" (this project's own stated thermal range extends to +80°C), sustained high-duty-cycle transmission over a full session could trigger throttling partway through a run, silently reducing achievable throughput right when the link is already closest to its margin.

**Prevention:** Mount/ventilate the car-side radio with this in mind, and include duty-cycle/temperature telemetry (the radio reports this) in whatever health indicator addresses Pitfall 3's staleness display, so throttling is visible rather than presenting as an unexplained live-data slowdown.

### Pitfall 12: NETID or air-rate mismatch between car and base radios produces total silence, not degraded connectivity

**What goes wrong:** NETID must match exactly for the link to establish at all — there's no partial/degraded state to debug against, just "no link," which can look identical to a dead radio, a dead antenna connection, or a dead power rail from the operator's side.

**Prevention:** Document the exact config values (netid, air rate, ECC on/off) both radios must share, verify them explicitly as part of the bench RF test in Pitfall 5, and provide an operator-visible link-status indicator that distinguishes "no link" from "link up but saturated" (Pitfall 3) so a misconfiguration doesn't get mistaken for a hardware failure at the track.

### Pitfall 13: ECC left enabled halves usable throughput without anyone noticing

**What goes wrong:** Enabling forward error correction on the SiK/RFD900x roughly halves usable throughput in exchange for range/reliability at longer distances the team's own link-budget analysis (48 dB+ margin at 300 m) says aren't needed. Current vendor guidance actively recommends against enabling it. Leaving it on by accident (or by an unreviewed default) directly eats into the already-thin bandwidth margin Pitfall 1 is trying to protect.

**Prevention:** Explicitly set and document ECC=off as a configuration decision, verify it during the bench RF test, and note the tradeoff in whatever config documentation the Operations phase produces.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Ship compression/framing using the *estimated* 4:1–8:1 ratio without measuring first | Faster to start building the radio/framing layer now | Whole link-budget conclusion (full bus fits) may be wrong; discovered only under real load, possibly on the car | Never — this is a go/no-go input, not a detail to backfill |
| Single shared "last frame" compression state instead of per-CAN-ID state | Simpler to implement | Any dropped frame corrupts *all* subsequent frames until a full resync, not just the affected ID | Never, given the project already accepts lossy live frames by design |
| FIFO queuing for the live-link transmit path (same policy as the archive) | Reuses one queue implementation for both paths | Live view silently goes stale under saturation instead of degrading visibly (Pitfall 3) | Only acceptable for the archive path; never for the live path |
| Bare `except: pass` around decode/hardware calls | Demo never crashes | Failures (read-only filesystem, decode errors, dropped frames) become invisible exactly when visibility matters most | Never — already flagged as debt in the existing codebase; don't reproduce it in the rebuild |
| Hardcoded CAN IDs / DBC path / channel names in source | Fastest way to get a script running | Every config change requires a code change and a redeploy, and only the original author knows where to look | Acceptable only for the very first bench smoke test, must not survive into on-car testing |
| Skip the dependency manifest during active development | Nothing to maintain while iterating | System can't be reliably rebuilt on a new machine or after a card re-image, at the worst possible time (trackside) | Acceptable for the first day or two of a fresh rebuild only |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| RFD900x / SiK firmware | Assuming air data rate ≈ usable throughput | Budget ~90% of air rate as usable *without* ECC, and ~50% of that if ECC is (mistakenly) left on; verify actual configured air-rate step, not the theoretical max |
| RFD900x NETID/config | Treating "no link" as a hardware fault | Verify NETID, air rate, and ECC settings match on both radios as the first debugging step; mismatch produces total silence, not degraded connectivity |
| cantools + multiplexed DBC messages | Assuming "same arbitration ID" implies "same byte layout" for delta/XOR compression | Check the DBC for multiplexed messages explicitly and handle them as a distinct case in the compression scheme, not folded into the generic per-ID delta path |
| python-ics / vspyx hardware SDK | Assuming the Python capture path has the same latency characteristics as compiled/kernel-native CAN tooling | Measure actual per-frame latency on the real neoVI hardware before sizing queues/threads around it; don't borrow numbers from a different library or interface |
| NVMe write path | Assuming `write()`/`fsync()` on a consumer drive is instantaneous or guarantees post-power-cut durability | Measure actual fsync latency under the target write rate on the real hardware, and treat "no power-loss protection" consumer SSD/NVMe caching as a real risk to test against, not a theoretical one |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Unbounded transmit queue on the live-link path | "Live" data arrives correctly but progressively later; looks fine until someone checks a timestamp | Cap queue depth in *time*, drop-oldest under pressure (Pitfall 3) | At or near 100% link utilization — i.e., exactly the condition the compression budget is sized to avoid but should still be tested against |
| Single-thread capture+compress+send pipeline | Frame loss correlates with GC pauses or scheduler jitter, not obviously with bus load | Separate capture from encode/send at the thread level; preallocate buffers; consider SCHED_FIFO/core isolation for capture (Pitfall 6) | Sustained combined bus load near ~4,000 fps, worse once compression/network work is added to the per-frame path |
| Adaptive/growing compression dictionary built from the live stream | Compression ratio degrades unpredictably after any dropped frame; hard to reproduce in testing without simulating drops | Static, config-driven ID dictionary; per-ID delta state; periodic full-value "keyframes" (Pitfall 2) | Any frame loss on the live link — which is expected/designed-for behavior on this link, not an edge case |
| fsync on every frame at ~4,000 fps to "be safe" | Write-path latency spikes, potentially starving the capture thread and reintroducing Pitfall 6's frame-loss risk | Batch fsync/flush at a measured, deliberate interval; test actual fsync latency on the real NVMe first | High sustained frame rate on a consumer NVMe without power-loss protection |

## Security Mistakes

Not a primary risk surface for this project (closed RF link, no internet-facing services, single trusted team), but two items are worth a line:

| Mistake | Risk | Prevention |
|---------|------|------------|
| `.gitignore` pattern `*.json` ignoring all JSON, not just data (already flagged in CONCERNS.md) | Could silently exclude a future JSON config file from version control, or (less likely but possible) hide accidental secret commits | Replace with targeted patterns (`logs/*.json`, `data/*.json`); explicit allow-list config files |
| Unauthenticated telemetry link | Anyone with an RFD900x on the same netid/frequency within range could technically receive (or in principle inject) frames | Low priority given ISM-band, short-range, competition context — but if alarms ever drive anything beyond a display (future scope), authentication/integrity on the link becomes relevant then, not now |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| Live view shows no indication of link health/staleness | Pit engineer trusts stale or garbage data as current (Pitfall 2, Pitfall 3) | Explicit staleness/link-health indicator on the display, driven by actual last-frame timestamps and queue depth, not just "data is arriving" |
| Alarms can fire off desynced/garbage decompressed values | False alarms erode trust in real alarms ("cry wolf"), or worse, a real alarm is dismissed as another glitch | Gate alarms behind the same integrity check proposed in Pitfall 2; consider requiring N consecutive plausible readings before an alarm fires, especially right after a detected frame drop |
| System only runnable by the person who built it | Race-day failure with no one else able to operate or recover it | Config-driven operation, written operational runbook (Pitfall 10) |

## "Looks Done But Isn't" Checklist

- [ ] **Compression ratio**: "compression works" isn't enough — verify it was measured per-CAN-ID on a real capture including at least one noisy analog channel, one counter/checksum-carrying message, and one multiplexed message if present, not just an aggregate number from clean/idle bus traffic.
- [ ] **Frame-drop resilience**: "the framing resyncs after corruption" isn't enough — verify it also produces *no garbage decoded values* after a dropped frame, not just that byte-level framing recovers (Pitfall 2's semantic-state desync is a separate problem from byte-level frame boundary loss).
- [ ] **Link works end to end**: "data flows from car to dashboard" isn't enough — verify it under *saturation* with measured latency percentiles, not just a light-load demo (Pitfall 3).
- [ ] **Archive is durable**: "it writes a CSV" isn't enough — verify it survives an actual power pull mid-write on the bench, repeatedly, with the file still parseable up to the last complete record afterward (Pitfall 4).
- [ ] **Radio integration works**: "the transport abstraction passed its tests" isn't enough if those tests only ran against loopback/UDP — verify against real RFD900x hardware once purchased, including a saturation test with real hardware (Pitfall 5).
- [ ] **Capture doesn't drop frames**: "it worked in a short test" isn't enough — verify with a sustained soak test at full ~4,000 fps combined bus load, with dropped-frame counts logged, not just eyeballed (Pitfall 6).
- [ ] **Errors are surfaced**: "it logged something to a file" isn't enough — verify a non-author, mid-session, would actually notice a failure (read-only filesystem, dead radio link, decode errors) without reading logs after the fact.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|-----------------|
| Compression ratio measured worse than assumed after architecture is already built | MEDIUM | Fall back to critical-channels-only live streaming (already sized in `telemetry_conversation.md`'s F1-comparison section: 30–50 channels at 10–20 Hz) while keeping full-rate local archive; doesn't require re-architecting, just re-scoping what's sent live |
| Stateful desync discovered after framing is built without per-ID isolation | MEDIUM–HIGH | Retrofit per-ID state partitioning and periodic keyframes; feasible but touches the core of the compression/framing code, cheaper the earlier it's caught |
| Archive corruption discovered after a real power-loss event with no recovery path | HIGH (data from that session may be unrecoverable) | Salvage what's parseable up to the last complete record if the format allows it; otherwise this is a lost-data event — this is exactly why Pitfall 4 needs to be addressed before, not after, first on-car use |
| Radio never bench-tested before first on-car integration, and something's misconfigured on the day | LOW–MEDIUM if caught trackside with time to debug; HIGH if it eats into limited track time during testing season | Keep the bench RF test procedure written down and fast to re-run; if link is dead, checking netid/air-rate/ECC match is the first, cheapest diagnostic step (Pitfall 12) before assuming hardware failure |
| Team member with critical system knowledge becomes unavailable | LOW if documented, HIGH if not | This is exactly what the operational runbook and config-over-hardcode work (Pitfall 10) is insurance against; cost is proportional to how much was written down in advance |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| 1. Compression assumption unmeasured | Telemetry-link phase (first task, before framing/radio work) | Per-CAN-ID measured bytes/frame on a real capture, including worst-case IDs, compared against the ~200–250 kbit/s budget |
| 2. Stateful compression desync | Telemetry-link phase (compression/framing design) | Loopback test harness that randomly drops frames; verify no garbage propagates beyond the affected ID and within a bounded time |
| 3. Bufferbloat / stale "live" view | Telemetry-link phase (queue policy) + Live-display phase (staleness indicator) | Synthetic saturation test measuring end-to-end latency percentiles (p50/p95/p99), not just success/failure |
| 4. Archive not power-loss safe | Local-archive/durability phase | Repeated bench power-pull test; verify file recoverable to last complete record |
| 5. Radio untested before competition | Telemetry-link phase (abstraction) + parallel procurement track | Bench RF test immediately on radio arrival, before on-car integration |
| 6. Python capture frame loss under load | Local-archive/durability phase, re-verified in telemetry-link phase | Sustained soak test at ~4,000 fps combined load with logged drop counts and queue high-water marks |
| 7. Vibration/connector/EMI failures | Hardening pass, informed by on-car shakedown | Physical inspection + shakedown run before first competition-adjacent test |
| 8. Silent-failure habits reproduced in rebuild | Architecture/scaffolding phase (convention set at start) | Code review checklist: no bare except, every CONCERNS.md item explicitly resolved or deferred with reason |
| 9. No dependency manifest | First phase of rebuild | `requirements.txt`/`pyproject.toml` and `package.json` exist and are used to provision a clean machine successfully |
| 10. Single-operator system | Operations phase, config work pulled forward | A team member other than the primary author can start/monitor/recover a session using only written instructions |
| 11. Thermal duty-cycle throttling | Live-display phase (health indicator) | Radio temperature/duty-cycle status surfaced on display, not just inferred from a slowdown |
| 12. NETID/config mismatch | Telemetry-link phase + bench RF test | Written, versioned config values for both radios; mismatch is the documented first troubleshooting step |
| 13. ECC left on by accident | Telemetry-link phase + bench RF test | ECC=off explicitly set and checked into config/documentation |

## Sources

- [Method for compressing can-bus data (patent, ~96–98% reduction on ~2000 msg/s CAN bus)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12200086) — MEDIUM confidence (patent example, not peer-reviewed measurement on this team's DBC)
- [Vector — Extended Signal Multiplexing in DBC Databases](https://cdn.vector.com/cms/content/know-how/_application-notes/AN-ION-1-0521_Extended_Signal_Multiplexing.pdf) — HIGH confidence (vendor spec)
- [cantools issue #300 — decode multiplexed signal / dlc error](https://github.com/cantools/cantools/issues/300) — HIGH confidence (primary tooling issue tracker)
- [Delayed-Dictionary Compression for Packet Networks (Stanford, Matias)](http://theory.stanford.edu/~matias/papers/infcm_cr.pdf) — HIGH confidence (primary academic source on stateful compression over lossy links)
- [ArduPilot — SiK Radio Advanced Configuration and Technical Information](https://ardupilot.org/copter/docs/common-3dr-radio-advanced-configuration-and-technical-information.html) — HIGH confidence (primary vendor-adjacent/ecosystem documentation; RFD900x runs SiK-derived firmware)
- [RFDesign — SiK Firmware User Manual, RFD900x](https://files.rfdesign.com.au/Files/documents/RFD900x%20Peer-to-peer%20V3.X%20User%20Manual%20V1.4.pdf) — HIGH confidence (primary vendor documentation)
- [PX4 Docs — RFD900 Long-Range Telemetry](https://docs.px4.io/main/en/telemetry/rfd900_telemetry) — MEDIUM confidence (limited detail returned)
- [Bufferbloat.net — Bufferbloat FAQs](https://www.bufferbloat.net/projects/bloat/wiki/Bufferbloat_FAQs/) and [Wikipedia — Bufferbloat](https://en.wikipedia.org/wiki/Bufferbloat) — HIGH confidence (established, well-documented networking phenomenon)
- [Preventing Filesystem Corruption in Embedded Linux (Technologic Systems)](https://www.embeddedts.com/assets/preventing-filesystem-corruption-in-embedded-linux) — MEDIUM-HIGH confidence (embedded-systems vendor guidance, consistent with kernel documentation)
- [Small Datum — SSDs, power loss protection, and fsync latency](http://smalldatum.blogspot.com/2026/01/ssds-power-loss-protection-and-fsync.html) — MEDIUM confidence (practitioner blog, technically consistent with known SSD firmware behavior)
- [PartCatalog — ECM Connector Failure Signs](https://www.partcatalog.com/blogs/engine/ecm-connector-failure-signs-and-diagnostic-steps) and [Amphenol/element14 — Connector Failures](https://community.element14.com/products/manufacturers/amphenol/b/blog/posts/connector-failures-and-what-they-can-really-cost-you) — MEDIUM confidence (industry/vendor guidance, general automotive connector reliability, not FSAE-specific)
- Raspberry Pi Forums discussion on Python real-time/GC limitations — LOW-MEDIUM confidence (community consensus, not a controlled benchmark)
- python-can vs. raw socketCAN latency figures (search-aggregated; treat as directional, not validated for python-ics specifically) — LOW confidence, flagged explicitly in Pitfall 6
- This project's own `.planning/PROJECT.md` and `.planning/codebase/CONCERNS.md` — HIGH confidence (primary source, ground truth for this specific codebase)

---
*Pitfalls research for: FSAE vehicle CAN telemetry over a constrained lossy radio link, onboard logging on a Raspberry Pi*
*Researched: 2026-07-30*
