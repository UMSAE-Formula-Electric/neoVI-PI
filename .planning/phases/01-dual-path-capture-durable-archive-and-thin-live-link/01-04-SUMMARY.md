---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 04
subsystem: telemetry-pipeline
tags: [mcap, cobs, crccheck, cantools, fanout, framing, archive, link, tracer]

# Dependency graph
requires:
  - phase: 01-02
    provides: Wave 0 test placeholders, requirements.txt, package-legitimacy approval for mcap/cobs/crccheck/python-ics
  - phase: 01-03
    provides: config/logger.json + telemetry.logger.config typed loader (LoggerConfig, load_logger_config, resolve_allowlist)
provides:
  - Real, production-quality COBS+CRC-16 framing (telemetry.framing)
  - Batch container assembly/disassembly with a one-byte-per-record length prefix (telemetry.wire.batcher)
  - The Link Protocol and its first implementation, LoopbackLink (telemetry.link)
  - The durable MCAP archive writer and session/`.done`-marker lifecycle (telemetry.archive)
  - The capture fan-out — the single point where the archive and telemetry paths diverge (telemetry.capture.fanout)
  - The ground-station byte-stream deframer with per-failure-mode corruption counters (telemetry.ground.deframe)
  - A green, committed end-to-end proof (tests/test_end_to_end.py) that the whole Phase 1 spine holds together on one frame
affects: [01-05, 01-06, 01-07, 01-08, 01-09, 01-10, 01-11, 01-12, 01-13]

# Tech tracking
tech-stack:
  added: []  # mcap/cobs/crccheck already pinned in requirements.txt by 01-02; this plan is their first real usage
  patterns:
    - "CRC-16 trailer packed INSIDE the COBS envelope, delimiter outside — corrects 01-RESEARCH.md Pattern 7's sketch"
    - "mcap.writer.Writer(f, use_chunking=False) + explicit application-level fsync cadence (record-count-or-time), never mcap's own chunking"
    - "ArchiveWriter.is_closed as a structural precondition mark_done() enforces, not a calling convention"
    - "deque(maxlen=N) fullness checked BEFORE append to compute discard counts — deque gives no after-the-fact eviction signal"
    - "Deframer.feed() as a byte-stream generator (not datagram) so the same class serves UDP now and serial later with no change"

key-files:
  created:
    - src/telemetry/framing/__init__.py
    - src/telemetry/framing/errors.py
    - src/telemetry/framing/crc16.py
    - src/telemetry/framing/cobs_frame.py
    - src/telemetry/wire/batcher.py
    - src/telemetry/link/__init__.py
    - src/telemetry/link/base.py
    - src/telemetry/link/loopback.py
    - src/telemetry/archive/__init__.py
    - src/telemetry/archive/record.py
    - src/telemetry/archive/writer.py
    - src/telemetry/archive/session.py
    - src/telemetry/capture/__init__.py
    - src/telemetry/capture/fanout.py
    - src/telemetry/ground/__init__.py
    - src/telemetry/ground/deframe.py
  modified:
    - tests/test_end_to_end.py

key-decisions:
  - "CRC-16 trailer placed inside the COBS envelope, not outside as 01-RESEARCH.md Pattern 7 sketched — a raw CRC-16 value can contain 0x00, which would let a delimiter-scanning receiver split one valid frame in half; only the corrected ordering guarantees the sole 0x00 in the framed stream is the real delimiter (LINK-01's resync property)"
  - "mcap schema/channel modelling: one shared, encoding-less schema (mcap's own convention for 'no formal schema'), one channel per configured channel name at topic /can/{name} — verified against the real mcap==1.4.0 Writer signatures via inspect.signature before coding against them, not against memory or RESEARCH.md prose"
  - "ArchiveWriter.add() takes (channel_name, RawFrame) rather than a CapturedFrame, keeping telemetry.archive decoupled from telemetry.capture's NamedTuple"
  - "Deframer carries a seventh counter, buffer_overflow_count, beyond the six the plan names explicitly (batches_ok/cobs_failures/crc_failures/batch_format_failures/records_decoded/record_decode_failures) — required by the action text's own T-01-05 buffer-cap mitigation ('discard the pending bytes and count the event'), not a scope addition"

patterns-established:
  - "Exception-family shape for new subsystems: one base (FramingError), specific subclasses (CobsDecodeFailed/CrcMismatch/BatchFormatError), one-line docstring per class — mirrors wire/encoder.py's CfrError family"
  - "Every new module uses logging.getLogger(__name__), never a hand-rolled print/log() helper"

