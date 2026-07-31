# Stack Research

**Domain:** FSAE vehicle CAN telemetry & logging — Raspberry Pi CM4 (neoVI PI) car side, custom compression + framing over a 900 MHz serial radio, Python ground station
**Researched:** 2026-07-30
**Confidence:** HIGH on architecture-shaping decisions (ground-station runtime, filesystem, framing, archive-format risk); MEDIUM on numeric throughput/compression-ratio claims not yet measured against this project's real CAN traffic; LOW/flagged where noted.

This document covers the five new subsystems only: compression, serial framing, log file format, power-cut-safe writing, and the ground-station pipeline (decode + display + sync). It does not re-cover CAN capture or DBC decoding — that stack (python-ics/vspyx, cantools) is already validated and unchanged; see `.planning/codebase/STACK.md`.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Custom binary encoder (hand-rolled, no library) | n/a | Delta-timestamp + arbitration-ID dictionary + payload-XOR-vs-last compression, per-frame | This is protocol design, not a library choice. It is the *load-bearing* compression (the 4:1–8:1 ratio the bandwidth budget in `telemetry_conversation.md` depends on) because it exploits structure (near-periodic frames, mostly-repeating payloads) that generic compressors can only find probabilistically and only across a window large enough to build state — at 5–8 bytes/frame there is no room for a generic compressor's own framing overhead per frame. |
| `zstandard` (PyPI) | 0.25.0 (requires Python ≥3.9) | Optional second-pass generic compressor over *batches* of already domain-encoded bytes, on both the live-link and NVMe-archive paths | Zstd's streaming API lets you flush at a controlled cadence (batch ~20–50 ms / ~100–200 frames, not per-frame), capturing redundancy the custom encoder leaves behind, with negligible CPU cost at this data rate on a Cortex-A72 (see Throughput note below). Prefer over LZ4 for the *live link* because CPU headroom is abundant and here ratio, not speed, is the scarce resource — every saved byte matters against the ~220 kbit/s ceiling. |
| `cobs` (PyPI) | 1.2.2 | Frame the compressed byte stream for the dumb serial pipe | COBS guarantees O(1) worst-case overhead (1 byte per ≤254-byte block) and — critically for a lossy link — a decoder can always resynchronize on the next `0x00` delimiter after any corruption, without needing to understand packet contents. Has a C extension with automatic pure-Python fallback, so it works even if the C toolchain isn't available on a given dev machine. |
| ext4 | current Raspberry Pi OS Bookworm default (e2fsprogs-maintained) | Root/data filesystem for the NVMe archive | Ext4's journal-and-replay crash recovery is the most battle-tested power-loss story available on Linux. F2FS's log-structured design is the better fit for wear-limited SD/eMMC, but multiple independent sources agree it is comparatively less power-loss-tolerant, and `fsck.f2fs` cannot run against a mounted filesystem (needs an initramfs step to repair) — added operational complexity this project doesn't need on NVMe, where wear headroom is not the SD-card-grade problem F2FS exists to solve. |
| `mcap` (PyPI) | 1.4.0 (requires Python ≥3.7) | Primary on-car archive container format | Purpose-built for exactly this problem: append-only, chunked, streaming writer with periodic chunk boundaries, and a reader that can recover every *complete* chunk even if the final (in-progress) chunk was truncated by a power cut. Built-in LZ4/Zstd chunk compression, message/chunk indexing for fast post-session seek, and free viewing via Foxglove Studio. Actively maintained (Foxglove); has a maintained JS/TS binding (`@mcap/core`, 2.2.1) if ever needed on the browser/Node side. |
| Python (ground station) | 3.11+ (match Pi OS / whatever the laptop ships) | Single runtime for the entire ground-station pipeline: serial read → deframe → decompress → DBC decode → WebSocket broadcast | See decisive rationale under "Ground-station runtime" below. |
| `websockets` (PyPI) | 17.0 (requires Python ≥3.11) | Replaces Node's `ws`-based `server.js`; serves the WebSocket feed (and static `dashboard.html`) directly from the Python decode process | Actively maintained, asyncio-native, minimal dependency surface. Collapses the two-process, stdout-piped architecture flagged as a structural flaw in `PROJECT.md` into one process with no IPC. |
| `uplot` (npm) | 1.6.32 | Browser-side scrolling multi-signal time-series chart | Canvas-based, purpose-built for real-time time series. Independent benchmarks: streaming 3,600 points at 60 fps costs uPlot ~10% CPU / 12 MB RAM vs. ~40% CPU / 77 MB for Chart.js and ~70% CPU / 85 MB for ECharts on the same task. At 10–20 Hz across dozens of alarm-relevant signals over a multi-hour test day, this is the difference between a dashboard that stays flat and one that leaks memory and drops frames by the third session. |
| `pyserial` | 3.5 | `/dev/ttyUSB0` (or equivalent) access to the RFD900x from both the car-side compressor/framer and (in loopback/bench testing) the ground station | De facto standard; already implicitly assumed by this project's Python-first hardware stack. No new PyPI release in the past year, but this reflects a stable, complete API for basic serial I/O, not abandonment — there is no serious competing library to switch to. |
| `rsync` (over SSH) | system package (no pinned version — ships with Raspberry Pi OS and virtually every Linux/macOS box) | Car → pit-laptop archive sync, triggered on network availability | See rationale under "Log sync" below. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pyzstd` | 0.19.1 | Alternative zstd binding with a stdlib bz2/lzma-style API | Use instead of `zstandard` only if you specifically want the more minimal, stdlib-idiomatic surface; `zstandard` is the more widely deployed binding (used by pip itself) and has the richer streaming/dictionary API this project's flush-cadence tuning needs — treat `pyzstd` as a fallback, not a first choice. |
| `asammdf` | 8.8.22 | Post-session conversion of the MCAP archive to MDF4 (`.mf4`) for teams/tools that want ASAM MDF | Run this as a batch step *after* a session file is closed, not as the live write path — see Log File Format section for why MDF4's own writer is a poor fit for the crash-safety requirement. |
| `python-can` (already a dependency) | 4.6.1 | `ASCWriter`/`ASCReader` for exporting a candump/CANalyzer-compatible `.asc` text export from the MCAP archive | Post-session export, not primary storage — see rationale below. Also usable directly for BLF export if a specific tool in the pipeline (e.g. Vector CANalyzer) demands it. |
| `canmatrix` | 1.2 (Feb 2025) | DBC ⇄ other-format conversion utility, if the DBC ever needs to move between tool ecosystems | Not on the critical logging path; keep in the toolbox for DBC maintenance tasks. |
| `crccheck` (PyPI) | 1.3.1 — **or** a hand-rolled 256-entry CRC-16 table (≈10 lines, no dependency) | CRC over each *framed packet* (a batch of compressed frames), not per individual CAN frame | Either is fine; the hand-rolled table removes one more dependency from a path that must be testable and demonstrable with no hardware present. Do not add `crccheck` just to save 10 lines of code if minimizing dependencies matters more to your team. |
| `@mcap/core` (npm) | 2.2.1 | Read/write MCAP from a JS/Node context | Only needed if some tool in the pipeline (e.g. a future browser-side raw-archive inspector, or a Foxglove-based analysis workflow) needs MCAP access outside Python. Not required for the core pipeline given the ground station is Python. |
| Foxglove Studio (desktop app, free) | current | Ad-hoc visual inspection / scrubbing of MCAP archives post-session | Zero-integration-cost bonus of choosing MCAP as the archive format — point it at a `.mcap` file and get a scrubbable multi-signal viewer without writing any tooling. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `zstd` CLI (system package, from the `zstd` project) | Manually measure real compression ratio against an existing log before committing to numbers | PROJECT.md flags the 4:1–8:1 ratio as an *unverified assumption* — run `zstd -19 --ultra` and also lower levels against a real captured log file (both raw and after the custom domain encoder) before roadmap commits to a bandwidth budget. This is the single highest-value 30-minute research task available before Phase 1 planning locks in numbers. |
| `socat` or a local loopback pair (`socat -d -d pty,raw,echo=0 pty,raw,echo=0`) | Build/test the framing + serial layer without an RFD900x on hand | Matches the stated constraint "buildable, testable, and demonstrable with no radio present" — a `socat` PTY pair behaves like a real serial device for `pyserial`. |

## Installation

```bash
# Car side (Python, Raspberry Pi OS)
pip install zstandard cobs mcap pyserial

