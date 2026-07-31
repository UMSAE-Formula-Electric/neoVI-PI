# Architecture Research

**Domain:** Split car/ground-station CAN telemetry and archival system over a lossy 900 MHz radio link (Raspberry Pi CM4 car side, Python ground station)
**Researched:** 2026-07-30
**Confidence:** HIGH on the structural patterns (fan-out queue policy, layered protocol separation, link abstraction, GIL-suitability reasoning from documented CPython semantics) — these follow directly from well-established practice and this project's own settled decisions. MEDIUM on specific numeric parameters (queue depths, keyframe cadence, byte-budget deltas) — directionally correct, calibrate against Phase 0/1 measurements. LOW/flagged explicitly anywhere a claim isn't grounded.

This document assumes and builds on `.planning/research/STACK.md` (MCAP, COBS, ext4+fdatasync, Python ground station, zstd) and `.planning/research/PITFALLS.md` (compression-ratio risk, stateful-desync risk, bufferbloat risk, archive-durability risk, GIL/frame-loss risk) as settled. It does not re-litigate those; it answers *how the pieces are wired together*.

## Standard Architecture

### System Overview

```
┌───────────────────────────── CAR (Raspberry Pi CM4) ─────────────────────────────────────┐
│                                                                                             │
│   ┌────────────────┐                                                                       │
│   │ neoVI hardware  │  python-ics / vspyx (ctypes — releases GIL during blocking read)      │
│   └───────┬────────┘                                                                       │
│           │ poll                                                                           │
│   ┌───────▼─────────────────┐   thin, does nothing but read+timestamp+fan-out              │
│   │   CAPTURE THREAD         │                                                              │
│   └──────┬───────────┬───────┘                                                              │
│          │           │  non-blocking, structurally can't backpressure each other            │
│    ┌─────▼─────┐ ┌───▼──────────┐                                                           │
│    │ ARCHIVE   │ │ TELEMETRY    │  queue.Queue(maxsize=N)   deque(maxlen=N)                 │
│    │ QUEUE     │ │ QUEUE        │  (never-drop, alarm-on-full)  (drop-OLDEST on full)        │
│    └─────┬─────┘ └───┬──────────┘                                                           │
│          │           │                                                                      │
│   ┌──────▼──────┐ ┌──▼─────────────────────────────────────────────────┐                   │
│   │ ARCHIVE      │ │ TELEMETRY PIPELINE (own thread(s))                 │                   │
│   │ WRITER       │ │  encode (per-ID delta/XOR + keyframe) → batch      │                   │
│   │ (MCAP,       │ │  → [optional zstd] → COBS + CRC-16 → LEAKY-BUCKET  │                   │
│   │ batched      │ │  SHAPER (drop-oldest, paced drain) → Link.send()   │                   │
│   │ fdatasync)   │ └──────────────────────┬──────────────────────────┘                   │
│   └──────┬───────┘                        │                                                │
│          │                        ┌───────▼────────┐                                       │
│          ▼                        │  LINK (swappable)│  Loopback / UDP / Serial(RFD900x)    │
│   NVMe (ext4, append-only)         └───────┬────────┘                                       │
└─────────────────────────────────────────────┼──────────────────────────────────────────────┘
                                               │  lossy, unacknowledged byte pipe
┌──────────────────────────────────────────────▼───────────────── GROUND STATION (Python) ───┐
│                                       ┌────────────────┐                                     │
│                                       │  LINK (mirror)  │                                     │
│                                       └───────┬────────┘                                     │
│                              ┌────────────────▼─────────────────┐                            │
│                              │ DEFRAME (COBS decode + CRC verify) │                           │
│                              └────────────────┬─────────────────┘                            │
│                              ┌────────────────▼─────────────────┐                            │
│                              │ DECOMPRESS (optional zstd)         │                           │
│                              └────────────────┬─────────────────┘                            │
│                              ┌────────────────▼─────────────────┐                            │
│                              │ RECONSTRUCT (per-ID state,         │                           │
│                              │ seq-gap detect, XOR-undo,          │                           │
│                              │ staleness flag)                    │                           │
│                              └────────────────┬─────────────────┘                            │
│                              ┌────────────────▼─────────────────┐                            │
│                              │ DBC DECODE (cantools)              │                           │
│                              └────────────────┬─────────────────┘                            │
│                              ┌────────────────▼─────────────────┐                            │
│                              │ STATE STORE (signals + stale flag) │                           │
│                              └────────────────┬─────────────────┘                            │
│                              ┌────────────────▼─────────────────┐                            │
│                              │ WEBSOCKET (asyncio `websockets`,   │                           │
│                              │ 10–20 Hz downsample tick)          │                           │
│                              └────────────────┬─────────────────┘                            │
│                                       ┌────────▼────────┐                                    │
│                                       │ dashboard.html    │  uPlot, gap-honest rendering        │
│                                       │ (browser)          │                                    │
│                                       └───────────────────┘                                    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Two paths share only the capture step. From the fan-out point on, they are **structurally independent** — different queue types, different threads, different failure semantics, different destinations (disk vs. radio). This independence is the whole point: it is what makes "the lossy consumer can never backpressure the durable one" true by construction rather than by convention.

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|-------------------------|
| Capture thread | Poll hardware, timestamp, fan out to two queues, nothing else | `threading.Thread`, minimal per-call work |
| Archive queue | Absorb writer jitter without ever dropping under normal operation | `queue.Queue(maxsize=N)`, `put_nowait` |
| Telemetry queue | Bound live-path latency; structurally cannot block capture | `collections.deque(maxlen=N)` |
| Archive writer | Durable, crash-safe, append-only write to NVMe | MCAP writer + batched `os.fdatasync` |
| Domain encoder | Per-ID delta timestamp + XOR + keyframe scheduling | Pure-Python, per-ID state dict |
| Batcher | Assemble N encoded frames + header into one unit | Fixed struct header + concatenated CFRs |
| Framer | COBS-encode + CRC-16, byte-level resync guarantee | `cobs` package + small CRC table |
| Shaper | Leaky-bucket pacing + drop-oldest under saturation | `deque` + monotonic-clock-paced drain loop |
| Link | Swappable byte pipe abstraction | `Protocol`/ABC with Loopback/UDP/Serial impls |
| Deframer (ground) | Reverse of framer; discard corrupt/unrecoverable batches | `cobs.decode` + CRC check |
| Reconstructor (ground) | Per-ID state, gap detection, staleness | Mirrors encoder's per-ID state shape |
| DBC decoder (ground) | Raw bytes → scaled signal values | `cantools` |
| State store (ground) | Current value + staleness per signal | `dict`, in-memory, no history needed server-side |
| WebSocket server (ground) | Downsample + broadcast to browsers | `websockets`, asyncio |
| Dashboard | Render, including honest gaps | `dashboard.html` + `uplot` |

## Recommended Project Structure

```
car/
├── capture/
│   └── capture.py          # hardware poll → fan-out to archive_queue + telemetry_queue
├── archive/
│   ├── writer.py            # MCAP append, batched fdatasync, session-epoch header, canary write
│   └── session.py           # monotonic_start / wall_clock_start_estimate pairing (Q7)
├── telemetry/
│   ├── dictionary.py        # static ID→index table generated from the DBC, versioned
│   ├── encoder.py           # per-ID delta/XOR + keyframe cadence
│   ├── batcher.py           # batch header assembly, optional zstd pass
│   ├── framer.py            # COBS + CRC-16
│   └── shaper.py            # leaky-bucket queue + paced drain to Link
├── link/
│   ├── base.py               # Link Protocol/ABC
│   ├── loopback.py           # in-memory + PTY variants
│   ├── udp.py
│   ├── serial.py             # RFD900x via pyserial
│   └── ratelimited.py        # composable throttle+drop wrapper for testing
└── main.py                   # wiring: capture → {archive path, telemetry path} → link

