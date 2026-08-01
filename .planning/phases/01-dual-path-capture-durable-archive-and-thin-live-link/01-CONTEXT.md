# Phase 1: Dual-Path Capture — Durable Archive and Thin Live Link - Context

**Gathered:** 2026-08-01
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 16 questions across 4 areas; areas 1–3 accepted as proposed, area 4 Q4 overridden by the user

<domain>
## Phase Boundary

One logger process on the car captures both CAN buses, writes every frame to a crash-safe MCAP
archive on the onboard NVMe, and simultaneously feeds a second, lossy consumer that encodes the
Phase 0 critical-channel subset, frames it with COBS+CRC, and pushes it over a swappable link to a
headless ground-station consumer that deframes, decompresses, and DBC-decodes it — with no radio
hardware anywhere in the chain.

**In scope:** single-logger consolidation, dual-bus capture, session lifecycle, MCAP archive +
durability, capture fan-out with divergent overflow policies, batching, COBS+CRC framing, the link
abstraction with loopback and UDP implementations, a headless ground consumer, config file, and a
dependency manifest.

**Out of scope (later phases):** the browser dashboard and Python WebSocket server (Phase 2,
GND-02..05), Node server retirement and legacy logger deletion (Phase 2 — see Deferred), unattended
boot/service supervision (Phase 3), keyframes and dictionary-version negotiation (Phase 4),
leaky-bucket shaping and the saturation soak (Phase 5), live plots (Phase 6), alarms (Phase 7),
archive pull and MDF4 conversion (Phase 8), real radio hardware (Phase 9).

</domain>

<decisions>
## Implementation Decisions

### Session Lifecycle & Archive Layout

- **A session is one logger process run.** No time- or size-based rotation within a run. A run is
  bounded by ignition, and an abrupt power cut then naturally leaves the session without its
  completion marker — which is exactly what ARCH-05 and success criterion 2 want to observe.
- **Session naming is UTC `YYYYMMDD-HHMMSS` with a monotonic counter fallback.** The CM4 has no
  RTC battery, so the wall clock can be epoch-garbage at boot; the counter keeps sessions
  orderable and uniquely named even when the timestamp is meaningless. Record which of the two
  produced the name so post-session analysis can tell a real timestamp from a fallback.
- **Completion is marked by a sidecar `.done` file** written only after the archive writer's
  close-and-flush returns. ARCH-05 names this artifact literally. Never write it optimistically.
- **One MCAP file per session.** MCAP is append-only and crash-safe; chunking would add recovery
  seams without buying durability.

### Capture Fan-Out & Backpressure

- **One capture thread fans out to two independent queues** — a large one for the archive, a small
  bounded one for telemetry. This makes CAP-04 structural rather than a promise: the telemetry
  consumer holds no handle that could block capture or the archive path. Follows the existing
  queue-decoupling pattern in `src/new_logger.py`.
- **The telemetry queue drops the OLDEST entry when full** (evict head, then enqueue). PROJECT.md's
  bufferbloat decision is explicit that a full queue must not make delivered data stale, and this
  is the Phase 1 groundwork for LINK-05's drop-oldest shaping in Phase 5.
- **The archive flushes on a batched cadence — whichever of record-count or elapsed-time comes
  first.** Starting values 1000 records / 250 ms, both in config. ARCH-04 requires that flushing
  never stall capture.
- **If the ARCHIVE queue fills, that is a fatal condition: log loudly and stop the session.**
  CAP-03 says the archive consumer never drops, so silently discarding archive frames would break
  the project's core value. A hard, visible stop is the honest failure mode; an unbounded queue
  would just relocate the failure to an OOM kill.
- **Every discard, high-water mark, and error is counted and reported** (CAP-05, CAP-06): telemetry
  discard counts, both queues' high-water marks, and hardware/decode errors logged with frame
  context — never a bare `except Exception: pass`.

### Link Abstraction & Ground Station

- **Two link implementations ship in Phase 1: in-process loopback and UDP unicast.** LINK-04
  requires the whole chain to run radio-free; loopback proves the layering and UDP proves a real
  network hop with real packet loss. A serial implementation waits for Phase 9.
- **The link interface is a synchronous `send(bytes)` / `recv() -> bytes` Protocol**, with the
  transport owning its own thread. This mirrors the `FrameSource` Protocol style already
  established in `src/telemetry/wire/frame_source.py`. No asyncio in Phase 1.
- **The Phase 1 ground station is a headless CLI consumer** — deframe → decompress → DBC-decode →
  print/record. The browser dashboard and the single-process Python server are Phase 2 (GND-02..05).
- **The critical-channel allowlist filters ON THE CAR, at the telemetry fan-out, before the
  encoder.** Filtering upstream of encoding cuts CPU and queue pressure as well as bandwidth,
  rather than paying to encode frames that are then thrown away.

### Config & Provisioning

- **Config is JSON, loaded by a typed loader that raises a named error** — the same shape as Phase
  0's `config/gate.json` + `GateConfigError`, so the project has one config idiom rather than two.
