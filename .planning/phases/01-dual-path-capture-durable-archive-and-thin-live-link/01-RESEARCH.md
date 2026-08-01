# Phase 1: Dual-Path Capture — Durable Archive and Thin Live Link - Research

**Researched:** 2026-08-01
**Domain:** Crash-safe append-only telemetry archiving (MCAP) + dual-consumer capture fan-out + COBS/CRC framing over a swappable link, on CPython 3.12 targeting a Raspberry Pi CM4
**Confidence:** HIGH on the MCAP write/read mechanics, SDK comparison, and framing library behavior — all directly executed against the installed packages in this session, not taken from documentation prose. MEDIUM on CM4-specific throughput numbers (measured on the Windows dev box, not the target ARM core). LOW/flagged wherever noted.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Session Lifecycle & Archive Layout**
- A session is one logger process run. No time- or size-based rotation within a run. A run is bounded by ignition, and an abrupt power cut then naturally leaves the session without its completion marker.
- Session naming is UTC `YYYYMMDD-HHMMSS` with a monotonic counter fallback (CM4 has no RTC battery). Record which of the two produced the name.
- Completion is marked by a sidecar `.done` file written only after the archive writer's close-and-flush returns. Never write it optimistically.
- One MCAP file per session. MCAP is append-only and crash-safe; chunking would add recovery seams without buying durability.

**Capture Fan-Out & Backpressure**
- One capture thread fans out to two independent queues — a large one for the archive, a small bounded one for telemetry. Follows the existing queue-decoupling pattern in `src/new_logger.py`.
- The telemetry queue drops the OLDEST entry when full (evict head, then enqueue).
- The archive flushes on a batched cadence — whichever of record-count or elapsed-time comes first. Starting values 1000 records / 250 ms, both in config. ARCH-04 requires that flushing never stall capture.
- If the ARCHIVE queue fills, that is a fatal condition: log loudly and stop the session. CAP-03 says the archive consumer never drops.
- Every discard, high-water mark, and error is counted and reported (CAP-05, CAP-06): telemetry discard counts, both queues' high-water marks, and hardware/decode errors logged with frame context — never a bare `except Exception: pass`.

**Link Abstraction & Ground Station**
- Two link implementations ship in Phase 1: in-process loopback and UDP unicast. A serial implementation waits for Phase 9.
- The link interface is a synchronous `send(bytes)` / `recv() -> bytes` Protocol, with the transport owning its own thread. Mirrors the `FrameSource` Protocol style in `src/telemetry/wire/frame_source.py`. No asyncio in Phase 1.
- The Phase 1 ground station is a headless CLI consumer — deframe → decompress → DBC-decode → print/record. The browser dashboard and the single-process Python server are Phase 2 (GND-02..05).
- The critical-channel allowlist filters ON THE CAR, at the telemetry fan-out, before the encoder.

**Config & Provisioning**
- Config is JSON, loaded by a typed loader that raises a named error — the same shape as Phase 0's `config/gate.json` + `GateConfigError`.
- `--config` names the file, defaulting to `config/logger.json`. CLI flags override individual fields. Unknown keys are an error, not a warning.
- `requirements.txt` with exact pins.
- The subset allowlist is read from config at startup and never baked into code.

### Claude's Discretion
- Exact module layout under `src/telemetry/` beyond the existing `wire/`, `synth/`, `measure/` packages — follow the D-07 target-rebuild layout already established.
- MCAP schema/channel modelling (how CAN frames map onto MCAP channels and message encodings).
- Thread vs. process for the ground consumer, queue sizing defaults beyond the two named above, and log formatting.
- Whether the UDP link sends one datagram per batch or coalesces.

### Deferred Ideas (OUT OF SCOPE)
- **Legacy logger deletion moved to Phase 2 (user decision).** `src/neoVI_logger.py`, `src/new_logger.py`, `src/references.py`, `src/neoVI_sender.py` stay in place through Phase 1 for rollback safety. **CAP-01 and Phase 1 success criterion 1 will NOT be fully met in Phase 1** — the "duplicate implementation removed from the repository" clause is re-targeted to Phase 2. Phase 1 satisfies the other half: a single new implementation captures both buses concurrently.
- Serial / pyserial link implementation — Phase 9, with the real RFD900x.
- Keyframes and dictionary/allowlist version negotiation — Phase 4.
- Leaky-bucket shaping and the p99-latency saturation soak — Phase 5.
- MDF4 conversion and automated archive pull — Phase 8.
- Hand-review of Phase 0's 12 checksum-bucket classifier candidates — still open, non-blocking.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CAP-01 | Single logger captures both buses concurrently; duplicate removed | SDK comparison below picks `python-ics` decisively; removal deferred to Phase 2 per locked decision — plans must not claim this ID as fully closed |
| CAP-02 | Sustain ~4,000 fps combined, no archive-path drops | Queue throughput benchmarks + `SyntheticFrameSource` reuse as load generator (Pitfall/Code Examples) |
| CAP-03 | Fan-out to two consumers, divergent overflow policy | `queue.Queue`/`deque(maxlen)` verified throughput; Pattern 1 (reused from `.planning/research/ARCHITECTURE.md`) |
| CAP-04 | Telemetry consumer structurally cannot backpressure capture/archive | Same pattern — non-blocking primitives only |
| CAP-05 | Telemetry discards counted, not silently dropped | Code Examples: counters wired into the fan-out |
| CAP-06 | Hardware/decode errors logged with frame context | SDK comparison: `ics.get_messages()` error_count field; no bare `except: pass` |
| ARCH-01 | Every frame written to local MCAP archive on NVMe | MCAP Writer API verified (Priority 1) |
| ARCH-02 | Archive survives abrupt power cut, pre-cut data intact/readable | MCAP crash-recovery mechanics verified empirically (Priority 1) — this is the phase's single highest-risk finding |
| ARCH-03 | Durability proven by repeatable physical power-pull test | Power-cut test methodology (Priority 3) |
| ARCH-04 | Batched flush cadence, never stalls capture | mcap chunking-vs-fsync mismatch resolved (Priority 1/2) |
| ARCH-05 | `.done` marker only after close-and-flush | Write-ordering pattern (Priority 2) |
| LINK-01 | COBS + CRC framing, resync at delimiter | `cobs`/`crccheck` verified (Priority 6) |
| LINK-02 | CRC-failed frames discarded and counted | `cobs.DecodeError` verified (Priority 6) |
| LINK-03 | Transport abstracted (loopback/UDP/serial swap with no layer change) | Link Protocol pattern (Priority 7) |
| LINK-04 | Full chain runs with no radio hardware | LoopbackLink + UdpLink, both hardware-free |
| GND-01 | Ground station deframes/decompresses/DBC-decodes | Headless CLI consumer pattern (Priority 7) |
| OPS-04 | Sessions segmented, not one unbounded file | Session lifecycle (locked decision, already specified) |
| OPS-05 | Channels/DBC path/link settings from config | `GateConfig`/`GateConfigError` pattern reused for `config/logger.json` |
| OPS-06 | `requirements.txt` provisions a clean machine | Package Legitimacy Audit + verified installable versions below |
</phase_requirements>

## Summary

This phase's dominant risk is not the parts everyone expects to be hard (COBS, CRC, UDP) — those are small, well-behaved, and already effectively pre-selected by Phase 0's `.planning/research/` documents. The dominant risk is a **library behavior gap in `mcap` that is invisible until you deliberately simulate a crash**: the installed `mcap==1.4.0` Python `Writer` performs zero `fsync`/`flush`-to-disk of its own, buffers up to 1 MB of messages purely in Python-process memory before writing anything to the stream at all (default `use_chunking=True`), and — critically — its own `Reader` classes **cannot recover a crashed (footer-less) file through their default configuration**. `mcap.reader.make_reader()`'s default choice (`SeekingReader`) throws a nonsensical `RecordLengthLimitExceeded` error on a crashed file instead of a clean "no footer" signal, and `NonSeekingReader.iter_messages()`'s default `log_time_order=True` silently discards every message on any read error because it buffers the entire stream before yielding anything — recovering **zero of fifty** cleanly-written records in this session's direct test. The only reader configuration that recovers pre-crash data correctly is `NonSeekingReader(f).iter_messages(log_time_order=False)`, wrapped to catch `EndOfFile`/`struct.error`. This is the single most load-bearing, easy-to-get-wrong fact for ARCH-02 and success criterion 2, and it was verified by writing, crashing, and reading back real files in this session — not by reading `mcap`'s documentation.

The corollary is that CONTEXT.md's already-locked batching decision ("flush on record-count-or-time, whichever first, starting 1000/250ms") is **incompatible with `mcap`'s own default chunk-size-based flush trigger** (`chunk_size` is a byte threshold, not a count/time one) and is best implemented by disabling `mcap`'s chunking entirely (`use_chunking=False`, which also matches CONTEXT.md's own stated rationale that "chunking would add recovery seams without buying durability") and layering the record-count-or-time fsync cadence as an application-level concern on top of the now-per-message stream writes, with an explicit `os.fsync()`/`os.fdatasync()` call the library never makes on its own.