groundstation/
├── link/                     # mirrors car/link — same abstraction, receiving side
├── deframer.py
├── decompressor.py
├── reconstruct.py            # mirrors telemetry/encoder.py's per-ID state shape
├── decode.py                 # cantools DBC decode
├── state.py                  # state[channel][id].signals + staleness computation
├── server.py                 # asyncio websockets server (replaces can-dashboard/server.js)
└── static/
    └── dashboard.html        # retained, + uplot integration

shared/
├── protocol.py                # CFR / batch header struct layout — single source of truth,
│                               #   used by both car/telemetry/encoder.py and
│                               #   groundstation/reconstruct.py so the wire format
│                               #   cannot silently drift between the two ends
└── dbc_dictionary.py          # generates the static ID dictionary + dict_version;
                                #   run at build time on both car and ground station
                                #   from the SAME epbr2026_DBC_v1.0.dbc file
```

### Structure Rationale

- **`car/link/` and `groundstation/link/` share one interface (`shared` or a small installable package) but are physically separate implementations** — the car never imports ground-station code and vice versa; they are two different machines that happen to agree on a wire format, not two halves of one process.
- **`shared/protocol.py` is the load-bearing file for the crux problem (Q3 below).** Both the encoder and the reconstructor must agree byte-for-byte on the CFR/batch layout; keeping it in one file (imported by the car package, and copied/pinned or packaged for the ground station) prevents the classic distributed-system bug of the two ends drifting apart after a "quick fix" on one side only.
- **`telemetry/` and `archive/` are siblings, not layers** — reinforces that neither depends on the other; `archive/` has zero knowledge that `telemetry/` exists.

## Architectural Patterns

### Pattern 1: Fan-out with divergent, structurally-lossless-vs-lossy queues (answers Q1)

**What:** One capture step feeds two independent queue types with opposite overflow semantics, chosen so that overflow behavior is a property of the data structure, not application logic that could be gotten wrong under pressure.

- **Archive queue — `queue.Queue(maxsize=N)`, fed with `put_nowait()`.** Sized generously in *time* (e.g., ~10 s of frames at combined 4,000 fps ≈ 40,000 entries) — large enough that only a genuine fault (disk stall, filesystem gone read-only) can fill it, not routine scheduling jitter. On `queue.Full`, the frame is dropped **and this is treated as a critical, loudly-surfaced fault condition** (matches the Active-scope requirement to surface hardware/decode errors instead of swallowing them) — never a silent, expected-case drop. This queue's entire purpose is to *never* need its overflow path in normal operation.
- **Telemetry queue — `collections.deque(maxlen=N)`, fed with `.append()`.** A `deque` with `maxlen` set silently evicts the oldest element when a new one is appended past capacity — this is the correct built-in primitive for "drop-oldest, never block, never raise." Sized in *time* to match the live-path latency budget (Q5), not in frame count directly (compute `N` from that budget ÷ average per-frame interval, re-derived once real per-ID rates are measured).

**Why the lossy consumer structurally cannot backpressure the durable one:** the capture thread's fan-out step calls two independent non-blocking operations (`put_nowait` and `deque.append`), neither of which can ever block waiting on the other's state, and neither of which can raise in a way that stops the other from executing. There is no shared lock, no shared buffer, and no code path where "telemetry queue is full" has any bearing on whether the archive queue accepts the frame — the guarantee comes from picking primitives for which blocking/backpressure is not merely discouraged but *not an available code path*.

**When to use:** Any time one source must serve a must-not-lose consumer and a must-not-block consumer simultaneously.
**Trade-offs:** The archive queue's generous sizing costs memory (40k frames × ~30–40 bytes ≈ 1.5 MB — trivial on a CM4) in exchange for tolerating multi-second writer stalls without loss. The `deque(maxlen=N)` telemetry queue means genuinely-fresh data always displaces stale queued data — correct for a live view, wrong if ever reused somewhere completeness matters.

**Example:**
```python
archive_q: queue.Queue = queue.Queue(maxsize=ARCHIVE_QUEUE_DEPTH)   # ~10s of frames
telemetry_q: collections.deque = collections.deque(maxlen=TELEMETRY_QUEUE_DEPTH)  # ~250ms of frames

def on_frame(frame):
    try:
        archive_q.put_nowait(frame)
    except queue.Full:
        archive_fault_counter.increment()
        log_critical("archive queue full — durability guarantee at risk")
    telemetry_q.append(frame)   # never raises, never blocks, silently evicts oldest if full