# Ground station (Python)
pip install zstandard cobs mcap pyserial websockets cantools asammdf python-can

# Ground station browser bundle (only new addition vs. existing can-dashboard/)
npm install uplot
# (existing `ws` dependency in can-dashboard/ is retired once server.js is ported to Python —
#  see Ground-station runtime section)
```

## Deep-Dive: Answers to the Seven Questions

### 1. Compression of CAN frame streams

**Verdict: hand-rolled domain encoder is primary; zstd is an optional, cheap second pass — not LZ4.**

- The delta-timestamp / ID-dictionary / payload-XOR design already decided in `PROJECT.md` is correct and is *not* something a generic library replaces — it is the mechanism that gets you to 5–8 bytes/frame, and no general-purpose compressor can match a hand-tuned domain transform at that granularity without per-message framing overhead eating the gain.
- On top of that stream, a zstd pass is worth adding because CPU is not the constraint at this scale: raw CAN traffic here is ~4,000 frames/s × ~24 bytes ≈ 96 KB/s, and even *after* the domain encoder the byte stream feeding zstd is small. Reference numbers found in research: LZ4 compresses at 500+ MB/s per core; zstd at level 1 is in a similar range, dropping into the tens-of-MB/s range only at the highest levels (19+). Either is 100–1000× more throughput than this workload needs on a quad-core Cortex-A72. **Confidence: MEDIUM** — no Cortex-A72-specific published number was found; the x86 reference figures (hundreds of MB/s to >1 GB/s) leave enormous headroom even assuming several-times-slower ARM performance per core.
- Because throughput is a non-issue, pick zstd over LZ4 for the *live radio link* specifically for ratio, since every byte counts against the ~220 kbit/s ceiling. Use the streaming compressor (`zstandard.ZstdCompressor().stream_writer(...)` or `.compressobj()` + explicit `FLUSH_BLOCK`), and flush on a batch cadence (e.g., every 20–50 ms or ~100–200 already-domain-encoded frames), not per individual CAN frame — flushing every frame reintroduces per-call framing overhead and defeats cross-frame redundancy capture, while a 20–50 ms batch window is invisible against the project's sub-second latency requirement.
- Consider a **trained zstd dictionary** (`zstandard`'s `train_dictionary`, built from a representative session capture) especially useful right after link (re)acquisition, when there isn't yet enough in-session repetition for the streaming compressor to have built up state. Dictionary gains are strongest on small (few-KB) inputs — exactly this project's per-batch size.
- For the **NVMe archive path**, compression is optional (durability, not bandwidth, is the driver there) but if used, LZ4 is the better fit: maximal throughput at minimal CPU cost matters more than ratio when you're writing continuously for hours and want compression to never be the reason a write stalls.
- **What NOT to do:** don't call zstd/LZ4 per individual 8-byte CAN payload. Per-call overhead (even a few bytes of frame header) at 4,000 calls/s dwarfs any 5–8 byte target budget. Always batch before compressing.

### 2. Serial framing over a lossy byte pipe

**Verdict: COBS + trailing `0x00` delimiter, CRC over the batched packet (not per CAN frame).**

- COBS beats SLIP and raw HDLC-style byte-stuffing here specifically because of the "resync after corruption, no assumption of message boundaries" requirement in `PROJECT.md`: COBS's structural guarantee is that a decoder scanning forward for the next `0x00` will always land on a valid frame boundary, with worst-case 1-byte-per-254-byte overhead. SLIP's escape-byte scheme is simpler but has no equivalent bounded-overhead guarantee and is more prone to cascading resync failure if an escape byte itself is corrupted mid-stream.
- Python: `cobs` (PyPI, 1.2.2) — C extension with pure-Python fallback, actively packaged, trivial API (`cobs.encode`/`cobs.decode`).
- **JS/Node: do not use the npm `cobs` package** — last published in 2014, effectively unmaintained. Since the ground-station recommendation below moves deframing into Python entirely, this is moot for the primary pipeline; if a JS deframer is ever needed (e.g., a browser-side raw stream inspector), hand-roll it — the algorithm is ~15–20 lines and this removes an abandoned dependency from a safety-relevant path.
- **CRC:** don't CRC every individual CAN frame — batch several domain-encoded, possibly-zstd-compressed frames into one packet, COBS-frame *that*, and CRC the packet. A CRC-32 per original CAN frame (4 bytes) would by itself exceed the entire 5–8 byte/frame compression budget; CRC-16 amortized over a multi-hundred-byte batch is negligible overhead either way. Research indicates CRC-16 gives ample Hamming-distance error detection at the packet lengths in play here, and is cheaper in both code size and (on non-hardware-CRC-accelerated ARM cores) compute than CRC-32. Use a small lookup-table CRC-16/CCITT — either via `crccheck` or hand-rolled (recommended, to avoid an extra dependency on a path that must run with no hardware present for testing).

### 3. Log file formats for CAN

**Verdict: MCAP as the primary on-car write path; MDF4/ASC/BLF as post-session export formats only.**

| Format | Crash-safe append? | Read by asammdf/CANalyzer/canmatrix/python-can? | Verdict |
|---|---|---|---|
| MCAP | **Yes** — append-only, chunked; readers recover all complete chunks even if the last one was truncated | No (needs a conversion step; readable by `mcap` lib, Foxglove Studio) | **Primary archive.** Purpose-built for this exact failure mode. |
| MDF4 (`.mf4`, ASAM MDF) | **No** — python-can's `MF4Writer` doesn't support append mode at all; MDF4 requires a finalization step, and while `asammdf` attempts best-effort recovery of "unfinalized" files on load, "not all finalization steps are supported" per its own docs | Yes — natively, by all of them | Use as a **post-session export**, generated in one shot from a complete MCAP file, never as the live write target. |
| Vector BLF | **Documented broken in append mode** — `hardbyte/python-can` issue #1751: `BLFWriter`'s append parameter does not take effect | Yes, if you're in the Vector CANalyzer/CANoe ecosystem | Same as MDF4: export-only, from a completed archive, if a team member specifically needs Vector-format files. |
| candump / ASC (`.log`/`.asc`) | Yes — plain text, appending is just writing more lines | Yes — ASC is CANalyzer-compatible; candump log is `can-utils`-compatible | Fine as a lightweight, human-readable *secondary* export (e.g. a live-tail or a decoded-subset dump) — not efficient enough (parse cost, disk size) as the sole full-rate archive over multi-hour sessions. |
| Plain CSV | Yes (append lines) | Universally, trivially | Same caveats as ASC, worse: loses type fidelity (everything is text), largest on-disk footprint of any option here. Fine for a human-readable decoded-signal export, wrong for the full-rate raw archive. |
| Custom hand-rolled binary | Yes, if you build the crash-safety in yourself | No — bespoke, needs a reader written by you | MCAP gives you this exact property already, with indexing and tooling for free — don't reinvent it unless there's a specific reason MCAP doesn't fit. |

### 4. Power-cut-safe writing on Linux/Raspberry Pi

**Verdict: ext4 (not F2FS) + append-only sequential writes + explicit batched `fdatasync`, never fsync-per-record.**

- **Filesystem:** ext4. F2FS's log-structured, checkpoint-based design is optimized for flash wear-leveling on SD/eMMC, where its sequential-write pattern meaningfully extends card life — but that's not this project's constraint (NVMe doesn't have SD-card-grade wear/write-amplification problems). Multiple sources agree F2FS is comparatively weaker under sudden power loss, and its fsck cannot run against a mounted filesystem (requires an initramfs-based repair step) — unnecessary operational risk to take on at a race weekend for a wear-leveling benefit this hardware doesn't need. Ext4's journal-replay crash recovery is the most tested option available.
- **Write pattern:**
  - Open the archive with `O_APPEND`; never seek backward and rewrite already-written bytes — this both matches MCAP's own append-only chunk design and avoids partial-write corruption of previously-good data.
  - Call `os.fdatasync(fd)` **explicitly**, on your own interval (e.g., every ~100–200 ms or after each MCAP chunk closes) — do not rely on Python's buffered-file or the OS page cache's default flush cadence. A normal process crash (not just a hard power cut) can lose everything sitting in userspace/libc buffers *and* everything in the page cache that hasn't been explicitly synced.
  - Use `fdatasync`, not `fsync`, for the steady-state per-chunk flush — it skips the metadata journal commit (file size/mtime) unless that metadata is needed to read the data back correctly, which is cheaper per call at the cadence this project needs. A full `fsync` (or an explicit metadata flush) is still worth doing once, at controlled points — e.g., when a session file is closed/rotated — so the final file size and directory entry are durable too.
  - Batch the flush interval deliberately: too frequent (e.g., every record at 4,000/s) turns the syscall overhead itself into a bottleneck; too infrequent widens the data-loss window on a power cut. A ~100–200 ms cadence bounds worst-case loss to well under a second of driving data while keeping syscall overhead negligible against a ~4,000 Hz write rate.
  - **Confidence: HIGH** on the ext4-over-F2FS call and the append-only/explicit-fdatasync pattern (well-established Linux practice, not project-specific). **Confidence: MEDIUM** on the specific flush-interval numbers — validate empirically once real hardware and a real vibration/power-cycle test are available.

### 5. Ground-station runtime: Python vs. Node.js

**Verdict: Python. Decisively, not a close call.**

The deciding fact: **there is no viable, actively-maintained JS/Node equivalent of `cantools` for DBC decoding.** DBC decode must happen in Python. Given that constraint, the only real question is which language hosts the WebSocket-serving/display layer — and the answer is: also Python, for one reason that outweighs "the existing dashboard is Node": the browser-facing piece of the *existing* stack (`can-dashboard/server.js`) is a thin WebSocket + static-file server, on the order of ~20 lines using the `ws` package. Porting that to Python's `websockets` library (17.0, actively maintained, asyncio-native) is low-cost, and doing so collapses the entire ground-station pipeline — serial read → COBS deframe → zstd decompress → cantools DBC decode → alarm evaluation → WebSocket broadcast — into **one Python process**, eliminating the exact structural flaw `PROJECT.md` calls out about the current architecture ("logger and dashboard must live in the same process tree on the same machine," via a stdout→stdin pipe). One process, one language, no cross-language IPC, one runtime to install and supervise on the pit laptop.

`dashboard.html` itself (vanilla JS + whatever charting library) is **retained essentially unchanged** — the browser talks WebSocket regardless of what serves it, so this is not a frontend rewrite, only a ~20-line backend port.

**Plotting library: `uplot`, not Plotly.js or Chart.js.** For a scrolling multi-signal strip-chart updating at 10–20 Hz over multi-hour sessions, uPlot's canvas-direct rendering measurably beats both in CPU and memory (see Core Technologies table above for the cited benchmark: ~10% CPU/12 MB vs. ~40%/77 MB for Chart.js at the same streaming workload). Plotly.js is the wrong tool for this specific job — its strengths (statistical chart types, 3D, interactive export UI) are irrelevant to a real-time strip chart, and its overhead is unjustified at this update rate over a multi-hour session where memory growth/jank is the actual risk, not chart sophistication.

**Feed pattern:** downsample to the target 10–20 Hz *inside the Python decode process*, before anything crosses the WebSocket — do not push a message per raw CAN frame to the browser (4,000/s is far beyond anything perceptually useful on a chart and would waste both link and render budget locally, even though this is all localhost/LAN-side, not the radio). Batch a tick's worth of signal updates into one WebSocket message; feed uPlot via its append/`setData` pattern into a fixed-size ring buffer per signal on the client, dropping data older than the configured scroll window.

**What NOT to use:** don't attempt to keep decode in Python while also keeping a live JS re-implementation of any part of DBC scaling/decoding "for speed" — there is no meaningful performance case for it at 10–20 Hz display rates, and it creates two sources of truth for signal math that will drift as the DBC evolves.

### 6. Serial/radio interfacing

- **pyserial** (3.5) for `/dev/ttyUSB0` (or wherever the RFD900x enumerates) on both ends — standard, low-risk, already implicit in this project's Python-first stack.
- **RFD900x / SiK firmware** is a transparent serial pipe: bytes in one end come out the other, with FHSS and (optionally) Golay 12/24 forward error correction (`ECC=1`) handled at the radio layer. **Recommend `ECC=0`** (leave FEC off): ECC halves usable air-rate throughput in exchange for correcting up to a 25% bit error rate within each 12-bit block — but this project has already made the explicit architectural decision (`PROJECT.md`, "Live link is lossy and unacknowledged") to drop rather than recover corrupted live-link data, with the local NVMe archive as the completeness guarantee. Spending half the link's throughput budget protecting frames you're willing to lose anyway is the wrong trade; put that throughput back into the compressed-frame budget instead. The COBS+CRC framing layer already gives you clean detection-and-resync for whatever *does* get corrupted.
- `MAVLINK`-framing mode (an SiK firmware option) is irrelevant here — that's ArduPilot-specific packet alignment, not applicable to this project's own framing.
- **Flow control:** RFD900x supports RTS/CTS in hardware if wired; enable it if the wiring supports it so the module can backpressure the Pi's UART instead of silently dropping bytes when its internal TX queue saturates. If RTS/CTS isn't wired, keep the application's write rate under the configured air rate with margin — the ~40% headroom already established in `telemetry_conversation.md` (130–160 kbit/s average / ~220 kbit/s peak against ~200–250 kbit/s usable) provides exactly this cushion, and local UART/radio-buffer overflow (not RF propagation loss) is the more likely source of silent data loss on a link run near saturation.
- **Confirm empirically once hardware arrives:** the ~200–250 kbit/s usable-throughput figure at 500 kbit/s air rate is a planning number from the existing RF analysis, not yet measured against this specific radio pair and antenna setup — flag as a pre-roadmap validation item alongside the compression-ratio measurement.

### 7. Log sync car-to-pit

**Verdict: `rsync` over SSH, triggered by a network-availability hook — not Syncthing, not rclone.**

- This is a one-directional (car → pit laptop), two-node, occasional-connectivity pull of *completed* session archives — precisely rsync's native use case: delta-transfer, resumable, decades of production hardening, and no daemon required beyond `sshd` (which you likely want on the car anyway for admin access).
- **Syncthing** is built for continuous, bidirectional, multi-device sync with conflict resolution — none of which this system needs, and all of which adds unjustified surface area: a persistent background service, discovery/relay infrastructure, and a device-pairing step, for a two-machine one-direction pipeline on a tight pre-season timeline.
- **rclone**'s value is a unified interface across dozens of cloud/object-storage backends. There's no cloud target here — local Wi-Fi/Ethernet only — so it adds nothing rsync doesn't already do more simply for this case.
- **Trigger:** a small script on the pit laptop invoked either by a NetworkManager `dispatcher.d` hook (fires when the car's link/SSID comes up) or a lightweight polling loop (reachability check every few seconds while at the track) that runs `rsync -av` pulling only new/changed files from the car.
- **Critical detail specific to this project:** the car-side archive file is being actively appended (MCAP chunk writer) during a run. **Do not sync mid-session** — trigger the pull only after a session file is closed and durably flushed (e.g., the logger writes a companion `.done` marker file after finalizing and `fdatasync`-ing the archive), so rsync only ever transfers complete, stable files rather than racing the writer or transferring a truncated in-progress chunk.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Live-link generic compressor | zstd (`zstandard`) | LZ4 | LZ4 wins on raw speed, but at ~96 KB/s raw / a few KB/s post-domain-encoding, speed is never the bottleneck on a Cortex-A72; zstd's better ratio is the only thing that matters for the radio link specifically. (LZ4 remains the better call for the *archive* path, where throughput-per-CPU-cycle matters more than ratio — see Q1.) |
| Serial framing | COBS | SLIP | SLIP is simpler but lacks COBS's bounded-overhead, guaranteed-resync-on-next-delimiter property, which is the specific requirement ("resync after corruption") called out in `PROJECT.md`. |
| Serial framing | COBS | HDLC-style bit/byte stuffing with explicit frame-length fields | Length-prefixed framing is fragile on a lossy link: if the length field itself is corrupted, the decoder can desync for the rest of the stream until it gets lucky. COBS's delimiter-scan resync doesn't have this failure mode. |
| Archive format | MCAP | Custom hand-rolled append-only binary | A hand-rolled format can absolutely be made crash-safe, but MCAP already solves this (with indexing, tooling, and two maintained language bindings) — reinventing it only makes sense if MCAP is found to have some project-specific dealbreaker during Phase 1 spike work. |
| Archive format | MCAP | MDF4 as the live write target | MDF4 requires finalization; `MF4Writer` in python-can doesn't support append at all. Wrong tool for a target that must survive being killed mid-write. |
| Filesystem | ext4 | F2FS | F2FS's SD-card wear-leveling advantage doesn't apply on NVMe, and multiple sources flag it as comparatively weaker under sudden power loss with a more awkward repair story (needs a mounted-off fsck). |
| Ground-station runtime | Python (single process) | Node.js hosts the browser layer, Python only does decode, bridged by IPC (stdout pipe, socket, or message queue) | Possible, and strictly better than today's coupling if Python-vs-Node stays split — but adds a process boundary and a serialization/IPC contract for no benefit once you've accepted the ~20-line server.js port is cheap. Only reconsider this if the ground-station box needs to run the decode pipeline and the browser-facing server on separate machines, which nothing in `PROJECT.md` currently calls for. |
| Log sync | rsync over SSH | Syncthing | Syncthing solves a harder problem (continuous bidirectional multi-device sync) than this project has; the added daemon/discovery/pairing surface isn't earned here. |
| Log sync | rsync over SSH | rclone | rclone's value is cloud-backend abstraction; there is no cloud backend in this design. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| npm `cobs` package (0.2.1) | Last published 2014; effectively unmaintained | Hand-roll (~15–20 lines) if a JS-side deframer is ever needed; moot if the ground station is Python per this document's recommendation |
| `BLFWriter` (python-can) as the *live* write target | Append mode is a documented open bug (issue #1751) — it silently doesn't do what the name says | MCAP live, BLF as a post-session export if a Vector-tool user specifically needs it |
| `MF4Writer` (python-can) as the *live* write target | Doesn't support append mode at all; MDF4 needs a finalization step vulnerable to being interrupted by exactly the power-cut scenario this project must survive | MCAP live, MDF4 (via `asammdf`) as a post-session export |
| CRC-32 per individual CAN frame | 4 bytes of overhead on a 5–8 byte/frame compression budget defeats the entire point of compressing | CRC-16 (or CRC-32) over the *batched packet*, amortized across many frames |
| Per-frame zstd/LZ4 calls (compress each 8-byte payload individually) | Per-call framing/header overhead dwarfs the payload at this granularity; also throws away cross-frame redundancy | Batch frames into ~20–50 ms windows, compress the batch |
| Fsync/fdatasync on every record at 4,000/s | Syscall overhead becomes the bottleneck; doesn't meaningfully improve on a well-chosen batch interval | Explicit `fdatasync` on a ~100–200 ms (or per-chunk) cadence |
| F2FS for the NVMe archive | Weaker sudden-power-loss story than ext4, plus an awkward unmounted-fsck repair requirement, for a wear-leveling benefit NVMe doesn't need as much as SD/eMMC does | ext4 |
| Leaving SiK `ECC=1` (Golay FEC) enabled | Halves usable throughput protecting data this project has already decided it's willing to lose on the live link | `ECC=0`; rely on the project's own COBS+CRC for corruption *detection* (not recovery) and the NVMe archive for completeness |
| Syncthing for car→pit sync | Solves continuous bidirectional multi-device sync — a harder, differently-shaped problem than a one-directional occasional pull of completed files | rsync over SSH, triggered on network availability |
| Reimplementing DBC decode logic in JS "for the frontend" | No maintained JS DBC-decode library exists; a hand-rolled one creates a second, inevitably-diverging parser of `epbr2026_DBC_v1.0.dbc` | Keep all decode in Python (`cantools`); browser only ever receives already-decoded, already-scaled signal values |

## Stack Patterns by Variant

**If the RFD900x hasn't arrived yet (current state per `PROJECT.md`):**
- Use a `socat` PTY loopback pair, or the existing loopback/UDP link abstraction already planned in `PROJECT.md`, to exercise the full compress → frame → transport → deframe → decompress → decode chain end to end.
- Because COBS framing and the domain compressor don't know or care what carries the bytes, none of the code above the transport abstraction needs to change when the real radio shows up.

**If a future receive site needs the MCAP archive without Python available:**
- Use `@mcap/core` (npm, 2.2.1) or Foxglove Studio directly — both can read MCAP without touching the Python decode pipeline.

**If the compression-ratio validation (see Development Tools) comes back materially worse than 4:1–8:1 on real noisy-analog-channel traffic:**
- Revisit whether some analog channels should be excluded from the live link entirely (send only on request / at a slower rate) rather than trying to compress noise-dithered low bits further — this is a channel-selection problem, not a compressor problem, and no library swap here fixes it.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `zstandard` 0.25.0 | Python ≥3.9 | Confirm Raspberry Pi OS's shipped Python version meets this before pinning (Bookworm ships 3.11, which is fine). |
| `websockets` 17.0 | Python ≥3.11 | This is a *higher* floor than `zstandard`'s — if the ground-station laptop runs an older Python, this is the binding constraint on the whole stack's minimum version. |
| `mcap` 1.4.0 | Python ≥3.7 | No conflict with the above; not the constraint. |
| `uplot` 1.6.32 | Any modern evergreen browser (Canvas 2D) | No Node/npm build pipeline strictly required — can be used via a plain `<script>` tag, consistent with the existing "vanilla HTML" dashboard approach. |
| Python's stdlib `compression.zstd` (new in 3.14) | Python ≥3.14 | **Not usable yet** for this project unless the ground-station/Pi Python is upgraded to 3.14+; noted here only as a future migration path once that's the default — don't design around it now. |

## Sources

- PyPI JSON API (`pypi.org/pypi/<pkg>/json`) — direct version/requires-python lookups for `zstandard`, `lz4`, `cobs`, `python-can`, `asammdf`, `cantools`, `pyserial`, `crccheck`, `mcap`, `pyzstd`, `websockets` — HIGH confidence (authoritative registry data)
- npm registry API (`registry.npmjs.org/<pkg>`) — direct version/publish-date lookups for `cobs`, `uplot`, `plotly.js`, `chart.js`, `ws`, `serialport`, `@mcap/core` — HIGH confidence
- WebSearch: python-zstandard docs/readthedocs, GitHub (`indygreg/python-zstandard`, `klensy/python-zstandard`) — streaming API and throughput claims — MEDIUM confidence (general benchmark figures, not Cortex-A72-specific)
- WebSearch: `cobs-python` (GitHub `cmcqueen/cobs-python`), PyPI `cobs`, npm `cobs` — HIGH confidence on library existence/maintenance status, staleness date directly observed
- WebSearch: RFD900x / SiK firmware — RFDesign user manuals (files.rfdesign.com.au), ArduPilot SiK Radio Advanced Configuration docs (ardupilot.org) — MEDIUM confidence (manufacturer/community docs, not independently benchmarked by this research)
- WebSearch: python-can docs (`python-can.readthedocs.io`) and GitHub issues (`hardbyte/python-can` #1751 BLF append bug, #554 MDF4 support PR) — HIGH confidence (primary-source bug tracker and official docs)
- WebSearch: asammdf GitHub issue #11 (streaming/append support), asammdf docs — MEDIUM confidence (community discussion, confirms partial/limited finalization recovery but not exhaustively verified against this project's failure mode)
- WebSearch: MCAP official docs and blog (`mcap.dev`, `foxglove.dev`) — HIGH confidence (primary source, format explicitly designed for the append-only/crash-recovery property this project needs)
- WebSearch: ext4 vs. F2FS power-loss behavior — LeMaker blog, Gentoo/kernel mailing list discussions, Kevin Locke's SD card storage writeup — MEDIUM confidence (community/blog sources broadly agree, no single authoritative benchmark found)
- WebSearch: fsync/fdatasync semantics — Linux man pages (`man7.org`, `linux.die.net`), PostgreSQL fsync-failure discussion — HIGH confidence for the man-page API semantics; MEDIUM for the applied append-log guidance (drawn from general database/WAL practice, not CAN-logging-specific)
- WebSearch: uPlot vs. Chart.js/ECharts/Plotly streaming performance — uPlot's own GitHub README/benchmarks page, official demos (`leeoniya.github.io/uPlot`) — MEDIUM confidence (benchmark figures originate from the library author's own published comparison, not independently reproduced by this research)
- WebSearch: syncthing vs. rsync vs. rclone comparisons — Slant, SourceForge comparison pages, vendor/community writeups — MEDIUM confidence (aggregated community opinion, consistent across multiple independent sources)
- CRC-16 vs. CRC-32 cost — Hackaday "Picking a CRC," CMU embedded-networks CRC paper (Koopman) — MEDIUM confidence (general embedded-systems guidance, not benchmarked on this project's specific ARM target)

---
*Stack research for: FSAE vehicle CAN telemetry & logging (car-side compression/logging + ground-station decode/display/sync)*
*Researched: 2026-07-30*