requirements-completed: [ARCH-01, ARCH-05, CAP-03, CAP-04, LINK-01, LINK-02, LINK-03, LINK-04, GND-01, OPS-04]

coverage:
  - id: D1
    description: "One frame submitted to FanOut lands in a readable, non-empty MCAP archive on disk with a .done marker written only after close-and-flush returns"
    requirement: "ARCH-01"
    verification:
      - kind: e2e
        ref: "tests/test_end_to_end.py#test_one_frame_reaches_the_archive_and_the_pit"
        status: pass
    human_judgment: false
  - id: D2
    description: "The same frame crosses allowlist filtering, CFR encoding, batching, CRC-16, COBS, and LoopbackLink, and DBC-decodes on the ground side to the exact signal values it was built from"
    requirement: "LINK-01"
    verification:
      - kind: e2e
        ref: "tests/test_end_to_end.py#test_one_frame_reaches_the_archive_and_the_pit"
        status: pass
    human_judgment: false
  - id: D3
    description: "A batch corrupted in transit (one flipped byte) is discarded and counted — yields nothing, raises nothing, increments exactly one corruption counter"
    requirement: "LINK-02"
    verification:
      - kind: e2e
        ref: "tests/test_end_to_end.py#test_corrupted_batch_is_discarded_and_counted_not_decoded"
        status: pass
    human_judgment: false

duration: 55min
completed: 2026-08-01
status: complete
---

# Phase 1 Plan 4: Tracer — One Frame End-to-End Through Archive and Thin Live Link Summary

**Production-quality COBS+CRC-16 framing, an mcap-backed durable archive writer, and a capture fan-out proven together on one CAN frame with no radio, hardware, or socket in the chain (tests/test_end_to_end.py, both assertions green).**

## Performance

- **Duration:** 55 min
- **Started:** 2026-08-01T18:58:00Z (approx.)
- **Completed:** 2026-08-01T19:53:00Z
- **Tasks:** 1 (the tracer — twelve sub-deliverables inside one task, per plan)
- **Files modified:** 17 (16 created, 1 test file rewritten)

## Accomplishments

- One CAN frame travels the complete Phase 1 spine end to end: capture fan-out → MCAP archive on disk, and in parallel capture fan-out → allowlist filter → CFR encode → batch → CRC-16 → COBS → `LoopbackLink` → deframe → CFR decode → DBC decode — proven in a single committed test, `tests/test_end_to_end.py`, with real production code at every layer (not a spike).
- Corrected `01-RESEARCH.md` Pattern 7's framing sketch: the CRC-16 trailer is packed **inside** the COBS envelope (`cobs.encode(payload + crc_bytes)`), not appended outside it, so the only `0x00` byte anywhere in a framed segment is the real delimiter — a raw CRC-16 value can itself contain `0x00`, and Pattern 7's ordering would have let that split one valid frame into two fragments at a false delimiter.
- Built the durable MCAP archive writer directly against the real, `inspect.signature`-verified `mcap==1.4.0` `Writer` API (`__init__`, `start`, `register_schema`, `register_channel`, `add_message`, `finish`) — not against memory or RESEARCH.md prose — per critical constraint #2. `ArchiveWriter` owns its file object, disables `mcap`'s own byte-size chunking (`use_chunking=False`), and layers an explicit record-count-or-time fsync cadence on top, exactly as `01-RESEARCH.md` Pattern 2 verified is required.
- `ArchiveWriter.is_closed` is a structural precondition `archive/session.mark_done()` enforces (raises if not true) — ARCH-05's "only after close-and-flush returns" cannot be forgotten by a caller, it is checked.
- `capture/fanout.py`'s `FanOut.submit()` is the single, non-blocking divergence point between the archive queue (never-drop, fatal-if-full) and the telemetry deque (drop-oldest, discard-counted via a before-append fullness check) — CAP-03/CAP-04 hold structurally, not by convention.
- `ground/deframe.py`'s `Deframer` proves LINK-02 rather than merely asserting it: the test's second assertion flips one byte inside a real framed batch and confirms the deframer yields nothing, raises nothing, and increments exactly one corruption counter.
- Computed, not estimated, the batcher's one-byte-per-record length-prefix cost against the real twelve-message critical-channel subset using `telemetry.wire.overhead`'s own functions (see "Recomputed Subset Bit Rate" below).

## Task Commits