```

### Pattern 2: Thread-per-stage, GIL-aware, no multiprocessing by default (answers Q2)

**What:** A small, fixed number of OS threads (`threading`), each doing minimal pure-Python work punctuated by calls into C extensions / syscalls that release the GIL — capture, archive-writer, telemetry-encoder, shaper/sender. No `multiprocessing`, no `asyncio` on the car side.

**Where the GIL actually could bite, and why it mostly doesn't here:**

CPython's GIL only becomes a real bottleneck when multiple threads spend significant time executing *pure Python bytecode concurrently*. Every stage in this pipeline is dominated by either (a) blocking calls into C extensions that release the GIL for their duration, or (b) genuinely small amounts of pure-Python work per call:

| Stage | Dominant cost | GIL behavior |
|---|---|---|
| Hardware poll (`python-ics`/vspyx) | Blocking read into vendor SDK via ctypes | `ctypes.CDLL` calls release the GIL around the foreign call by default in CPython — the wait for hardware does not hold up other threads |
| Archive write (MCAP + fdatasync) | File I/O syscall, optional LZ4 compress | `os.fdatasync`/file writes release GIL for the syscall; `zstandard`/`lz4` C extensions release GIL during `compress()` |
| Domain encoder (delta/XOR/keyframe) | Pure Python: dict lookup, struct pack, XOR bytes | **Does not release the GIL** — this is the one stage that's actually pure-Python CPU work |
| Serial TX | `write()` to a file descriptor | Releases GIL for the syscall |

The encoder is the only stage that holds the GIL while doing real work, so it's the only candidate for GIL contention. At an estimated low single-digit microseconds per frame for a dict lookup + `struct.pack` + byte XOR (order-of-magnitude estimate, **not yet benchmarked on this Cortex-A72 — MEDIUM confidence**), 4,000 frames/s costs on the order of 10–20 ms of actual CPU time per second — under 2% of one core. This is not a throughput problem. The real risk is *scheduling jitter*: CPython's default GIL switch interval is 5 ms (`sys.setswitchinterval()`), so if the encoder thread runs a tight loop without ever hitting a GIL-releasing call, it can in principle hold the GIL for up to that interval before yielding, momentarily starving the capture thread's own Python-level work (queue puts, tuple construction) — not the hardware read itself (which is off-GIL), but the bookkeeping around it. At 4,000 fps, a single 5 ms stall could mean ~20 frames sitting in whatever buffer sits beneath the capture thread (the SDK's own internal driver buffer) before being drained — this is exactly why the capture thread's own per-call work must stay minimal (Pitfall 6 already establishes this) and why encode work lives on a *separate* thread from capture, so a GIL-held encoder stall delays encoding, not capture.

**Verdict: Python threads are viable at 4,000 fps for this workload, conditioned on:**
1. Capture thread does the absolute minimum per call (read, timestamp, two non-blocking fan-out pushes) — never encode, never write, never touch the radio.
2. Encode/compress/write/send each run on their own thread, so a GC pause or a GIL-holding stretch in one never blocks another's ability to *drain its own queue*, even if it can't run its own CPU work that instant.
3. Preallocate buffers where practical (reduces GC pressure — Pitfall 6 already calls this out).

**Threads vs. multiprocessing vs. asyncio:**
- **Threads, not multiprocessing, for the car side.** Multiprocessing's benefit is true parallel CPU execution across cores — not needed here per the above estimate (the CPU-bound stage is a small fraction of one core). Its cost is real: IPC between processes (pipe/`multiprocessing.Queue`) adds serialization overhead and reintroduces exactly the backpressure-shape problem Pattern 1 solves, now across a process boundary instead of for free within one. Reserve multiprocessing as an **explicit escape hatch**: if the Phase 1 soak test (see Build Order) measures the encoder thread meaningfully starving capture, move *only* the encoder to its own process, still connected via the same drop-oldest `deque`-shaped queue (now `multiprocessing.Queue` with the same maxsize-based drop-oldest wrapper, since stdlib `multiprocessing.Queue` doesn't support `maxlen` natively and needs a small wrapper to replicate `deque`'s eviction behavior).
- **Not asyncio for the car side.** Neither `python-ics`/vspyx nor `pyserial` is asyncio-native; using asyncio here would mean wrapping every blocking call in `loop.run_in_executor` (i.e., a thread pool under the hood anyway) for no benefit — asyncio's win is scaling to many concurrent I/O waiters, not a fixed handful of pipeline stages.
- **Asyncio for the ground station, deliberately different from the car side.** `websockets` is asyncio-native and the ground station has a genuinely concurrency-shaped problem (interleave serial read, decode, and broadcast to a variable number of browser clients) — this is the profile asyncio is built for.

**Fallback if measurement proves Python insufficient:** Two escalating options, in order — (1) move only the domain-encoder's inner loop to a compiled extension (Cython, or a small Rust module via PyO3) while keeping everything else in Python, a surgical fix targeting the one stage that's actually pure-Python CPU work; (2) as a last resort, a standalone C/C++/Rust capture+encode binary writing into a shared-memory ring or Unix socket that the rest of the Python pipeline (archive writer, radio shaper) consumes unchanged. Given the order-of-magnitude estimate above (low single-digit % of one core), **this fallback is not expected to be needed and should not be pre-built** — it exists as a documented escape hatch triggered only if the Phase 1 soak test shows real frame loss correlated with encoder load rather than hardware/GC noise.

### Pattern 3: Layered, self-describing wire protocol with per-ID recoverable state (answers Q3 — the crux)

**What:** Six explicit layers, each with a narrow contract, so a lossy channel breaking one layer's assumptions doesn't cascade into the others.

```
capture (raw CAN frame)
  → wire record encode (CFR: id_index, seq, delta_t, payload)
  → per-ID stateful compression (XOR-vs-last, per-ID isolated)
  → batching (many CFRs + one shared header)
  → COBS + CRC-16 framing (batch-level, content-agnostic)
  → link transport (Loopback / UDP / Serial)
```

**The core problem:** XOR-against-last-frame compression means the decoder's correctness depends on holding the *same* "last payload" state as the encoder. On a link that drops frames by design (no ARQ, per `PROJECT.md`), a dropped frame silently desyncs that state — the next decoded value is wrong, not missing, which is worse for a system whose job includes limit alarms (PITFALLS.md Pitfall 2). The fix is four concrete mechanisms, all already implied by the question and made concrete here:

**1. Static ID dictionary, shipped out-of-band.** Built once from `epbr2026_DBC_v1.0.dbc` at build/deploy time (`shared/dbc_dictionary.py`, run identically on car and ground station from the same DBC file), not learned adaptively from the live stream. Fewer than 256 unique arbitration IDs on this bus (confirmed in `telemetry_conversation.md`) means a 1-byte index replaces a 4-byte ID. A `dict_version` byte (hash of the generated table) travels in every batch header — receiver refuses/flags decode if its local table's version doesn't match, rather than silently mismapping indices to the wrong IDs.

**2. Per-ID independent compression state.** `last_payload: dict[id_index, bytes]` and `last_seq: dict[id_index, int]`, keyed by `id_index`, not one running stream-compression state. A dropped frame for one ID never touches any other ID's state — this bounds the blast radius of any single loss to exactly the ID(s) present in the lost data.

**3. Per-ID sequence number for gap detection.** Each CFR carries a 1-byte, per-ID, wrapping sequence number. The reconstructor tracks the last-seen `seq` per ID; if the new frame's `seq` isn't `last_seq + 1`, a gap is declared for *that ID specifically* — the reconstructor marks it stale and **refuses to apply the XOR-undo against the (now known-stale) baseline**, rather than emitting a plausible-looking wrong value. This is the fast, cheap, immediate detection layer.

**4. Periodic per-ID keyframes.** Every ID periodically sends its *full* payload (not a delta) regardless of whether it changed — recommended cadence keyed to wall time per ID (e.g., once per second of that ID's own traffic) rather than a fixed frame count, since IDs on this bus range from single-digit Hz to several hundred Hz. This is the actual repair mechanism: it bounds the maximum time any ID can stay "stale" after a drop to roughly the keyframe interval, independent of whether a gap was explicitly detected.

Sequence-gap detection and keyframes are complementary, not redundant: gap detection gives an immediate "don't trust this" signal (cheap, but doesn't fix anything), keyframes give the actual fix on a bounded schedule. Together they satisfy the requirement precisely: bounded staleness, no silent garbage, no adaptive state to itself desync.

**Concrete packet layout:**

*Layer 1 — Compressed Frame Record (CFR), one per original CAN frame, variable length:*

```
byte 0:        flags        bit0 = KEYFRAME, bit1 = EXTENDED_ID, bits2–7 reserved
byte 1:        id_index     0–255, from the static dictionary
byte 2:        seq          8-bit, wraps, PER-ID (not global)
bytes 3–4:     delta_t_us   uint16, microseconds since this batch's base timestamp
                             (batch-relative, not frame-relative — see below)