The second major finding is a decisive, evidence-based answer to the CAP-01 python-ics-vs-vspyx question the phase asks for: `python-ics` fails fast and cleanly when its native driver is absent (`ics.find_devices()` raises a catchable `RuntimeError` in well under a second), while `vspyx` (Vehicle Spy X's full application engine wrapped for Python) **hung on bare `import vspyx` for the full 30-second test timeout** on this dev machine with no hardware or license configured. For an unattended embedded logger that must start non-interactively and be testable hardware-free on a Windows dev laptop, this is a decisive, not marginal, difference favoring `python-ics` as the single consolidated implementation.

**Primary recommendation:** Build the archive writer around `mcap.writer.Writer(file_obj, use_chunking=False, compression=CompressionType.LZ4)` with an explicit application-level fsync scheduler (count-or-time), read crashed sessions back with `NonSeekingReader(...).iter_messages(log_time_order=False)` only, consolidate capture onto `python-ics`, keep the fan-out exactly as already decided in CONTEXT.md (`queue.Queue`/`deque(maxlen=N)`), and implement framing with the already-vetted `cobs` + `crccheck` (or an inline CRC-16 table) libraries — no new library category is needed anywhere in this phase.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CAN frame capture (hardware poll) | Car — Capture thread | — | `python-ics` polls the neoVI device directly; nothing else touches hardware |
| Archive durability (MCAP write, fsync cadence, `.done` marker) | Car — Archive writer thread | Database/Storage (NVMe/ext4) | Owns the only durability guarantee in the system; zero dependency on radio/link |
| Fan-out & backpressure isolation | Car — Capture thread (fan-out step only) | — | The two `put`/`append` calls are the entire mechanism; no separate component |
| Domain encoding (CFR) | Car — Telemetry pipeline | — | Already implemented in `src/telemetry/wire/encoder.py`; Phase 1 imports unchanged |
| Framing (COBS+CRC) & batching | Car — Telemetry pipeline | — | New this phase; content-agnostic, sits below the encoder |
| Link transport | Car ↔ Ground — Link Protocol implementations | — | Swappable; loopback/UDP in Phase 1, serial in Phase 9 |
| Deframe/decompress/decode | Ground station (headless CLI) | — | DBC decode never happens car-side (bandwidth inversion, already a settled Key Decision) |
| Config (channels, DBC path, link settings, allowlist) | Car + Ground — shared JSON config, typed loader | — | Read at startup on both ends; no runtime negotiation in Phase 1 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcap` | 1.4.0 `[VERIFIED: PyPI + installed & exercised this session]` | On-car archive container | Purpose-built append-only format; already the settled Key Decision in `PROJECT.md` over BLF (append broken, python-can#1751) and MDF4 (no append at all) |
| `python-ics` | `1!26.3.9` (calendar-versioned, epoch 1) `[VERIFIED: PyPI + installed this session; ics.find_devices() exercised without hardware]` | CAN hardware capture, both buses | Already in use in `src/new_logger.py`; fails fast (`RuntimeError`) with no native driver present — see SDK comparison below for why this beats vspyx for CAP-01 consolidation |
| `cantools` | 42.0.3 `[VERIFIED: already pinned in requirements-dev.txt, package-legitimacy approved in Phase 0]` | DBC decode, ground-station only | Unchanged from Phase 0; imported by `src/telemetry/wire/dictionary.py` |
| `cobs` | 1.2.2 `[VERIFIED: PyPI + installed & exercised this session — cobs.decode() raises DecodeError on corrupted input]` | COBS byte-level framing | Already the settled choice in `.planning/research/STACK.md`; C extension with pure-Python fallback |
| `crccheck` | 1.3.1 `[VERIFIED: PyPI + already installed in this dev environment; Crc16CcittFalse/Crc16Xmodem/Crc16Modbus all exercised this session]` | CRC-16 over each framed batch | Already present in the dev interpreter (see Package Legitimacy Audit for provenance note); `.planning/research/STACK.md` explicitly names it as an acceptable choice alongside a hand-rolled table |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | 9.1.1 `[VERIFIED: already pinned, Phase 0 package-legitimacy approved]` | Test runner | Unchanged; 127 tests currently pass (`python -m pytest -q`, verified this session) |
| `crccheck` alternative: hand-rolled CRC-16 table | n/a | Same purpose, zero dependency | Only if the team wants one fewer pinned dependency; `crccheck` is already installed and costs nothing extra to keep, so this is a discretion call, not a requirement |
| `vspyx` | 1.3.0.dev580 `[VERIFIED: PyPI, installable via pip on Windows cp312 — confirmed by direct download this session]` | Legacy alternate SDK, NOT recommended for the new consolidated logger | Kept only if `src/neoVI_logger.py` is retained unmodified per the Deferred-to-Phase-2 decision; do not build new code against it |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `mcap` `use_chunking=False` (recommended) | `mcap` default chunking (`use_chunking=True`, small `chunk_size`) | Verified to also recover complete chunks after a crash (194/200 messages recovered in this session's test with `chunk_size=256`), but the flush trigger is byte-size-based, not count/time-based — cannot precisely implement CONTEXT.md's locked "1000 records or 250ms" cadence without also layering an explicit fsync call, so chunking buys compression/indexing at the cost of an extra, harder-to-reason-about durability boundary. Not recommended for Phase 1; CONTEXT.md's own rationale ("chunking would add recovery seams without buying durability") already anticipates this call |
| `python-ics` (recommended) | `vspyx` | vspyx wraps the full Vehicle Spy X application engine; `import vspyx` hung 30+ seconds with no hardware/license present in this session's test, vs. `python-ics`'s sub-second, catchable failure. Worse fit for an unattended embedded logger and for hardware-free dev-laptop testing |
| `cobs` + `crccheck`/hand-rolled CRC-16 | Reach for a higher-level framed-transport library (e.g. `pyserial`'s own framing, or a pub/sub protocol) | Everything else in this space assumes a connected, addressable transport or adds dependencies well beyond what a 6-line COBS+CRC batch needs; Phase 0's own D-06 modeled exactly this pair, no reason to diverge |

**Installation (illustrative — planner should freeze versions during Wave 0):**
```bash
pip install mcap==1.4.0 cobs==1.2.2 crccheck==1.3.1 python-ics==26.3.9 cantools==42.0.3 pytest==9.1.1
```

**Version verification:** All six package/version pairs above were checked against the PyPI registry this session via `pip index versions <pkg>` and, for `mcap`/`cobs`/`python-ics`/`vspyx`, actually installed and imported (`python -m pip install ...`) in the project's native-Windows CPython 3.12.10 interpreter at `C:\Users\ethan\AppData\Local\Programs\Python\Python312\`. `mcap` additionally pulled in `lz4` (4.4.5) and `zstandard` (0.25.0) as its own transitive dependencies for chunk compression — both must be pinned in `requirements.txt` even though Phase 1's writer recommendation (`use_chunking=False`) never calls their compression path, because `mcap` imports them unconditionally at module load and the `Writer.__init__` validation branch references them.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `mcap` | PyPI | published 2026-06-18 (this release) | unknown (checker limitation) | github.com/foxglove/mcap | `[SUS: unknown-downloads]` | Approved — see note below |
| `cobs` | PyPI | published 2025-07-20 | unknown (checker limitation) | github.com/cmcqueen/cobs-python | `[SUS: unknown-downloads]` | Approved — see note below |
| `python-ics` | PyPI | published 2026-07-08 | unknown (checker limitation) | intrepidcs.com | `[SUS: too-new, unknown-downloads]` | Approved — see note below |
| `crccheck` | PyPI | published 2025-07-10 | unknown (checker limitation) | github.com/MartinScharrer/crccheck | `[SUS: unknown-downloads]` | Approved — see note below |
| `vspyx` | PyPI | — (not separately checked; not the recommended package) | — | intrepidcs.com | not run | N/A — not recommended for new code |

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** all four checked packages, but every flag is `unknown-downloads` (a metadata-fetch limitation of the checker against PyPI, not a legitimacy finding — the exact pattern Phase 0's own `00-DECISION.md`/STATE.md already documented for `cantools`/`pytest`: "Both RESEARCH.md SUS verdicts were metadata artifacts, not legitimacy findings") plus `too-new` for `python-ics` (the *release cadence* is recent because Intrepid ships calendar-versioned point releases frequently — `1!26.3.9` is epoch 1, year 26; the package itself has 50+ historical releases dating back years, confirmed via `pip index versions python-ics`). Each package's `repoUrl` resolves to its known-legitimate maintainer: Foxglove (mcap's creator and primary maintainer), the well-established `cobs-python` author, Intrepid's own vendor domain (matches the existing `import ics` usage already in `src/new_logger.py`), and the well-known `crccheck` author. All four are cross-checked against official sources (Foxglove's own MCAP docs referenced their PyPI package; Intrepid's own site is the `repoUrl` for `python-ics`) and were installed and directly exercised in this session, satisfying `[VERIFIED]` provenance. **Per protocol, the planner should still gate the first install of each in a fresh environment behind a `checkpoint:human-verify` task**, since the automated checker's own signal remains `SUS` even though the underlying finding is a metadata artifact, not a risk finding.

**`crccheck` is already installed in the current dev interpreter** despite Phase 0's own D-06 stating "cobs and CRC-16 libraries stay uninstalled." This is an environment-state discrepancy worth flagging to the planner: either it was installed manually outside the GSD workflow during exploration, or a prior session's tooling installed it. It is not currently referenced in `requirements-dev.txt` or any source file. D-06 no longer holds as an accurate description of installed state (though it may still hold as a description of what's *pinned in a manifest*, which remains true) — the planner should decide whether to adopt it into `requirements.txt` or treat its presence as incidental.

## Architecture Patterns

### System Architecture Diagram

```
                              CAR (Raspberry Pi CM4)
┌──────────────────────────────────────────────────────────────────────────┐
│  neoVI hardware (both buses)                                             │
│        │ python-ics poll (capture_thread, ~10ms interval)                │
│        ▼                                                                 │
│  ┌─────────────┐                                                         │
│  │ CAPTURE      │  timestamp + fan-out only, zero decode, zero I/O       │
│  │ THREAD       │                                                         │
│  └──┬───────┬───┘                                                         │
│     │       │  two independent non-blocking calls — neither can          │
│     │       │  block or be blocked by the other                          │
│     ▼       ▼                                                             │
│  ┌──────┐ ┌──────────┐                                                    │
│  │queue.│ │deque      │  put_nowait() / append()                         │
│  │Queue │ │(maxlen=N) │  archive: never-drop, fatal-if-full               │
│  │(N large)│ (drop-oldest)│  telemetry: silently evicts oldest             │
│  └──┬───┘ └────┬─────┘                                                    │
│     ▼          ▼                                                          │
│  ┌────────────┐  ┌──────────────────────────────────┐                    │
│  │ ARCHIVE     │  │ TELEMETRY PIPELINE                │                   │
│  │ WRITER      │  │  allowlist filter (config)         │                  │
│  │ thread      │  │  → CFR encode (encoder.py)         │                  │
│  │             │  │  → batch (13B header + N CFRs)     │                  │
│  │ mcap.Writer │  │  → COBS encode + CRC-16 append     │                  │
│  │ use_chunking│  │  → Link.send(bytes)                │                  │
│  │ =False      │  └──────────────┬───────────────────┘                   │
│  │ + explicit  │                 │                                        │
│  │ fsync every │        ┌────────▼────────┐                              │
│  │ 1000 rec /  │        │ LINK (swappable) │  LoopbackLink / UdpLink      │
│  │ 250ms       │        └────────┬────────┘                              │
│  └──┬──────────┘                 │  lossy, unacknowledged byte pipe       │
│     ▼                            │                                        │
│  NVMe (ext4)                     │                                        │
│  session-NAME.mcap               │                                        │
│  + .done sidecar                 │                                        │
│  (fsync data → write .done       │                                        │
│   → fsync .done → fsync dir)     │                                        │
└───────────────────────────────────┼──────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼──────────────────────── GROUND STATION ┐
│                              ┌─────────────────┐                             │
│                              │ LINK (mirror)    │                            │
│                              └────────┬────────┘                            │
│                              ┌────────▼────────────────┐                    │
│                              │ DEFRAME: COBS decode +   │                    │
│                              │ CRC verify; discard+count│                    │
│                              │ on failure (LINK-02)     │                    │
│                              └────────┬────────────────┘                    │
│                              ┌────────▼────────────────┐                    │
│                              │ CFR decode (decoder.py)  │                    │
│                              └────────┬────────────────┘                    │
│                              ┌────────▼────────────────┐                    │
│                              │ DBC decode (cantools)     │                    │
│                              └────────┬────────────────┘                    │
│                              ┌────────▼────────────────┐                    │
│                              │ headless CLI print/record │                    │
│                              │ (GND-01; dashboard is      │                    │
│                              │  Phase 2)                   │                    │
│                              └──────────────────────────┘                    │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
src/telemetry/
├── wire/            # EXISTING — encoder.py, decoder.py, dictionary.py, overhead.py, frame_source.py
│   └── batcher.py       # NEW — batch header assembly (protocol_version, dict_version,
│                         #        base_timestamp, frame_count, batch_seq per Pattern 3)
├── framing/         # NEW package
│   ├── cobs_frame.py    # thin wrapper: encode(payload)->bytes, decode(bytes)->payload|raises
│   └── crc16.py         # crccheck-backed or hand-rolled CRC-16, one function each way
├── link/            # NEW package
│   ├── base.py           # Link Protocol: send(bytes)->None, recv(timeout)->bytes|None, close()
│   ├── loopback.py       # in-process, zero OS dependency
│   └── udp.py             # UdpLink, one socket per side
├── capture/         # NEW package
│   ├── hardware_source.py  # implements FrameSource against python-ics (CAP-01 consolidation)
│   ├── replay_source.py    # NEW — deferred Phase 0 real-log FrameSource reader (D-08 re-check condition)
│   └── fanout.py           # capture_thread: poll → timestamp → two-queue fan-out (Pattern 1)
├── archive/         # NEW package
│   ├── writer.py          # mcap.Writer wrapper: use_chunking=False, count-or-time fsync cadence
│   ├── session.py         # UTC name + monotonic-counter fallback, .done sidecar sequencing
│   └── reader.py           # NonSeekingReader(log_time_order=False) recovery wrapper — used by
│                            #   tests and by any operator tooling that inspects a crashed session
├── measure/          # EXISTING — config.py pattern reused for config/logger.json's typed loader
└── ground/           # NEW package
    ├── deframe.py        # COBS decode + CRC verify, discard+count on failure
    └── cli.py             # headless consumer entry point (GND-01)

config/
├── gate.json          # EXISTING (Phase 0)
└── logger.json         # NEW — channels, DBC path, link settings, critical-channel allowlist
```

### Pattern 1: Fan-out with divergent overflow queues (reused unchanged from `.planning/research/ARCHITECTURE.md` Pattern 1)

**What:** One capture step feeds `queue.Queue(maxsize=N)` (archive, never-drop, `put_nowait()`) and `collections.deque(maxlen=N)` (telemetry, drop-oldest, `.append()`). This is already locked in CONTEXT.md and unchanged by this session's research — restated here only because the throughput numbers below verify it holds at the required rate.

**Verified this session** (native Windows CPython 3.12.10, illustrative only — not the CM4's Cortex-A72, but directionally confirms neither primitive is the bottleneck):
```
queue.Queue.put_nowait:  100,000 ops in 0.088s  ≈ 1.14M ops/s
deque(maxlen).append:    100,000 ops in 0.007s  ≈ 14.3M ops/s  (~12.5x faster)
```
At the phase's target ~4,000 fps combined, `queue.Queue.put_nowait()` alone would need to sustain roughly 0.35% of the throughput measured above to keep pace — even a 30-50x slower per-op cost on the CM4's Cortex-A72 (a conservative estimate; no CM4-specific number was measured this session) leaves comfortable headroom. `deque.append()`'s ~12.5x speed advantage is exactly why the telemetry path uses it, independent of its drop-oldest semantics — it is also the cheaper primitive.

**Example (canonical fan-out, matches CONTEXT.md's locked shape):**
```python
archive_q: queue.Queue = queue.Queue(maxsize=ARCHIVE_QUEUE_DEPTH)      # ~10s of frames
telemetry_q: collections.deque = collections.deque(maxlen=TELEMETRY_QUEUE_DEPTH)  # ~250ms of frames

def on_frame(frame, stop_event, hwm_counters, discard_counters):
    try:
        archive_q.put_nowait(frame)
    except queue.Full:
        log_critical("archive queue full — durability guarantee at risk; stopping session")
        stop_event.set()   # fatal per CONTEXT.md's locked decision
        return
    hwm_counters.archive = max(hwm_counters.archive, archive_q.qsize())

    was_full = len(telemetry_q) == telemetry_q.maxlen
    telemetry_q.append(frame)   # never raises, never blocks; silently evicts oldest if full
    if was_full:
        discard_counters.telemetry += 1   # CAP-05: count what deque silently ate
```
Note the `was_full` check: `deque(maxlen=N).append()` gives no signal that it evicted anything, so CAP-05's discard-counting requirement must be implemented by checking fullness *before* the append, not by inspecting the deque afterward.

### Pattern 2: MCAP archive writer — verified crash-recovery mechanics `[VERIFIED: mcap 1.4.0 source read + empirical crash simulation, this session]`

**The problem CONTEXT.md's locked decision must actually solve:** ARCH-02 requires the archive to survive an abrupt power cut with "all data written before the cut intact and readable." This session verified, by writing real `.mcap` files and truncating/crashing them, exactly what "readable" requires from the `mcap` Python library — which differs sharply from what a naive read of its documentation ("append-only, chunked, streaming writer... reader that can recover every complete chunk") would suggest.

**Verified facts, in order of how easy each is to get wrong:**

1. **`mcap.writer.Writer` never calls `fsync`/`fdatasync`, and `add_message()` doesn't even always call the underlying stream's `.write()`.** Reading the installed package's source (`Writer.__flush()`) confirms `__flush()` only calls `self.__stream.write(data)` — no Python-level `.flush()`, no OS-level sync, ever, anywhere in the class. The caller must own the file object and manage both flush layers itself.

2. **Default `use_chunking=True` with `chunk_size=1024*1024` (1 MB) means messages sit purely in an in-memory `ChunkBuilder` until the chunk reaches 1 MB — no bytes reach the stream at all until then.** At combined ~4,000 fps of small raw-CAN records (well under 1 MB of accumulated bytes for many seconds), a crash before the chunk fills loses everything in it, silently. This is strictly worse than "unflushed OS buffer" — it's unwritten-to-the-stream Python memory. `mcap`'s own default is a poor match for CONTEXT.md's locked 250ms/1000-record cadence.

3. **`Writer.finish()` is the only call that writes `DataEnd`, the summary section, the `Footer` record, and the trailing MCAP magic bytes.** A file crashed before `finish()` has none of these. This is expected — every append-only crash-safe format has some "not yet closed" state — but the specific consequence for *reading it back* is not obvious from the library's public docstrings:

4. **`mcap.reader.make_reader()`'s default choice fails badly on a crashed file, not gracefully.** `make_reader()` picks `SeekingReader` for any seekable stream (a normal on-disk file always is). `SeekingReader.get_summary()` unconditionally seeks to `file_end - FOOTER_SIZE - MAGIC_SIZE` and tries to parse whatever bytes are there as a `Footer` record, with **no try/except around this in `iter_messages()`**. Verified this session: reading a real, complete-except-for-`finish()`, 50-message crashed file via `make_reader()` raised `RecordLengthLimitExceeded: unknown (opcode 0) record has length 281474976710656 that exceeds limit 4294967296` — a nonsense error from parsing arbitrary message bytes as if they were a footer, giving zero indication the actual problem is "no footer was ever written."

5. **`NonSeekingReader.iter_messages()`'s default `log_time_order=True` silently discards everything on any read error, even on files with no truncation at all.** Verified this session: a real file with 50 fully-written, complete, uncorrupted `Message` records (chunking disabled, so every record reached the stream — the only thing missing was the trailing `finish()`) recovered **0 of 50 messages** through `NonSeekingReader(f).iter_messages()`'s default. Root cause, confirmed by reading the source: `log_time_order=True` implements sorting via `sorted(self._iter_messages_internal(...), key=...)`, which must fully drain the underlying generator into memory *before* sorting and yielding anything — so an `EndOfFile` raised partway through that drain propagates before a single message is ever yielded. The docstring does warn "setting log_time_order to True on a non-seekable stream will cause the entire content of the MCAP to be loaded into memory," but does not warn that this also means **zero partial recovery on any read error, even at the very last record.**

6. **The one configuration that works, verified empirically:** `NonSeekingReader(f).iter_messages(log_time_order=False)`, iterated with a `for` loop and wrapped in `try: ... except (EndOfFile, struct.error): pass` (both exception types were observed depending on exactly where the truncation lands — a clean EOF between records raises `mcap.exceptions.EndOfFile`; a truncation mid-record-header raises a bare `struct.error`, which is **not** an `mcap`-specific exception type and must be caught explicitly). Results from this session's direct tests:

   | Scenario | Recovered | Expected | Notes |
   |---|---|---|---|
   | 50 complete records, no `finish()` call, no truncation | 50 / 50 | 50 | `log_time_order=False` streams correctly |
   | Same file truncated to 50% of its size | 23 / ~25 | ~25 | Clean partial recovery up to the truncation point |
   | Same file, last 3 bytes chopped (mid final record) | 49 / 50 | 49 | The one incomplete record is correctly dropped, not corrupted |
   | Default chunking (`chunk_size=256`), 200 messages, no `finish()` | 194 / 200 | ~194–200 | Confirms `.planning/research/STACK.md`'s "complete chunks survive" claim — but **only** reachable via this same non-default reader configuration, and only bounded by `chunk_size` bytes of loss for the final open chunk, not by the record-count/time cadence CONTEXT.md locked |

**Recommendation, directly resolving the CONTEXT.md/mcap-API tension:**
```python
import os
from mcap.writer import Writer, CompressionType

class ArchiveWriter:
    def __init__(self, path, flush_every_records=1000, flush_every_s=0.25):
        self._f = open(path, "wb")               # own the file object — never pass a string path
        self._writer = Writer(self._f, use_chunking=False)  # every add_message() reaches the stream now
        self._writer.start()
        self._records_since_flush = 0
        self._last_flush_t = time.monotonic()
        self._flush_every_records = flush_every_records
        self._flush_every_s = flush_every_s
        self._fsync = getattr(os, "fdatasync", os.fsync)   # Linux: fdatasync; portable fallback elsewhere

    def add(self, channel_id, log_time_ns, data, publish_time_ns, seq):
        self._writer.add_message(channel_id, log_time_ns, data, publish_time_ns, seq)
        self._records_since_flush += 1
        now = time.monotonic()
        if (self._records_since_flush >= self._flush_every_records
                or now - self._last_flush_t >= self._flush_every_s):
            self._f.flush()
            self._fsync(self._f.fileno())
            self._records_since_flush = 0
            self._last_flush_t = now

    def close(self):
        self._writer.finish()      # writes DataEnd + summary + Footer + trailing magic
        self._f.flush()
        self._fsync(self._f.fileno())
        self._f.close()
```
```python
# Recovery path — the ONLY reader configuration verified to recover pre-crash data:
from mcap.reader import NonSeekingReader
from mcap.exceptions import EndOfFile
import struct

def recover_crashed_session(path):
    recovered = []
    with open(path, "rb") as f:
        reader = NonSeekingReader(f)
        try:
            for schema, channel, message in reader.iter_messages(log_time_order=False):
                recovered.append((schema, channel, message))
        except (EndOfFile, struct.error):
            pass   # everything before the truncation point is already in `recovered`
    return recovered
```

**Cross-platform testability gap (verified this session):** `os.fdatasync` does not exist on Windows CPython (`hasattr(os, "fdatasync")` returns `False` on this dev box) — the `getattr(os, "fdatasync", os.fsync)` fallback above is required for the code to even run on the dev laptop, and the dev-laptop test suite will only ever exercise the `os.fsync` branch, never the Linux-only `fdatasync` branch the CM4 will actually use. This should be called out explicitly in the Wave 0 test plan, not discovered later.

### Pattern 3: `.done` marker write ordering (ARCH-05)

**What:** Per CONTEXT.md, the `.done` sidecar must be written "only after the archive writer's close-and-flush returns." The full ordering, extending Priority 2's request (fsync data, then write marker, then fsync dir):

```python
def close_session(archive_writer, session_dir, done_filename=".done"):
    archive_writer.close()                          # Pattern 2's close(): finish() + flush + fsync(data fd)
    done_path = session_dir / done_filename
    with open(done_path, "w") as f:
        f.write("")                                   # empty marker file is sufficient per ARCH-05's wording
        f.flush()
        os.fsync(f.fileno())                            # fsync the marker file's own data (trivial, but correct)
    dir_fd = os.open(session_dir, os.O_RDONLY)
    try:
        os.fsync(dir_fd)                                 # fsync the DIRECTORY ENTRY — Linux-only, see below
    finally:
        os.close(dir_fd)
```
**Verified this session: `os.fsync()` on a directory file descriptor raises `PermissionError: [Errno 13] Permission denied` on Windows** — `os.open(directory, os.O_RDONLY)` succeeds but the subsequent `os.fsync()` fails, because Windows does not support syncing directory metadata this way. This is a second, separate Linux-only operation (alongside `fdatasync`) that the dev laptop cannot exercise end-to-end. The archive-close code path must either (a) guard the directory-fsync call with a platform check so Windows tests can still validate the rest of the sequence, or (b) accept that this specific step is untestable outside Linux/WSL/CI-on-Linux and rely on the physical power-pull test (ARCH-03) as the only real proof it matters. Recommend (a): wrap in `if sys.platform != "win32":` so the ordering logic itself (which is what a SIGKILL-based automated test can actually verify) is still exercised on the dev laptop.

### Pattern 4: Power-cut testing — one physical test, one automated proxy, and what the proxy does NOT prove

ARCH-03 explicitly wants a **physical** repeatable power-pull procedure, and this phase separately needs an automated proxy runnable on a dev laptop with no bench/no CM4 present.

**Physical test (the actual ARCH-03 requirement):**
1. Start a logging session against a synthetic/looped-back frame source (or real hardware once available) at a known, controlled rate.
2. At a randomized or scheduled point during the run, physically disconnect DC power to the CM4 (pull the barrel/PoE connector, or — closer to the real failure mode — trip the car's kill switch feeding the neoVI PI) — not a shutdown command, not `kill`, an actual power interruption.
3. Re-apply power, let the Pi boot, and run the recovery routine (Pattern 2) against the last session directory.
4. Assert: every record recovered decodes correctly and is bounded by what was captured before the cut; the session's `.done` marker is absent (correctly reflecting the interrupted session); no partial/garbage record is silently accepted.
5. Repeat multiple times (CONTEXT.md/prompt: "repeatedly") — a single successful pull proves nothing about consistency; the failure modes this test exists to catch (partial NVMe writes, filesystem journal replay edge cases) are probabilistic.

**Automated proxy (what runs in CI / on the dev laptop with no hardware):**
`SIGKILL` (`kill -9` / `subprocess.Popen(...).kill()`) the writer process at a randomized point mid-session, then run Pattern 2's recovery routine.

**What the SIGKILL proxy does NOT prove — the ground-truth-discipline point this project's own history (Phase 0's three separate prose/measurement mismatches, per STATE.md) says to be explicit about:** `SIGKILL` terminates the *process*, not the *operating system*. Any bytes already handed to the file object via `write()` remain in the **OS page cache**, which is still alive and intact after a process is killed — the kernel did not crash. A test that SIGKILLs the writer and then immediately re-opens and reads the file back is, in the worst case, reading data straight out of page cache that was **never actually fsync'd to the NVMe** — meaning a completely broken fsync-cadence implementation (e.g., one that never calls `fsync` at all) can still pass a naive SIGKILL test, because the data it "recovers" was never actually at risk of loss in that test. This is a well-established methodology gap in crash-consistency testing generally (academic crash-injection testing explicitly targets fsync/persistence boundaries rather than arbitrary process kills, for exactly this reason) `[CITED: general crash-consistency testing literature, e.g. FAST/SOSP filesystem crash-consistency papers — no single canonical source pins this specific claim, treat as established practitioner consensus, not a single citable fact]`.

**To make the SIGKILL proxy meaningfully test the application's fsync-cadence logic (not just "did `write()` get called"), the stronger version drops the page cache before reading back:**
- On Linux (the CM4 target, and any Linux CI runner or WSL instance used for this phase): `echo 1 | sudo tee /proc/sys/vm/drop_caches` between the kill and the read-back forces subsequent reads to come from actual disk, distinguishing fsync'd data from merely-`write()`'d-but-cached data. Requires root; not available in all CI sandboxes.
- On the Windows dev laptop specifically: **there is no equivalent mechanism available to this session** — Windows has no direct `drop_caches` analog exposed to a normal process, and this phase's own environment constraint is "development happens on native Windows CPython 3.12.10 with no neoVI hardware attached." The SIGKILL proxy on Windows can only prove "the application correctly calls `write()` at the expected cadence," not "the application correctly calls `fsync`" — the fsync-correctness half of ARCH-02 is provable on this dev machine only by code inspection (confirm the fsync call is present and reached) plus the physical test, never by an automated Windows-side proxy alone.
- Recommend the test suite explicitly document this scope limit in its own docstring/comment (e.g., "this test proves write-cadence correctness; it does NOT prove fsync correctness — see 01-RESEARCH.md Pattern 4") so a future contributor doesn't mistake a passing SIGKILL test for proof the physical test can be skipped.

### Pattern 5: SDK comparison for CAP-01 — `python-ics` vs `vspyx`, verified this session

| Property | `python-ics` | `vspyx` |
|---|---|---|
| Installable via `pip` on Windows cp312 | Yes `[VERIFIED]` | Yes `[VERIFIED]` — contradicts this session's own earlier `pip index versions vspyx` failure, which was a quirk of that specific subcommand, not actual unavailability; `pip install`/`pip download` succeeded |
| Behavior with no native driver/hardware present | `ics.find_devices()` raises `RuntimeError: ...icsneoFindDevices... Windows Error #127...` in well under a second `[VERIFIED, this session]` | `import vspyx` alone hung for the full 30-second test timeout with no output, before even reaching `Application.New()` `[VERIFIED, this session — timeout killed the process, exact hang point (import vs. init) not further isolated]` |
| Timestamp source | `m.TimeSystem` (hardware-timestamped, per existing `src/new_logger.py` usage) `[CITED: existing codebase]` | `point.GetAttribute("Timestamp")` via the VehicleSpy observer pipeline `[CITED: existing codebase, src/neoVI_logger.py]` — no direct comparison of timestamp accuracy was run this session; both are plausible hardware timestamps, this is a gap, see Open Questions |
| Existing dual-bus filtering support | `CHANNEL_MAP`/`NET_ID_TO_NAME` already resolve both `NETID_HSCAN`/`NETID_HSCAN2` concurrently in `src/new_logger.py` — proven pattern | Requires per-channel `NewAttachedController` + a Resolver URI lookup per channel (`src/neoVI_logger.py::attach_controllers`) — more setup surface, and requires the full Vehicle Spy X `Application`/`Resolver` machinery rather than a flat device handle |
| Fit for an unattended, non-interactive embedded logger (forward-looking OPS-01, Phase 3) | Fails fast, catchable, no GUI/license dependency implied by the API surface used | The "Vehicle Spy X" branding and the 30-second-plus unexplained hang strongly suggest the underlying engine expects a fuller application/license context than a headless embedded process should depend on — this is inference from the observed hang, not confirmed root-cause `[ASSUMED — the exact cause of the hang (network license check, COM initialization, GUI dependency) was not isolated this session]` |

**Recommendation: consolidate CAP-01 onto `python-ics`.** This matches the existing codebase's own STRUCTURE.md characterization of `src/new_logger.py` as the "primary entry point for data collection" and is now additionally justified by directly observed hardware-free behavior, not just precedent.

### Pattern 6: COBS + CRC-16 framing — verified library behavior

```python
# Source: cobs 1.2.2, exercised directly this session
from cobs import cobs
encoded = cobs.encode(batch_bytes)          # O(1) worst-case overhead: 1 byte per ≤254-byte block
decoded = cobs.decode(encoded)              # raises cobs.cobs.DecodeError on malformed input — VERIFIED
# corrupting one byte of `encoded` and calling cobs.decode() raised:
#   DecodeError: not enough input bytes for length code
```
`cobs.decode()`'s exception is a clean, catchable, specific type (`cobs.cobs.DecodeError`) — LINK-02's "discarded and counted" requirement maps directly onto `except cobs.cobs.DecodeError: corrupt_batch_counter += 1; continue`, with no need to pre-validate input.

```python
# Source: crccheck 1.3.1, exercised directly this session
from crccheck.crc import Crc16CcittFalse   # note: __name__ resolves to "Crc16Ibm3740" — CCITT-FALSE
                                              # and IBM-3740 are the same registered CRC-16 parameters
                                              # (poly 0x1021, init 0xFFFF); crccheck aliases both names
crc = Crc16CcittFalse.calc(batch_bytes)      # returns int; pack as struct "<H" for the 2-byte trailer
```
No specific CRC-16 variant is mandated by any requirement — this is a Claude's Discretion area per CONTEXT.md. Recommend CRC-16/CCITT-FALSE (`Crc16CcittFalse` in `crccheck`, aliased internally as `Crc16Ibm3740`) as a widely-used, well-understood choice for byte-stream framing with no specific project reason to prefer an alternative variant.

**Batch sizing against a real UDP path — computed this session using the repo's own `overhead.py` module** (not estimated):
```
batch_frames=12   clean=96B    all_in=112B   (16.7% overhead)
batch_frames=20   clean=160B   all_in=176B   (10.0% overhead)
batch_frames=50   clean=400B   all_in=417B    (4.2% overhead)
batch_frames=100  clean=800B   all_in=819B    (2.4% overhead)
```
(Illustrative per-frame clean payload of 8 bytes used above; actual critical-channel-subset CFR sizes will differ once real per-message delta compression is measured against captured traffic.) All four sizes sit comfortably under the ~1,472-byte practical Ethernet/Wi-Fi UDP payload ceiling (1,500-byte MTU minus IP+UDP headers) `[CITED: standard Ethernet/IPv4 MTU arithmetic, well-established networking fact]` with wide margin — no fragmentation risk at any Phase-1-plausible batch size, so `LINK-03`'s UDP implementation needs no special handling for oversized datagrams in this phase.

**Pitfall to flag for the UDP receiver:** `socket.recvfrom(bufsize)` silently truncates a UDP datagram larger than `bufsize` with no error raised (standard POSIX/Winsock `recv` semantics for datagram sockets) `[CITED: standard socket API behavior]`. If the receive buffer is sized smaller than the largest possible batch, a legitimate (uncorrupted) frame gets silently truncated at the socket layer before the CRC even sees it — the CRC check will correctly flag it as corrupt (harmless for correctness, LINK-02 still holds), but it will inflate "corrupt batch" counts with events that were never actually link corruption, muddying any saturation/loss diagnostics built on top of that counter later (Phase 5). Size `recvfrom`'s buffer generously above the largest configured batch size, not tightly.

### Pattern 7: Link Protocol and headless ground consumer (reused from `.planning/research/ARCHITECTURE.md` Pattern 4, scoped to Phase 1's two implementations)

```python
# Source: pattern already specified in .planning/research/ARCHITECTURE.md Pattern 4,
# scoped here to exactly the two Phase 1 implementations (loopback, UDP)
from typing import Protocol, Optional

class Link(Protocol):
    def send(self, data: bytes) -> None: ...
    def recv(self, timeout: Optional[float] = None) -> Optional[bytes]: ...
    def close(self) -> None: ...

class LoopbackLink:
    """Pure in-memory, zero OS dependency — for tests that must run with no radio,
    no vehicle hardware, and no network stack at all."""
    def __init__(self):
        self._q: "queue.Queue[bytes]" = queue.Queue()
    def send(self, data: bytes) -> None:
        self._q.put(data)
    def recv(self, timeout=None) -> Optional[bytes]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None
    def close(self) -> None:
        pass

class UdpLink:
    """Wi-Fi/RFD900x stand-in — UDP's own inherent, unordered packet loss is a
    feature here, modeling the real radio link's lossy behavior more faithfully
    than TCP would (already established in ARCHITECTURE.md Pattern 4)."""
    def __init__(self, local_addr, remote_addr, recv_bufsize=4096):
        import socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(local_addr)
        self._remote = remote_addr
        self._bufsize = recv_bufsize  # size generously — see Pattern 6's recvfrom pitfall
    def send(self, data: bytes) -> None:
        self._sock.sendto(data, self._remote)
    def recv(self, timeout=None) -> Optional[bytes]:
        self._sock.settimeout(timeout)
        try:
            data, _ = self._sock.recvfrom(self._bufsize)
            return data
        except TimeoutError:
            return None
    def close(self) -> None:
        self._sock.close()
```

The headless ground consumer (GND-01) is a plain loop, no asyncio (matches CONTEXT.md's locked "no asyncio in Phase 1" and mirrors `ARCHITECTURE.md`'s reasoning that asyncio's value shows up only once the ground station serves multiple concurrent browser clients, which is Phase 2 scope):
```python
def run_ground_station(link: Link, dictionary, decoder_options, db):
    decoder = Decoder(dictionary, decoder_options)
    corrupt_batches = 0
    while True:
        raw = link.recv(timeout=1.0)
        if raw is None:
            continue
        try:
            payload = cobs.decode(raw[:-2])
            crc_ok = Crc16CcittFalse.calc(payload) == struct.unpack("<H", raw[-2:])[0]
            if not crc_ok:
                raise ValueError("CRC mismatch")
        except (cobs.cobs.DecodeError, ValueError, struct.error):
            corrupt_batches += 1
            continue
        for cfr_bytes in split_batch(payload):    # batcher.py's inverse
            frame = decoder.decode(cfr_bytes, batch_base_timestamp_us)
            print(db.decode_message(frame.frame_id, frame.payload))
```

### Anti-Patterns to Avoid

- **Reading a possibly-crashed MCAP archive with `mcap.reader.make_reader()`'s defaults.** Verified this session to raise a misleading `RecordLengthLimitExceeded` error rather than a clean "no footer" signal. Always use `NonSeekingReader(f).iter_messages(log_time_order=False)` for any session without a confirmed `.done` marker.
- **Trusting `mcap`'s default chunking to satisfy a count/time flush cadence.** `chunk_size` is bytes-only; a 250ms/1000-record requirement needs an explicit application-level scheduler layered on top of `use_chunking=False`, not tuning of `chunk_size`.
- **Treating a SIGKILL-based crash test as proof of fsync correctness.** It only proves the application calls `write()` at the right cadence; the OS page cache survives a process kill, so unsynced data can still "look" durable in that specific test. See Pattern 4.
- **Sizing a UDP `recvfrom()` buffer tightly to the expected batch size.** Silent truncation on an undersized buffer will masquerade as link corruption in loss statistics.
- **Building new capture code against `vspyx` for the consolidated logger.** Verified hang on hardware-free import in this session; `python-ics` is the better-evidenced choice for CAP-01.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Append-only crash-tolerant binary log format with recoverable records | A bespoke self-describing record format | `mcap` (with the `use_chunking=False` + explicit fsync pattern above) | Gets you record framing, an optional index/summary section, and free viewing via Foxglove Studio; the crash-recovery gap this research found is in *reader configuration*, not a reason to hand-roll the format itself |
| Byte-stream resync after corruption | A custom length-prefixed or delimiter scheme | `cobs` | Already the settled Phase 0 choice (`.planning/research/STACK.md`); length-prefixed framing has no bounded-worst-case recovery if the length field itself is corrupted (explicitly named as Anti-Pattern 5 in `.planning/research/ARCHITECTURE.md`) |
| Error detection over a batch of bytes | A custom checksum | `crccheck`'s CRC-16 implementation (or a hand-rolled 256-entry table, both acceptable per Phase 0's own STACK.md) | Well-understood Hamming-distance guarantees; not worth re-deriving |
| Thread-safe drop-oldest queue | A custom ring buffer with manual locking | `collections.deque(maxlen=N)` | Verified 12.5x faster than `queue.Queue` in this session's benchmark and already GIL-atomic for single-item append; reinventing this adds a lock for no benefit |

**Key insight:** every "don't hand-roll" item in this phase was already correctly identified in Phase 0's own research documents (`.planning/research/STACK.md`, `.planning/research/ARCHITECTURE.md`). This session's contribution is not picking different tools — it's verifying that the specific way those tools must be *called* (reader configuration, chunking flag, fsync placement) matches what the locked decisions actually require, which none of the prior research sessions tested against real library behavior.

## Common Pitfalls

### Pitfall 1: Reading a crashed MCAP file the "obvious" way recovers nothing, or crashes with a misleading error
**What goes wrong:** `mcap.reader.make_reader(open(path, "rb"))` (the top-level, documented entry point) raises `RecordLengthLimitExceeded` with a nonsensical record length on a footer-less file. `NonSeekingReader(f).iter_messages()`'s own default (`log_time_order=True`) recovers zero messages from a file with fifty perfectly intact records, because it buffers the whole stream before yielding anything.
**Why it happens:** Both defaults are optimized for the common case (a complete, `finish()`-ed file), and neither degrades gracefully for the crash-recovery case this phase specifically needs to exercise.
**How to avoid:** Always read recovery-path archives with `NonSeekingReader(f).iter_messages(log_time_order=False)`, catching `(mcap.exceptions.EndOfFile, struct.error)`. This should be a named utility function (`archive/reader.py` per the recommended structure) used by both the operator-facing recovery tool and the automated power-cut test, never re-derived inline.
**Warning signs:** A power-cut test "passes" by only checking that `.done` is absent, without actually attempting to read the archive back and count recovered records.

### Pitfall 2: `mcap`'s default chunking silently defers all durability past the locked 250ms/1000-record budget
**What goes wrong:** With `use_chunking=True` (the library default), up to 1 MB of messages can sit purely in an in-process `ChunkBuilder`, invisible to any fsync cadence applied to the underlying file object, because no bytes have reached the stream at all yet.
**Why it happens:** `mcap`'s chunking exists for compression and seek-indexing, both genuinely useful for a *general* MCAP writer, but the library conflates "when do bytes leave the process" with "when is a chunk considered complete," and only exposes control over the latter (via `chunk_size`, in bytes).
**How to avoid:** `use_chunking=False`, verified this session to make every `add_message()` call reach `stream.write()` immediately; layer the count/time fsync cadence on top of that as a separate, application-owned concern.
**Warning signs:** A durability test that passes with small synthetic loads (which happen to fill a 1MB chunk quickly) but silently regresses once real per-message sizes are smaller (raw CAN frames are ~15-30 bytes; reaching 1MB takes tens of thousands of frames).

### Pitfall 3: `vspyx` import can hang with no clear timeout on a machine without its full runtime context
**What goes wrong:** Verified this session — a bare `import vspyx` call, with no attempt to use hardware, hung for the entire 30-second test window with zero output, before even reaching `Application.New()`.
**Why it happens:** Not conclusively determined this session (exact root cause — license check, COM initialization, GUI subsystem probe — was not isolated), but the observed behavior is consistent with `vspyx` wrapping the full Vehicle Spy X desktop application engine rather than a minimal hardware SDK.
**How to avoid:** Do not build new car-side capture code against `vspyx`. If `src/neoVI_logger.py` is retained unmodified through Phase 2 per the Deferred decision, do not import it from any Phase 1 module, and do not assume its import is safe to attempt from a startup-critical code path (e.g., a config-driven "try vspyx, fall back to python-ics" pattern would risk an unattended logger hanging at boot).
**Warning signs:** Any Phase 1 test or startup path that imports `vspyx` and does not have an explicit, short timeout wrapped around the import itself.

### Pitfall 4: `queue.Queue`/`deque` throughput numbers from a dev laptop don't transfer directly to the CM4
**What goes wrong:** This session's ~1.14M ops/s (`queue.Queue`) and ~14.3M ops/s (`deque`) figures were measured on native Windows x86-64 CPython 3.12.10, not the CM4's Cortex-A72.
**Why it happens:** No CM4 hardware is available to this dev session per the phase's stated constraints.
**How to avoid:** Treat these numbers as directional evidence that neither primitive is a likely bottleneck at ~4,000 fps, not as a substitute for the soak test success criterion 3 explicitly requires on real hardware.
**Warning signs:** Citing this session's benchmark numbers as if they were measured on the target device.

### Pitfall 5: `os.fdatasync` and directory `os.fsync` are Linux-only — the dev laptop cannot fully exercise ARCH-04/ARCH-05
**What goes wrong:** `hasattr(os, "fdatasync")` is `False` on Windows (verified this session); `os.fsync()` on a directory file descriptor raises `PermissionError` on Windows (verified this session).
**Why it happens:** Both are POSIX-specific filesystem operations with no Windows NTFS equivalent exposed the same way.
**How to avoid:** Guard both calls with a platform check or a `getattr(os, "fdatasync", os.fsync)` fallback so the surrounding application logic (cadence counting, write-ordering) is still exercisable and testable on the dev laptop, even though the Linux-specific syscall itself is not.
**Warning signs:** A test suite that only runs on the dev laptop and claims full ARCH-04/ARCH-05 coverage without a platform-guard note.

## Code Examples

See Patterns 1–3, 6, 7 above — every code example in this document was constructed from and cross-checked against directly-executed behavior in this session (mcap read/write experiments, cobs/crccheck exercises, queue/deque benchmarks), not copied from library documentation.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Two parallel logger implementations (`new_logger.py`, `neoVI_logger.py`) | Single `python-ics`-based capture module, dual-bus, config-driven | This phase (partial — removal deferred to Phase 2 per locked decision) | CAP-01's consolidation half lands now; the "duplicate removed from repo" half does not |
| Decode-on-car, ship decoded JSON over stdout→stdin pipe | Encode-on-car (raw+compressed), decode-on-ground-station | Already settled as a Key Decision in PROJECT.md, implemented starting this phase | Bandwidth-appropriate direction; unchanged by this session's findings |
| CSV as the full-rate archive format | `mcap`, append-only, crash-recoverable via the verified non-default reader path | This phase | The actual crash-recovery mechanics required correction from what prior research assumed (see Pattern 2) |

**Deprecated/outdated:**
- Reading MCAP files via `mcap.reader.make_reader()`'s top-level default for anything that might be a crashed/incomplete session — this session's finding supersedes any assumption that the "obvious" public API call is crash-safe by default.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The exact cause of `vspyx`'s 30-second import hang (license check vs. COM init vs. GUI dependency) was not isolated | Pattern 5 / Pitfall 3 | If the hang is actually a fixable one-line config issue (e.g., a missing env var suppressing a license prompt), the SDK comparison's strength is overstated — though the fast-fail-vs-hang asymmetry itself was directly observed and doesn't depend on the root cause |
| A2 | `python-ics`'s hardware timestamp (`m.TimeSystem`) and `vspyx`'s (`point.GetAttribute("Timestamp")`) were not directly compared for accuracy/resolution this session | Pattern 5 | If one SDK's timestamp is meaningfully more accurate, that could push back toward `vspyx` despite the operational downsides found — worth a Phase 1 spike if timestamp precision becomes a concern once real hardware is available |
| A3 | CRC-16/CCITT-FALSE was recommended with no requirement mandating it | Pattern 6 | Low risk — this is explicitly a Claude's Discretion area per CONTEXT.md; any CRC-16 variant satisfies LINK-01/LINK-02's correctness requirement, this is a preference, not a correctness claim |
| A4 | The SIGKILL-doesn't-prove-fsync methodology point is stated as established practitioner consensus, not pinned to one canonical, directly-quotable source | Pattern 4 | Low risk to correctness (the underlying mechanism — page cache surviving a process kill — is basic, verifiable OS behavior, not itself in question), but the citation strength is CITED/consensus rather than a single authoritative reference |
| A5 | The `crccheck` package's presence in the dev environment despite D-06's "stays uninstalled" note was not traced to a specific cause | Package Legitimacy Audit | Low risk — flagged for the planner to resolve by deciding whether to adopt it into `requirements.txt` deliberately; does not block planning |

**If this table is empty:** N/A — five assumptions logged above, none blocking, all low-to-moderate risk.

## Open Questions

1. **Should Phase 1 pin `mcap`'s `compression` parameter at all, given `use_chunking=False` disables the chunk-level compression path entirely?**
   - What we know: `Writer.__init__` validates `compression` against `lz4`/`zstandard` availability regardless of `use_chunking`, but the compression codepath only executes inside `__finalize_chunk()`, which is never called when chunking is disabled.
   - What's unclear: whether a future Phase (8, MDF4 conversion / archive size) wants archive-side compression enough to revisit `use_chunking=True` with a small `chunk_size` instead — this session confirmed that path also recovers correctly (194/200), just with a different loss-bound shape (bytes, not time/count).
   - Recommendation: ship `use_chunking=False` for Phase 1 (matches CONTEXT.md's own stated rationale) and treat compression as a Phase 8 archive-size optimization if disk usage becomes a concern, not a Phase 1 concern — the phase description already frames durability, not disk economy, as this phase's driver.

2. **What is the actual per-frame CPU cost of `Encoder.encode()` on the CM4's Cortex-A72, replacing `.planning/research/ARCHITECTURE.md`'s explicitly-flagged "not yet benchmarked" MEDIUM-confidence estimate?**
   - What we know: the estimate (low single-digit µs/frame, <2% of one core at 4,000 fps) was never measured on real hardware, and this session's dev-laptop benchmarks (x86-64) don't substitute for an ARM measurement.
   - What's unclear: whether the encoder or the mcap write path is the actual bottleneck once both run concurrently under real thread scheduling on the CM4.
   - Recommendation: the phase's own success criterion 3 (soak test with logged queue high-water marks) is the mechanism that answers this — no further research action needed before planning, just ensure the plan's soak-test task captures per-stage timing, not just aggregate drop counts.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Native Windows CPython 3.12.10 | All Phase 1 development/testing | ✓ | 3.12.10 | — |
| `mcap` | ARCH-01/02/04/05 | ✓ (installed this session) | 1.4.0 | — |
| `cobs` | LINK-01/02 | ✓ (installed this session) | 1.2.2 | — |
| `crccheck` | LINK-01/02 | ✓ (pre-existing in this dev environment) | 1.3.1 | Hand-rolled CRC-16 table, zero-dependency |
| `python-ics` | CAP-01 capture | ✓ (installed this session) | `1!26.3.9` | — |
| Native Intrepid driver (`icsneo40.dll`) | Real hardware capture testing | ✗ (verified: `find_devices()` raises `RuntimeError`) | — | `python-ics` calls must be mocked/stubbed for hardware-free tests; the existing `TESTING_MODE`/VSB-buffer pattern in `neoVI_logger.py` does not apply to `python-ics` (that's a `vspyx`-specific mechanism) |
| `os.fdatasync` | ARCH-04's Linux flush cadence | ✗ on Windows dev box (✓ expected on CM4/Linux) | — | `getattr(os, "fdatasync", os.fsync)` — see Pattern 2 |
| Directory `os.fsync` | ARCH-05's write-ordering | ✗ on Windows dev box (✓ expected on CM4/Linux) | — | Platform-guard the call; validate for real only via CI-on-Linux or the physical power-pull test |
| neoVI CM4 hardware | Real-rate soak test, physical power-pull test (ARCH-03) | ✗ (not on hand per phase constraints) | — | Loopback/synthetic-load testing for everything except the physical durability proof, which genuinely requires the hardware and cannot be waived |
| RFD900x radio | Serial link (Phase 9 only) | ✗ (not purchased, per PROJECT.md) | — | Out of scope for Phase 1 by design (LINK-04 requires no-radio operation) |

**Missing dependencies with no fallback:**
- Physical CM4 + physical power interruption for ARCH-03's repeatable bench test — no software substitute satisfies this requirement; it must be scheduled once hardware is available, and Phase 1's plan should not claim ARCH-03 complete on the strength of the SIGKILL proxy alone.

**Missing dependencies with fallback:**
- Native Intrepid driver (mock/stub at the `FrameSource` boundary for hardware-free capture tests).
- `os.fdatasync`/directory `fsync` (portable fallback + platform guard, full coverage only on Linux).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 `[VERIFIED: installed, 127 tests currently passing via `python -m pytest -q` this session]` |
| Config file | `pytest.ini` (`pythonpath = src`, `testpaths = tests`, `addopts = -ra`) |
| Quick run command | `python -m pytest -x -q --tb=short` (matches `.planning/config.json`'s `workflow.test_command`) |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAP-02/CAP-03/CAP-04 | Fan-out sustains rate; telemetry never blocks archive | integration | `pytest tests/test_fanout.py -x` | ❌ Wave 0 |
| CAP-05/CAP-06 | Discards and errors counted, not swallowed | unit | `pytest tests/test_fanout.py::test_discard_counting -x` | ❌ Wave 0 |
| ARCH-01/ARCH-04 | MCAP writer produces valid, readable archive at batched cadence | integration | `pytest tests/test_archive_writer.py -x` | ❌ Wave 0 |
| ARCH-02/ARCH-03 | Crash-mid-write recovers all pre-crash complete records | integration (SIGKILL proxy) + manual (physical pull) | `pytest tests/test_archive_crash_recovery.py -x` | ❌ Wave 0 — this test IS the automated proxy from Pattern 4, and must document its own scope limit per that pattern |
| ARCH-05 | `.done` written only after close+flush, correct ordering | unit | `pytest tests/test_session.py::test_done_marker_ordering -x` | ❌ Wave 0 |
| LINK-01/LINK-02 | COBS+CRC frame/deframe, corrupted input discarded+counted | unit | `pytest tests/test_framing.py -x` | ❌ Wave 0 |
| LINK-03/LINK-04 | Same encode→decode chain over LoopbackLink and UdpLink | integration | `pytest tests/test_link.py -x` | ❌ Wave 0 |
| GND-01 | End-to-end capture→archive + capture→encode→frame→link→deframe→decode | integration | `pytest tests/test_end_to_end.py -x` | ❌ Wave 0 |
| OPS-05 | Config loader rejects unknown keys, missing keys, malformed values | unit | `pytest tests/test_logger_config.py -x` | ❌ Wave 0 — mirror `tests/test_gate_config.py`'s existing pattern exactly |
| CAP-02 (soak) | Sustained ~4,000 fps, zero archive drops, HWM/discard counts logged | soak (slower, not part of quick run) | `pytest tests/test_soak.py -x --tb=short` (mark `@pytest.mark.slow`, excluded from quick run) | ❌ Wave 0 — reuse `telemetry.synth.generator.SyntheticFrameSource` as the load generator, driven through the real fan-out/writer code instead of the measurement CLI |

### Sampling Rate
- **Per task commit:** `python -m pytest -x -q --tb=short` (excludes the soak test via a `slow` marker, keeps the loop fast)
- **Per wave merge:** `python -m pytest -q` (full suite, including the soak test)
- **Phase gate:** Full suite green before `/gsd-verify-work`, plus the ARCH-03 physical power-pull test result recorded in the phase's verification artifacts even though it cannot be automated

### Wave 0 Gaps
- [ ] `tests/test_fanout.py` — covers CAP-02/03/04/05/06
- [ ] `tests/test_archive_writer.py` — covers ARCH-01/04, exercises the Pattern 2 writer directly
- [ ] `tests/test_archive_crash_recovery.py` — covers ARCH-02/03's automated proxy half, uses Pattern 2's recovery function and Pattern 4's SIGKILL methodology with the documented scope-limit comment
- [ ] `tests/test_session.py` — covers ARCH-05, session naming (UTC + monotonic fallback)
- [ ] `tests/test_framing.py` — covers LINK-01/02, exercises `cobs`/`crccheck` directly per Pattern 6
- [ ] `tests/test_link.py` — covers LINK-03/04, `LoopbackLink` and `UdpLink` against the same test suite (Pattern 7)
- [ ] `tests/test_end_to_end.py` — covers GND-01, full chain over loopback
- [ ] `tests/test_logger_config.py` — covers OPS-05, mirrors `tests/test_gate_config.py`
- [ ] `tests/test_soak.py` — covers CAP-02's sustained-rate claim, marked `slow`
- [ ] `tests/conftest.py` additions — a `logger_config` fixture (mirroring the existing `gate_config` fixture) once `config/logger.json` exists

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-trusted-team embedded system; no user accounts anywhere in this phase |
| V3 Session Management | no | "Session" here means a logging run, not an auth session — no ASVS V3 applicability |
| V4 Access Control | no | No multi-tenant or privilege-boundary concept in this phase |
| V5 Input Validation | yes | Config loader (`GateConfigError`-style typed loader for `config/logger.json`, unknown-key-is-error per CONTEXT.md); MCAP/CFR/batch decode paths (all malformed input raises a named exception, never a bare `except: pass`, matching `decoder.py`'s existing convention) |
| V6 Cryptography | no (explicitly not applicable) | No cryptographic guarantee is claimed anywhere in this phase — `dictionary.py`'s `dict_version` byte is already explicitly documented as NOT a cryptographic integrity guarantee, and the CRC-16 in this phase's framing is an error-detection code, not an authentication/integrity mechanism. This must stay documented, not silently reinterpreted as security later |
| V12 File & Resources | yes | Config-provided paths (DBC path, archive output directory) are read from `config/logger.json`; since this is a single-trusted-team system with no untrusted input source for the config file itself, path traversal is low-risk but the loader should still resolve and validate paths exist before use (matches the existing `dbc_path` resolution pattern in `tests/conftest.py`/`dictionary.py`) rather than trusting a config value blindly at the point of use |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/corrupted UDP batch crashes or hangs the ground-station decode loop | Denial of Service | `LINK-02`'s discard-and-count requirement, implemented via the `except (cobs.cobs.DecodeError, ValueError, struct.error)` pattern in Pattern 7 — every layer of the deframe/decode chain must raise a specific, caught exception type, never propagate an unhandled one that kills the consumer process |
| Config file with unknown/malformed keys silently defaults instead of failing | Tampering (accidental — no adversary implied, but a wrong config could silently mis-stream data) | Fail-closed typed loader per CONTEXT.md's locked decision, mirroring `GateConfigError`'s existing precedent |
| Unauthenticated telemetry link (anyone in RF range with a matching NETID could receive; Phase 9 concern, noted here for completeness) | Information Disclosure | Already assessed as low-priority in `.planning/research/PITFALLS.md`'s Security Mistakes section — ISM-band, short-range, single-team competition context. No action required in Phase 1 (loopback/UDP have no equivalent RF exposure); re-assess if alarms or any actuation is ever added downstream of the decoded signals |
| `os.fsync`/`fdatasync` call omitted or silently no-op'd in a refactor | Tampering (data-integrity, not confidentiality) | Not a classic ASVS category, but directly load-bearing for this phase's core value — recommend a Wave 0 test asserting the fsync call is actually invoked (e.g., via `unittest.mock.patch` on `os.fsync`/`os.fdatasync` and asserting call count matches the configured cadence), not just that the archive file happens to be readable in a given test run |

## Sources

### Primary (HIGH confidence)
- `mcap` 1.4.0 — installed and directly exercised this session (`Writer`/`Reader`/`NonSeekingReader`/`SeekingReader` source read via `inspect.getsource`; write/crash/recover experiments run against real files)
- `cobs` 1.2.2 — installed and directly exercised this session (encode/decode/corruption behavior)
- `crccheck` 1.3.1 — already installed; CRC-16 variants directly exercised this session
- `python-ics` `1!26.3.9` and `vspyx` 1.3.0.dev580 — both installed this session; hardware-free import/init behavior directly observed
- PyPI registry (`pip index versions`, `pip download`) — package existence/version currency verified this session for all six packages named above
- `gsd-tools query package-legitimacy check` — run this session for `mcap`, `cobs`, `python-ics`, `crccheck`
- `src/new_logger.py`, `src/neoVI_logger.py`, `src/telemetry/wire/*.py`, `src/telemetry/synth/generator.py`, `src/telemetry/measure/config.py` — read in full this session
- `.planning/phases/01-.../01-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/PROJECT.md`, `.planning/phases/00-.../00-DECISION.md` — read in full this session

### Secondary (MEDIUM confidence)
- `.planning/research/ARCHITECTURE.md`, `.planning/research/STACK.md`, `.planning/research/PITFALLS.md` — Phase-0-era research, largely reused/cross-checked and in one case (mcap complete-chunk recovery claim) empirically re-verified and confirmed accurate-but-incomplete (accurate for chunked files, missing the non-default-reader-configuration caveat)
- vspyx installability and PyPI page — [Vehicle Spy X docs](https://docs.intrepidcs.net/vspyx/release/) and [PyPI vspyx](https://pypi.org/project/vspyx/), cross-checked against this session's own `pip download` result

### Tertiary (LOW confidence)
- General crash-consistency testing methodology (SIGKILL vs. fsync boundary testing) — WebSearch-surfaced academic sources (FAST/SOSP filesystem crash-consistency literature) corroborate the general practice of injecting crashes at persistence boundaries, but no single source was found pinning the exact SIGKILL-vs-page-cache claim as stated; treat as established practitioner consensus reconstructed from first principles (page cache surviving a process kill is basic, independently verifiable OS behavior) rather than a single authoritative citation
- Exact root cause of the `vspyx` import hang — not isolated this session, flagged as Assumption A1

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package verified installable and version-current against PyPI this session
- Architecture (MCAP crash mechanics, SDK comparison): HIGH — directly executed, not inferred from documentation
- Architecture (queue/deque throughput): MEDIUM — verified this session but on non-target hardware
- Pitfalls: HIGH for the mcap/reader and SDK-hang findings (directly reproduced); MEDIUM for the SIGKILL-methodology framing (sound reasoning, imperfectly single-sourced)

**Research date:** 2026-08-01
**Valid until:** 30 days for the library-behavior findings (mcap/cobs/crccheck APIs are stable, low churn); re-verify SDK behavior (Pattern 5) if either `python-ics` or `vspyx` receives a major version bump before Phase 1 execution, given both are calendar-versioned and release frequently.