1. **Task 1: End-to-end "one frame reaches the pit and the archive" — one path only** - `ee052bd` (feat)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `src/telemetry/framing/errors.py` — `FramingError`/`CobsDecodeFailed`/`CrcMismatch`/`BatchFormatError`, mirroring `wire/encoder.py`'s `CfrError` family shape
- `src/telemetry/framing/crc16.py` — CRC-16/CCITT-FALSE via `crccheck.crc.Crc16CcittFalse`; `crc16()`, `pack_crc()`, `verify_crc()`
- `src/telemetry/framing/cobs_frame.py` — `frame()`/`unframe()`; CRC trailer inside the COBS envelope, delimiter outside (the Pattern 7 correction)
- `src/telemetry/wire/batcher.py` — `BatchHeader`, `pack_batch()`, `split_batch()`; 13-byte `"<BBQHB"` header asserted at import time against `overhead.BATCH_HEADER_BYTES`; one-byte length-prefixed records
- `src/telemetry/link/base.py` — the `Link` Protocol (`send`/`recv`/`close`)
- `src/telemetry/link/loopback.py` — `LoopbackLink`, wrapping a `queue.Queue`
- `src/telemetry/archive/record.py` — `pack_frame()`/`unpack_frame()`, the archive's raw-frame on-disk layout (`"<IB"` + payload)
- `src/telemetry/archive/writer.py` — `ArchiveWriter`: owns the file object, `use_chunking=False`, record-count-or-time fsync cadence, `is_closed` property
- `src/telemetry/archive/session.py` — `SessionPaths`, `new_session()` (UTC-named), `mark_done()` (writer-closed precondition + directory fsync guarded for Windows)
- `src/telemetry/capture/fanout.py` — `CapturedFrame`, `FanOutCounters`, `FanOut` (the fan-out divergence point)
- `src/telemetry/ground/deframe.py` — `DeframeCounters`, `Deframer` (byte-stream feed, per-failure-mode counting)
- `tests/test_end_to_end.py` — replaces 01-02's placeholder skip with the tracer's own two-assertion proof

## Decisions Made

- **CRC-16 variant:** CRC-16/CCITT-FALSE (`crccheck.crc.Crc16CcittFalse`), matching `01-RESEARCH.md` Pattern 6's recommendation — a Claude's Discretion area, no requirement mandates a specific variant.
- **MCAP schema modelling:** one shared, encoding-less schema (`encoding=""`, `data=b""`, per `mcap`'s own `register_schema` docstring convention for "no schema") registered once, then one channel per configured channel name at topic `/can/{channel_name}`. Verified this is a valid, round-trippable choice by writing and reading back a real archive file with `mcap.reader.make_reader()` during development (not part of the committed test — the committed test only asserts existence/non-emptiness/`.done`, per the plan's own `<done>` criteria).
- **ArchiveWriter's public API takes `(channel_name: str, frame: RawFrame)`**, not a `CapturedFrame`, so `telemetry.archive` has no import-time coupling to `telemetry.capture`'s `NamedTuple`.
- **Subject message for the tracer test:** `M195_Pedal_Press_Percent` (frame ID `0xC3`, single signal `Pedal_Press_Percent`) — on the config allowlist, simple enough to assert an exact known-value DBC decode against.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added a seventh `Deframer` counter, `buffer_overflow_count`**
- **Found during:** Task 1, writing `ground/deframe.py`
- **Issue:** The plan's task text names six `DeframeCounters` fields explicitly (batches OK, COBS failures, CRC failures, batch format failures, records decoded, record decode failures) but separately requires, in the same paragraph, that an unterminated stream "discard its pending bytes and increment a counter" when the accumulation buffer cap is exceeded (T-01-05's DoS mitigation). No counter name for that event is among the six listed.
- **Fix:** Added `buffer_overflow_count: int = 0` to `DeframeCounters` and incremented it in `Deframer.feed()` when the residual buffer exceeds `max_buffer_bytes` with no delimiter present.
- **Files modified:** `src/telemetry/ground/deframe.py`
- **Verification:** Covered implicitly by the corrupted-batch test's zero-count assertions on the clean path (`test_one_frame_reaches_the_archive_and_the_pit` asserts `buffer_overflow_count == 0`); the overflow-triggering case itself is Wave-0-deferred to `01-08`'s framing test suite per the phase's own test-ownership split (`test_framing.py` is "Filled by: 01-08").
- **Committed in:** `ee052bd` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 missing-critical, mandated by the plan's own T-01-05 threat-model text)
**Impact on plan:** No scope creep — the plan's action text required this counter to exist even though it wasn't in the six-item enumeration; this fix reconciles the two.

## Issues Encountered

None — the real `mcap==1.4.0` API matched `01-RESEARCH.md` Pattern 2's reference implementation closely once schema/channel registration signatures were verified directly (`inspect.signature`), and every other library (`cobs`, `crccheck`) behaved exactly as Pattern 6 documented.