byte 5:        trim_count   number of trailing zero bytes elided from the XOR delta
                             (0 if KEYFRAME — full payload follows)
bytes 6..N:    payload      KEYFRAME: full DLC bytes (0–8), verbatim
                             delta:   XOR(payload, last_payload[id_index]),
                                      trailing zero run removed per trim_count
```

*Layer 2 — Batch (the unit that gets optionally zstd-compressed, then COBS+CRC framed):*

```
Batch header (fixed, 13 bytes):
  byte 0:        protocol_version      bump on any wire-format change
  byte 1:        dict_version          static ID-dictionary hash/version
  bytes 2–9:     batch_base_timestamp  int64, monotonic ns since session start (see Q7)
  bytes 10–11:   frame_count           uint16
  byte 12:       batch_seq             uint8, wraps — batch-level loss detection,
                                        independent of per-ID seq
Body:
  frame_count × CFR records, back-to-back
```

Then: `[optional zstd, streaming dictionary, one flush per batch]` → append CRC-16 over the (post-zstd) bytes → COBS-encode `(payload + CRC)` as one unit → trailing `0x00` delimiter.

**Why timestamps are batch-relative, not a running delta-of-deltas:** the batch already carries one absolute (monotonic) `batch_base_timestamp`; each CFR's `delta_t_us` is relative to *that*, not to the previous frame's delta. A `uint16` (max 65,535 µs ≈ 65 ms) comfortably covers a 20–50 ms batch window (STACK.md's recommended flush cadence). This makes time reconstruction for surviving frames in a batch independent of whether an *earlier* batch was lost — only per-ID payload/sequence state needs to survive across batch loss, which is exactly the state Pattern 3 already isolates and repairs. Cross-batch running-delta timestamps would instead compound: losing one batch would desync every subsequent batch's absolute-time reconstruction too, which is a strictly worse failure mode than the payload-desync problem this whole pattern exists to solve.

**Receiver recovery flow, concretely:**
1. Scan for `0x00`, COBS-decode. On decode failure or CRC mismatch → discard the whole batch, increment "corrupt batch" counter (feeds link-health UI), do not attempt partial salvage — COBS's guarantee is *byte-level* resync at the next delimiter, not intra-frame recovery, and treating a corrupted batch as fully lost is the correct, simple response.
2. If `batch_seq` jumped by more than 1 → a whole batch was lost. No global action beyond incrementing a "batches lost" counter (staleness UI). Per-ID consequences are handled at step 3, naturally, because only IDs actually present in the lost batch will show a `seq` gap.
3. For each successfully-decoded CFR: check `seq` continuity for that `id_index`. Contiguous → apply XOR-undo (or accept full KEYFRAME payload), mark not-stale. Gap detected → mark that ID stale, hold its last-known-good value, and do **not** apply the delta against the now-untrusted baseline. Stale clears automatically the next time that ID sends a KEYFRAME (or, if the gap genuinely didn't affect that ID — i.e. it wasn't transmitted during the lost interval — the very next delta naturally continues the sequence and is trusted immediately).

**Budget honesty:** the sequence byte adds ~1 byte/frame beyond the original 5–8 byte/frame napkin estimate in `telemetry_conversation.md` — roughly a 12–15% overhead on that budget, in exchange for structural garbage-detection. This should be included explicitly in the Phase 0 compression-ratio measurement (PITFALLS.md Pitfall 1) rather than assumed free; if margin is tight after real measurement, the sequence byte and the flags/trim-count byte are the first candidates to fold together (e.g., pack `flags`+`trim_count` into a nibble each) — a refinement to make during Phase 2, not a reason to skip the mechanism.

**Trade-offs:** all four mechanisms cost a small, quantifiable, testable amount of bandwidth in exchange for eliminating an entire class of silent-wrong-value failures — given this system explicitly drives safety-relevant alarms (cell voltage, temperature), this trade is not close.

### Pattern 4: Content-agnostic, swappable Link abstraction (answers Q4)

**What:** A minimal interface that every layer above it (encoder, batcher, framer, shaper) depends on only through, so the same code runs unmodified against loopback, UDP, or the real radio.

```python
class Link(Protocol):
    def send(self, data: bytes) -> None: ...
    def recv(self, timeout: float | None = None) -> bytes | None: ...
    def bytes_pending_send(self) -> int | None: ...   # backpressure hint; None if unknown
    def close(self) -> None: ...