- **`--config` names the file, defaulting to `config/logger.json`. CLI flags override individual
  fields. Unknown keys are an error, not a warning** — Phase 0's fail-closed precedent, which
  exists so a typo in a key name cannot silently leave a default in place.
- **`requirements.txt` with exact pins.** OPS-06's own wording, and consistent with Phase 0 pinning
  `cantools==42.0.3` / `pytest==9.1.1`.
- **The subset allowlist is read from config at startup and never baked into code** (carried from
  the Phase 0 decision and now an Active requirement in PROJECT.md). Changing which messages the
  live path carries must cost a config edit plus a restart of both ends — nothing more.

### Claude's Discretion

- Exact module layout under `src/telemetry/` beyond the existing `wire/`, `synth/`, `measure/`
  packages — follow the D-07 target-rebuild layout already established.
- MCAP schema/channel modelling (how CAN frames map onto MCAP channels and message encodings).
- Thread vs. process for the ground consumer, queue sizing defaults beyond the two named above,
  and log formatting.
- Whether the UDP link sends one datagram per batch or coalesces.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- `src/telemetry/wire/frame_source.py` — `RawFrame` NamedTuple and the `FrameSource` Protocol
  (`frames() -> Iterator[RawFrame]`). Phase 1 adds a live hardware source implementing it, and
  should also add the deferred real-log reader the Phase 0 re-check condition needs.
- `src/telemetry/wire/encoder.py` — `Encoder(dictionary, options)`, `EncoderOptions`, and the
  `CfrError` / `BatchWindowExceeded` / `PayloadTooLong` error family. Phase 1 consumes this
  unchanged; D-05 makes it the shipped encoder, not analysis code.
- `src/telemetry/wire/dictionary.py`, `decoder.py`, `overhead.py` — the ID dictionary, the matching
  decoder for the ground station, and the framing-overhead model.
- `src/telemetry/measure/config.py` — the typed-loader-with-named-error pattern to copy for
  `config/logger.json`.
- `src/new_logger.py` — the capture/writer thread split, `queue.Queue` decoupling, `_STOP` sentinel
  shutdown, and the `CHANNEL_MAP` / NetworkID resolution logic are the working reference for
  talking to the hardware, even though the file itself is superseded.

### Established Patterns

- Threads named for debugging (`name="capture"`, `name="writer"`); daemon for capture,
  non-daemon for the writer so it flushes before exit.
- Shutdown via `threading.Event` polled by every loop, plus a sentinel pushed onto the queue.
- `log()` / `debug()` helpers writing to stderr; stdout reserved for machine-readable output.
- Phase 0 convention: fail closed on malformed config with a named exception rather than
  defaulting.

### Integration Points

- `epbr2026_DBC_v1.0.dbc` via cantools — structure only on the car (ID dictionary); full decode
  happens on the ground station.
- `config/gate.json` sits beside the new `config/logger.json`; both use the same loader idiom.
- The 12-message critical-channel subset from `00-DECISION.md` is the initial allowlist content.

</code_context>

<specifics>
## Specific Ideas

- The archive path and the live path share one capture fan-out and neither proves anything alone —
  this is why the roadmap ships them together rather than in sequence.
- Success criterion 2 is a *physical* test: power is pulled repeatedly, not simulated with a
  SIGKILL. Plan for a repeatable procedure someone can actually run on the bench (ARCH-03).
- Success criterion 3 is a sustained full-rate run (~4,000 frames/s combined) reporting zero
  archive-path drops, with queue high-water marks and discard counts surfaced — not merely absent
  errors.
- Phase 0's gate rests on a modelled stream. Phase 1's first bench or track session is the
  designated moment to re-run it against real captured traffic, which is why the real-log
  `FrameSource` reader belongs in this phase.

</specifics>

<deferred>
## Deferred Ideas

- **Legacy logger deletion moved to Phase 2 (user decision).** The user chose to keep
  `src/neoVI_logger.py`, `src/new_logger.py`, `src/references.py`, and `src/neoVI_sender.py` in
  place through Phase 1 for rollback safety. Consequence, recorded deliberately: **CAP-01 and
  Phase 1 success criterion 1 both require the duplicate implementation to be *gone from the
  repository*, and that clause will NOT be met in Phase 1.** Phase 1 satisfies the other half —
  a single new implementation captures both buses concurrently. The removal clause should be
  re-targeted to Phase 2, which is already the retirement phase (GND-03 removes the Node server),
  so all legacy deletion lands together. Planning should not quietly claim criterion 1 as met.
- Serial / pyserial link implementation — Phase 9, with the real RFD900x.
- Keyframes and dictionary/allowlist version negotiation — Phase 4.
- Leaky-bucket shaping and the p99-latency saturation soak — Phase 5.
- MDF4 conversion and automated archive pull — Phase 8.
- Hand-review of Phase 0's 12 checksum-bucket classifier candidates — still open, non-blocking.

</deferred>