## Recomputed Subset Bit Rate (per critical constraint #5)

`01-DECISION.md`'s twelve-message critical-channel subset totals **74.62 kbit/s** under Phase 0's D-06 model (6-byte CFR header only, no per-record length prefix, `batch_frames=100`). This plan's batcher adds one length-prefix byte per record inside each batch. Recomputed, per message, using `telemetry.wire.overhead.overhead_breakdown()` against each subset message's real `clean_bytes_per_frame` (from `00-REPORT.csv`, `bracket=typical`) plus the new 1-byte prefix, amortized over the same 100-frame batch assumption:

| Message | Rate (Hz) | Old all-in B/frame | New all-in B/frame | Old kbit/s | New kbit/s |
|---|---|---|---|---|---|
| M176_Fast_Info | 333.33 | 9.6804 | 10.6975 | 25.8145 | 28.5265 |
| M192_Command_Message | 200.00 | 12.6147 | 13.5861 | 20.1834 | 21.7378 |
| M166_Current_Info | 100.00 | 10.5216 | 11.5227 | 8.4173 | 9.2182 |
| M167_Voltage_Info | 100.00 | 10.5020 | 11.5035 | 8.4016 | 9.2028 |
| CAN_WHEEL_SPEED | 25.47 | 10.5777 | 11.5765 | 2.1550 | 2.3585 |
| BRAKE_TEMPS | 25.47 | 10.6001 | 11.5985 | 2.1596 | 2.3630 |
| M195_Pedal_Press_Percent | 25.47 | 7.1385 | 8.1927 | 1.4544 | 1.6691 |
| Battery_Volt_1_Overall_Param_Std | 12.98 | 13.2523 | 14.2108 | 1.3765 | 1.4760 |
| CAN_VEHICLE_SPEED | 25.47 | 6.4966 | 7.5530 | 1.3236 | 1.5388 |
| HTL_CH_ID_SAFETY_LOOP_STATUS | 25.47 | 6.1284 | 7.1918 | 1.2486 | 1.4652 |
| HTL_CH_ID_BRAKE_PRESSED | 25.47 | 6.1276 | 7.1910 | 1.2484 | 1.4650 |
| M160_Temperature_Set_1 | 10.00 | 10.5105 | 11.5120 | 0.8408 | 0.9210 |

**Recomputed subset total: 81.94 kbit/s** (up from 74.62 kbit/s — **+7.32 kbit/s, +9.8%**). This is a measured recomputation via `overhead_breakdown()`, not an estimate: each row's "new" total-batch clean bytes is `(clean_bytes_per_frame + 1) * 100`, passed through `overhead_breakdown(total_clean, 100)`, then converted to kbit/s at that message's real DBC-declared rate. The recomputed figure still sits comfortably under the 120 kbit/s pass bar (`00-THRESHOLD.md`) with over 38 kbit/s of margin, and confirms the per-record length prefix's cost is a real but small tax — not a threat to Phase 0's no-go-subset viability.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The whole Phase 1 spine is proven end to end on one frame with production code at every layer. `01-05` through `01-13` are cleared to build outward: `01-05` (session lifecycle expansion, monotonic-counter fallback), `01-06` (MCAP writer hardening + crash recovery), `01-07` (fan-out expansion to sustained-rate soak), `01-08` (framing suite + `UdpLink`), `01-09` (hardware capture source), `01-10` (logger CLI), `01-11` (ground CLI), `01-12` (replay source), `01-13` (soak test).
- `archive/reader.py` (crash-recovery `NonSeekingReader(..., log_time_order=False)` wrapper) is intentionally NOT built in this plan — it is `01-05`/`01-06` scope per the phase's own module ownership split (`01-PATTERNS.md`'s "No Analog Found" table names it separately from `writer.py`/`session.py`).
- No blockers. The only untested-here surface is the Linux-only halves of `ArchiveWriter`'s fsync cadence (`os.fdatasync`) and `session.mark_done`'s directory fsync — both are platform-guarded so their ordering logic is exercised on the Windows dev box, but the actual syscalls only run on the CM4/Linux CI, per `01-RESEARCH.md` Pitfall 5. This is a recorded, known scope limit, not a defect.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*

## Self-Check: PASSED

All 16 created source files, the modified test file, and this SUMMARY.md were verified present on disk. Commit `ee052bd` (Task 1: the tracer) was verified present in `git log --oneline --all`. `python -m pytest tests/test_end_to_end.py -x -q --tb=short` and `python -m pytest -q -m "not slow"` were both re-confirmed green (157 passed, 10 Wave-0 placeholder skips, 0 failures) before this summary was written.