```

**Contract every implementation must uphold**, so nothing above needs to know which one is active:
- Bytes that *are* delivered arrive in the order sent (no reordering) — COBS's byte-scan resync assumes this for whatever does get through.
- No implementation is required to guarantee delivery — every layer above already assumes loss by design.
- `send()` always takes one complete framed blob (one COBS frame) per call — the Link never chunks or reassembles at a level above raw bytes.

**Implementations:** `LoopbackLink` (pure in-memory, zero OS dependency, for unit tests that must run with no radio and no vehicle hardware — this is explicitly Active scope); a PTY-backed loopback variant (via `socat`) for exercising the real serial code path without hardware; `UdpLink` (Wi-Fi stand-in — UDP's own inherent packet loss is a *feature* here, more faithfully modeling the real radio's behavior than TCP would); `SerialLink` (wraps `pyserial` against `/dev/ttyUSB0`, the RFD900x once purchased); `RateLimitedLink` (a composable wrapper around any other Link that throttles throughput and/or injects a configurable drop percentage — this is the vehicle for both the bufferbloat-saturation test (Pattern 5) and the frame-drop/garbage-detection test (Pattern 3), meaning those two test harnesses are not bespoke one-offs but the same reusable wrapper composed differently).

**Testing implications:** because Link is the only hardware-touching layer, the entire encode→batch→frame→deframe→decompress→reconstruct→decode chain is testable with zero hardware via `LoopbackLink`, satisfying the Active-scope test-suite requirement directly. The same test suite then runs unmodified against `RateLimitedLink` (saturation + loss simulation, no hardware) and finally `SerialLink` (bench, then on-car, once the RFD900x arrives) — proving the *software contract* is radio-agnostic at every stage, with only the final stage proving the *radio itself* behaves as assumed (PITFALLS.md Pitfall 5 draws exactly this distinction).

## Pattern 5: Leaky-bucket transmit shaping with drop-oldest, at the batch level (answers Q5)

**What:** SiK/RFD900x's anti-bufferbloat throttling is MAVLink-specific (reports buffer-fullness back to the sender via `RADIO` status packets) and does nothing for a non-MAVLink stream (STACK.md, PITFALLS.md Pitfall 3 both already establish this). The sender must enforce its own policy, at two points:

**Stage A — pre-batch frame buffering** (the `telemetry_q` from Pattern 1): bounds how many raw captured frames can be waiting to be encoded/batched before the oldest are silently dropped. Protects against the encoder itself falling behind — per Pattern 2's analysis this is unlikely to be the binding constraint, but the cost of this safety margin is zero (it's the same `deque(maxlen=N)` already needed for Pattern 1).

**Stage B — the outbound batch queue, the actually bufferbloat-relevant stage:** this sits downstream of the real bandwidth constraint (the radio), so it's where the design has to be deliberate.

- Maintain a `deque` of *pending batches* (not yet written to the Link), bounded both by count and by a running byte total.
- Before enqueueing a newly-assembled batch, compute `queued_bytes = sum(len(b) for b in pending) + bytes_pending_send()` (the latter from the Link's backpressure hint, e.g. OS TTY output buffer depth, when available). If `queued_bytes > link_rate_Bps × target_latency_budget_s` (target budget: a few hundred ms, per PITFALLS.md Pitfall 3), pop from the **left** (oldest) repeatedly until back under budget — `deque.popleft()`/`.append()` are both O(1) — before appending the new batch. This is the drop-oldest policy, applied at the point where the drop decision is actually actionable (before the bytes are handed to the OS/radio, since once `write()` is called on a FIFO byte pipe there is no way to retract already-queued bytes).
- **Pace the drain, don't just gate it.** A background sender loop drains one batch per tick from the pending queue and calls `Link.send()` at a `time.monotonic()`-scheduled interval computed from a configured `tx_rate` deliberately set *below* the link's true capacity (recommend ~60–70% of the measured/configured usable rate, consistent with the ~40% headroom already established in `telemetry_conversation.md` — i.e., don't run the shaper at the theoretical ceiling, leave slack for the estimate to be wrong). This paced drain, combined with the drop-oldest queue-budget check above, is the leaky-bucket: the bucket drains at a controlled, sub-capacity rate, and when input exceeds that rate long enough to breach the latency budget, old contents are discarded rather than the bucket being allowed to grow — never a plain FIFO that "eventually catches up."
- **Why RTS/CTS alone isn't sufficient:** if wired, hardware flow control is still worth enabling as a second line of defense against a specific corruption mode (an OS-buffer overflow mid-write breaking a COBS frame in the middle, which is worse than losing a whole frame cleanly) — but RTS/CTS only pauses/resumes a FIFO, it has no concept of "prefer newest." The drop-oldest decision must happen at the application layer, before `write()` is ever called, which is exactly Stage B's job.

**Measurement and proof (must be automated, not "tried it once before competition"):**
- Every batch already carries `batch_base_timestamp` (Pattern 3's header) — the ground station computes `local_receive_wall_clock − reconstructed_batch_time` for every successfully received batch, logging the full latency distribution, not just a mean.
- A synthetic saturation test, runnable with zero hardware via `RateLimitedLink` capped at the target usable rate: drive the pipeline with real/replayed CAN traffic at a deliberately excessive rate (e.g., 150% of the configured budget) and record **p50/p95/p99 end-to-end latency** of frames that do arrive, the drop rate, and — critically — whether p99 stays **flat** over the duration of a sustained-overload test rather than climbing. A flat p99 near the configured target-latency budget is the signature of a correctly-bounded leaky bucket; a climbing p99 over test duration is the signature of an unbounded/FIFO buffer — i.e., this test should be able to *fail* against a naive implementation, proving it actually exercises the mechanism rather than passing trivially.
- This test belongs in the same automated suite as the frame-drop/garbage test (Pattern 3) — both are compositions of the same `RateLimitedLink` wrapper, both runnable in CI with no hardware, both explicitly required by the Active-scope test-suite item.
- Also surface live shaper state on the transmit side itself (pending-queue depth, current measured drop rate, current paced send rate) via a debug log line or local status endpoint, so on-car testing can directly confirm the shaper is behaving as designed rather than inferring it only from receiver-side symptoms.

## Data Flow

### Durable Path (Capture → NVMe)

```
capture → archive_queue (never-drop, alarm-on-full)
        → archive writer (MCAP, batched fdatasync ~100–200ms)
        → NVMe (ext4, append-only, O_APPEND, periodic full fsync at session close)
```
No compression is required here for correctness (durability, not bandwidth, is the driver — STACK.md); LZ4 is acceptable if used, for throughput-per-CPU-cycle, never for ratio. This path has **zero dependency on the radio, the encoder, the framer, or the Link** — it must be fully buildable and bench-provable (including power-pull tests) before any telemetry-link code exists.

### Lossy Path (Capture → Dashboard)

```
capture → telemetry_queue (deque, drop-oldest)
        → encoder (per-ID delta/XOR + keyframe cadence, static ID dictionary)
        → batcher (batch header + frame_count CFRs, optional zstd)
        → framer (COBS + CRC-16)
        → shaper (leaky-bucket, drop-oldest, paced drain)
        → Link.send()
        ── lossy, unacknowledged wire ──
        → Link.recv() [ground station]
        → deframer (COBS decode + CRC verify; discard whole batch on failure)
        → decompressor (optional zstd)
        → reconstructor (per-ID XOR-undo, seq-gap detection, staleness flag)
        → DBC decode (cantools)
        → state store (value + unit + timestamp + stale flag, per signal)
        → WebSocket broadcast (10–20 Hz downsample tick, batched per tick)
        → dashboard (uPlot, gap-honest rendering — see Q6 below)
```

### Ground-Station Pipeline: Buffering Placement and Honest Gaps (answers Q6)

The ground station has no bandwidth constraint (localhost/LAN, "free" per STACK.md), so unlike the car side it should carry **minimal deliberate buffering** — the goal is forward-with-low-latency, not smooth-over-gaps:

- **Serial-read accumulator:** a small, fixed-size byte buffer (bounded by the max COBS-encoded batch size, itself bounded by the batch cadence/size chosen in Pattern 3) — just enough to hold one in-progress frame while scanning for the next `0x00`. Not time-based, not a source of latency.
- **State store is the only meaningful buffer:** it holds one *current* value + staleness metadata per signal — no server-side history. There is deliberately no "replay buffer" or windowed history on the ground station; that's the archive's job (post-session, via MCAP/Foxglove), not the live pipeline's.
- **Client-side uPlot ring buffer** (already specified in STACK.md) holds the scrolling display window — entirely client-side, per browser tab.
- **Per-client WebSocket send queue, bounded, drop-oldest for that client only.** If one browser tab is slow (backgrounded, laggy), its own bounded send queue should drop-oldest rather than let a slow consumer back up the shared decode pipeline for every other viewer — the same drop-oldest principle as the car side, applied at the one place on the ground station where an external, uncontrolled consumer (a browser) could otherwise apply backpressure to something upstream of it.

**Honest representation of missing data — concrete rules, not a UI afterthought:**
1. **No interpolation exists anywhere in the decode/state path.** This is a code-level constraint: nothing between `reconstruct.py` and the browser is permitted to synthesize or hold-forward a value across a detected gap.
2. On the periodic UI-push tick, for each signal check `now − last_update_ts` against an expected-period threshold (derived from the DBC's message cycle time if defined, else a configured default) — if exceeded, mark that signal `stale: true` in the outgoing WebSocket payload, in addition to (not instead of) the reconstructor's own seq-gap staleness flag from Pattern 3 (two independent staleness signals: "we detected a sequence gap" and "we simply haven't heard from this signal in a while," which can differ — e.g., a low-frequency ID with no gap yet is not the same condition as a dropped batch).
3. **uPlot series receive an explicit `null`/`NaN` for any tick where a signal has no fresh update**, rendering as a genuine visible break in the line rather than a flat interpolated segment connecting stale points — this is the concrete mechanism behind "we lost 300 ms here" rather than a smoothed-over line.
4. A link-health/staleness banner (aggregate lost-batch count, per-ID stale-count, last-batch-received-age) surfaces the *system-level* health independent of any single chart, so the pit engineer doesn't have to notice a gap on one specific plot to know the link is degraded — directly addresses PITFALLS.md Pitfall 3's "quietly stale, not visibly broken" failure mode.

## Time Synchronization Design (answers Q7)

**The constraint:** the CM4 has no battery-backed RTC (confirmed independently — a CM4 loses wall-clock time across every power cycle until it re-syncs), while the car and the pit laptop are physically separate machines with independently drifting clocks and no guaranteed network path between them once the car is on track.

**Design principle: monotonic time is load-bearing for correctness; wall-clock time is only for human-readable labeling — and this separation is deliberate, not incidental.**

- **`time.monotonic()` (`CLOCK_MONOTONIC`) is the primary timestamp source for everything the protocol actually needs to function correctly:** per-frame `delta_t_us` (Pattern 3), the leaky-bucket shaper's latency-budget math (Pattern 5), keyframe cadence timing, and the archive writer's internal record timing. Monotonic time cannot jump backward and is immune to NTP step-corrections mid-session, both of which would silently corrupt any logic computing deltas against it.
- **A session epoch is established once, at logger startup:** record `monotonic_start = time.monotonic()` and `wall_clock_start_estimate = time.time()` together, exactly once per session. This pairing is written into the MCAP archive's session metadata and into a low-rate "epoch beacon" — a small control batch broadcast at link-up and re-broadcast periodically (e.g., every 5–10 s) so a ground station attaching mid-session can still recover the pairing. Every subsequent `batch_base_timestamp` (Pattern 3) is monotonic-since-session-start — small values, cheaper to encode than absolute epoch time, which also reinforces the compression budget. Absolute wall-clock time is reconstructed only at the point of *display or export*: `wall_clock_start_estimate + (monotonic_now − monotonic_start)`.
- **Wall-clock sync options, in priority order:**
  1. **NTP in the paddock, pre-session, while on Wi-Fi/Ethernet near the pit** (`chrony` or `systemd-timesyncd` against the pit laptop or any venue-reachable NTP source). Sync once before the car goes on track; the modern SoC's internal oscillator is stable enough to free-run for the duration of a session without meaningful drift relative to this project's needs.
  2. **GPS + PPS, if budget allows.** The CM4 exposes a PPS-capable GPIO pin via the official IO board; `chrony` + `gpsd` against it gives microsecond-accurate time fully offline, independent of any network — the most robust option once the car leaves Wi-Fi range, and it's a nice-to-have hardware addition (not required for Phase 1) that would also unlock GPS position/lap timing later if ever wanted.
  3. **No sync available (cold boot, no network, no GPS):** `wall_clock_start_estimate` may simply be wrong. This is **acceptable by design** because nothing that affects data correctness depends on it — only the human-readable session label does, and that's fixable after the fact (cross-reference the pit laptop's own WebSocket-receive wall-clock log for the same session, the rsync transfer timestamp, or a manual operator correction at archive-pull time). **Never let wall-clock correctness become load-bearing for anything except labeling** — this is the design rule that makes the RTC-less CM4 a non-issue rather than a recurring operational risk.
- **Aligning the car archive with what the pit saw:** because both the archive's internal record timing and every batch sent over the radio derive from the *same* `monotonic_start` epoch on the *same* oscillator (the car's), post-session alignment between "what the archive says happened" and "what was streamed live" is a same-clock comparison — `monotonic_since_session_start` matches directly between the two, with no cross-machine clock-drift reconciliation needed for this pairing at all. The ground station's own wall-clock receive timestamp is recorded *separately*, purely to measure link latency (Pattern 5) and drive staleness display (Q6) — it is never used to correct or reinterpret the car's own signal timing. This separation of concerns is precisely what avoids needing any car↔laptop clock-sync protocol for data correctness — sync only matters for the low-stakes case of a human-readable date/time label.

## Anti-Patterns

### Anti-Pattern 1: One shared compression-state struct instead of per-ID isolation

**What people do:** implement delta/XOR compression as one running byte-stream state (like a generic LZ-style compressor would), rather than partitioned per CAN arbitration ID.
**Why it's wrong:** a single dropped frame corrupts the decode of every subsequent frame across every ID until a full resync — not just the ID that was actually affected. On a link explicitly designed to drop data, this turns an isolated, bounded problem into a system-wide one.
**Do this instead:** per-ID state dicts, as in Pattern 3. This should never be treated as an optimization to add later — it's the difference between a bounded and unbounded failure mode.

### Anti-Pattern 2: Same queue policy for the archive and live paths

**What people do:** reuse one FIFO queue implementation for both the durable and lossy consumers "to keep the code simple."
**Why it's wrong:** a plain FIFO under sustained overload doesn't drop data, it *delays* it — throughput looks fine while latency silently balloons (textbook bufferbloat, PITFALLS.md Pitfall 3). A live view fed by a FIFO under saturation shows old data with no indication it's old, which is worse than visibly dropping frames for a pit engineer acting on what they see.
**Do this instead:** Pattern 1's structurally different queue types (never-drop bounded queue for archive, drop-oldest ring buffer for telemetry) — the correctness of each path's *policy*, not just its code, must differ.

### Anti-Pattern 3: Adaptive, live-learned ID dictionary

**What people do:** build the arbitration-ID → index mapping on the fly from whatever IDs are first seen in the stream, since the encoder "already has to see every frame anyway."
**Why it's wrong:** reintroduces the exact stateful-desync problem Pattern 3 exists to solve, but for the dictionary itself — if the dictionary-building frame is lost, or the two ends build it in a different order, index N means a different arbitration ID on each side, silently.
**Do this instead:** a static, DBC-derived, versioned dictionary, generated once and shipped to both ends (Pattern 3, mechanism 1).

### Anti-Pattern 4: Letting the radio's write rate pace the capture thread

**What people do:** have the capture (or an early pipeline stage) call `Link.send()` directly, or otherwise let a blocking/slow radio write propagate backpressure upstream toward hardware polling.
**Why it's wrong:** reintroduces the coupling this whole architecture exists to break — a saturated or momentarily stalled radio should never be able to slow down reading from the CAN bus, which risks overflowing the hardware SDK's own internal buffer and losing data the archive path could otherwise have kept.
**Do this instead:** the shaper (Pattern 5) sits between the batcher and the Link specifically so nothing upstream of it ever calls a Link method directly; only the shaper's own paced-drain loop does.

### Anti-Pattern 5: Length-prefixed or content-aware framing

**What people do:** frame batches with an explicit length field instead of COBS's delimiter-scan approach, reasoning "we already know the batch size."
**Why it's wrong:** if the length field itself is corrupted (entirely possible on a noisy RF link), the decoder desyncs for the rest of the stream until it gets lucky finding a plausible-looking boundary — there's no bounded-worst-case recovery.
**Do this instead:** COBS + CRC (already settled in STACK.md) — the framing layer must remain content-agnostic; it's already the correct call here and this reasoning is why it should stay that way through implementation, not get "simplified" later.

## Integration Points

### External Libraries

| Library | Integration Pattern | Notes |
|---------|---------------------|-------|
| `python-ics` / `vspyx` | ctypes-wrapped hardware SDK; polled from the capture thread only | Releases GIL during blocking calls (standard `ctypes.CDLL` behavior) — do not call from any other thread |
| `mcap` | Streaming append-only writer, one instance owned by the archive writer thread | Never shared across threads; archive writer is the sole owner |
| `cobs` | Stateless encode/decode calls, used in both `framer.py` (car) and `deframer.py` (ground) | C extension with pure-Python fallback — verify which is active in CI vs. embedded target |
| `zstandard` | Streaming compressor with an explicit per-batch flush, optional trained dictionary | Must flush once per batch, never per-frame (STACK.md) |
| `pyserial` | Only inside `link/serial.py` — no other module imports it directly | Keeps the RFD900x-specific code isolated behind the `Link` interface |
| `cantools` | DBC decode, ground-station only | Never imported car-side per the architecture's decode-on-ground-station inversion |
| `websockets` | asyncio server in `groundstation/server.py`, replaces `can-dashboard/server.js` | ~20-line port per STACK.md; retains `dashboard.html` largely unchanged |
| `chrony`/`gpsd` (optional) | OS-level time sync, entirely decoupled from application logic | Application only ever reads `time.monotonic()`/`time.time()`; no direct dependency on the sync mechanism |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|----------------|-------|
| Capture ↔ Archive path | `queue.Queue` (never-drop) | One-directional; archive writer never signals back to capture |
| Capture ↔ Telemetry path | `deque(maxlen=N)` (drop-oldest) | One-directional; encoder never signals back to capture |
| Telemetry encoder ↔ Link | Only through the shaper (Pattern 5) | No direct calls from encoder/batcher/framer into `Link.send()` |
| Car ↔ Ground station | Wire protocol only (`shared/protocol.py`'s CFR/batch layout) | No shared process, no shared memory — must agree byte-for-byte via the versioned, static dictionary + `protocol_version` field |
| Ground-station decode pipeline ↔ WebSocket broadcast | State store (in-memory dict) + per-tick downsample | Decode never blocks on a slow WebSocket client; per-client bounded send queues isolate that |

## Scaling / Operating-Condition Considerations

This system doesn't scale to "users" in the conventional sense — the relevant axes are bus load, number of simultaneous receivers, and session duration.

| Condition | Architecture behavior | Adjustment if it becomes binding |
|---|---|---|
| Current: ~4,000 fps combined, one car, one pit laptop | Design point for every numeric estimate in this document | — |
| Multiple simultaneous ground-station receivers (not currently planned — explicitly out of scope per `PROJECT.md`) | **Falls out for free:** each receiver independently deframes/reconstructs its own per-ID state from the same broadcast/multicast link; there is no shared server-side state to coordinate | Would need a broadcast-capable Link (e.g. UDP multicast) rather than point-to-point serial — not a protocol change |
| Higher bus load (e.g. CAN FD upgrade, or added ECUs) | First things to re-validate: telemetry-queue sizing (Pattern 1), encoder CPU-time-per-frame estimate (Pattern 2), and the compression-ratio measurement itself (bandwidth budget headroom shrinks first) | Fall back to critical-channels-only live streaming (already sized in `telemetry_conversation.md`) while keeping full-rate archive, per PITFALLS.md Pitfall 1's documented recovery path |
| Multi-hour session duration | Client-side uPlot ring buffer and server-side state-store-only (no history) design already bound memory growth regardless of session length (STACK.md's uPlot benchmark citation) | — |

## Build Order — Vertical Slices with Dependency Rationale (answers Q8)

Ordering follows the actual dependency graph: capture fan-out (Pattern 1) is the true root — nothing else can be meaningfully built or tested without it (or a recorded/replayed stand-in for it). From there, the durable and lossy paths are genuinely independent and can proceed in parallel once the fan-out exists. Radio procurement is a standing parallel-track action from day one (PITFALLS.md Pitfall 5), never gated by software sequencing.

**Slice 0 — Scaffolding (days, not weeks; a prerequisite, not a phase with its own "vertical" value):**
- Dependency manifests (`requirements.txt`/`pyproject.toml`), consolidate the two existing loggers into one, config-driven runtime (no hardcoded IDs/paths/DBC path), "no bare except" convention adopted from the start (PITFALLS.md Pitfalls 8, 9, 10).
- **Compression-ratio measurement against a real log** (PITFALLS.md Pitfall 1) — a throwaway script, not production code, but its output (real bytes/frame, broken out per-ID, specifically covering a rolling-counter ID, a multiplexed message if the DBC has one, and the highest-frequency raw sensor ID) is a **gate**: it must exist before Slice 2 finalizes the CFR/batch byte layout in Pattern 3, because whether counters/multiplexed messages need special handling changes that layout.
- **Kick off RFD900x procurement in parallel, starting immediately** — not blocked by, and not blocking, any of the following software slices.

**Slice 1 — "Something runs on the car": capture fan-out + durable archive + thin end-to-end live link.** *(This is the phase the prompt requires to deliver both a working archive path and a thin end-to-end live link — both land here, together, not sequentially.)*
- Build the capture thread with Pattern 1's two-queue fan-out (archive queue, never-drop; telemetry queue, drop-oldest).
- Archive side, fully independent of everything else: MCAP writer, batched `fdatasync`, ext4, and a **bench power-pull test proving recovery to the last complete record** (PITFALLS.md Pitfall 4) — by the end of this slice, the "no run's data is ever lost" core value should be provably, not just architecturally, true.
- Telemetry side, deliberately minimal for this slice — not the final compression scheme: a bare-bones encode (even a naive fixed-format record, not yet the full delta/XOR/keyframe design) → simple batching → COBS+CRC → `LoopbackLink` → deframe → decode → the Python `websockets` port of `server.js` → dashboard (or a bare-bones stand-in). The goal here is proving the **layered shape** works end to end across all six protocol layers over loopback — not the final byte budget or the stateful-recovery guarantees, which are Slice 2's job.
- **Exit criteria for this slice, all measured, none assumed:** archive recovers from a real power-pull; capture sustains a soak test at full ~4,000 fps combined bus load with logged (not eyeballed) drop counts and queue high-water marks (PITFALLS.md Pitfall 6) — this is also the go/no-go signal for Pattern 2's GIL-viability reasoning, since it's the first point real hardware numbers replace the order-of-magnitude estimates in this document; a synthetic/replayed signal visibly reaches the dashboard over loopback.

**Slice 2 — Protocol hardening: real compression, stateful recovery, bufferbloat control.** Depends on Slice 1's shapes and Slice 0's compression measurement.
- Finalize the CFR/batch layout (Pattern 3) using Slice 0's real per-ID numbers; implement per-ID state, sequence numbers, periodic keyframes, versioned static dictionary; bake the session-epoch/monotonic timestamp scheme (Q7) into the batch header here, since retrofitting timestamp semantics into an already-deployed wire format later is expensive.
- Implement the leaky-bucket shaper and `RateLimitedLink` (Pattern 5).
- Build the automated frame-drop and saturation test harnesses (PITFALLS.md Pitfalls 2 and 3) as compositions of `RateLimitedLink` — CI-runnable, no hardware.
- **Exit criteria:** measured p50/p95/p99 latency stays bounded under a synthetic saturation test (flat p99, not climbing); a randomized frame-drop test shows no garbage-but-plausible value ever reaches the state store, only correctly-flagged staleness.

**Slice 3 — Live display completeness and honest staleness UX.** Depends on Slice 2's per-ID staleness flags. Runs entirely against loopback/synthetic data — does not block on radio hardware.
- Scrolling uPlot time-series, configurable limit alarms, gap-honest rendering (Q6: null/NaN gaps, staleness banner, dual staleness signals).
- Alarms should be gated behind the same integrity checks Pattern 3 already produces (PITFALLS.md: "alarms can fire off desynced/garbage decompressed values" is a named risk) — this slice is also where that gating gets wired in, not deferred.

**Slice 4 — Radio integration.** By this point, procurement (started in Slice 0) should have landed hardware.
- Swap `LoopbackLink`/`UdpLink` for `SerialLink` — nothing above the Link interface changes, per Pattern 4's design.
- Bench RF test in isolation (throughput, NETID/ECC/air-rate config, latency under saturation with real hardware) before any on-car integration (PITFALLS.md Pitfall 5).
- On-car RF test, engine/inverter off then on, to characterize real EMI impact (PITFALLS.md Pitfalls 5, 7, 11, 13) — documented, versioned radio config (netid, air rate, ECC=off) checked into the same config system Slice 0 established.

**Slice 5 — Operations polish.** Lower urgency, deferrable without touching prior work.
- GPS+PPS time-sync refinement (Q7, item 2) — only improves wall-clock *label* accuracy, never data correctness, so it's safely last.
- `rsync`-over-SSH automated archive pull, triggered on network availability, gated on session-close `.done` markers (STACK.md).
- Operational runbook, connector strain-relief/hardening pass (PITFALLS.md Pitfalls 7, 10).

**Cross-cutting, not a slice of its own:** the "no bare except / surface errors loudly" convention (PITFALLS.md Pitfall 8) and the archive-writability canary check (Pitfall 4) should be enforced from Slice 0 onward and re-checked at every subsequent slice's exit criteria, not owned by one phase.

## Sources

- CPython `ceval_gil.h` / documented GIL switch-interval semantics (`sys.setswitchinterval`, default 5 ms) — HIGH confidence (primary CPython source/mechanics, widely corroborated: [tenthousandmeters.com — Python behind the scenes #13](https://tenthousandmeters.com/blog/python-behind-the-scenes-13-the-gil-and-its-effects-on-python-multithreading/), [Rohan Varma — The Python GIL](https://rohanvarma.me/GIL))
- `ctypes` GIL-release-around-foreign-call behavior — HIGH confidence (documented CPython `ctypes` semantics: foreign `CDLL` calls release the GIL for the duration of the call by default)
- Raspberry Pi CM4 no onboard battery-backed RTC; PPS-capable GPIO via official IO board — HIGH confidence, corroborated by multiple independent sources: [Jeff Geerling — Time Card and PTP on CM4](https://www.jeffgeerling.com/blog/2021/time-card-and-ptp-on-raspberry-pi-compute-module-4/), [Austin's Nerdy Things — Microsecond accurate NTP with GPS PPS](https://austinsnerdythings.com/2025/02/14/revisiting-microsecond-accurate-ntp-for-raspberry-pi-with-gps-pps-in-2025/), [Timebeat — Clock Sync Capabilities of the CM4](https://www.timebeat.app/post/raspberry-pi-hardware-capabilities)
- Token bucket / leaky bucket rate-limiting pattern — HIGH confidence as a general, well-established CS pattern; no CAN/serial-specific prior art found, design here is this project's own application of the standard pattern to a serial/batch context (general references: [freeCodeCamp — Token Bucket Rate Limiting](https://www.freecodecamp.org/news/token-bucket-rate-limiting-fastapi/))
- CM4 CPU: Broadcom BCM2711C0, quad-core Cortex-A72 @ 1.5 GHz — HIGH confidence (`telemetry_conversation.md`, this project's own prior research, and independently corroborated: [MagPi — Raspberry Pi Compute Module 4 specs, benchmarks and testing](https://magazine.raspberrypi.com/articles/raspberry-pi-compute-module-4-specs-benchmarks-testing))
- Per-frame domain-encoder CPU cost estimate (low single-digit µs/frame, <2% of one core at 4,000 fps) — **MEDIUM confidence, explicitly not yet benchmarked on this Cortex-A72/python-ics stack**; order-of-magnitude reasoning from general CPython bytecode-execution cost, not a measured number — flagged as a Slice 1 exit-criteria measurement to replace this estimate with real data
- `.planning/research/STACK.md`, `.planning/research/PITFALLS.md`, `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`, `telemetry_conversation.md` — HIGH confidence (primary sources, this project's own settled research and ground truth)

---
*Architecture research for: split car/ground-station CAN telemetry over a lossy radio link*
*Researched: 2026-07-30*
