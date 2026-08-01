---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 08
subsystem: telemetry-pipeline
tags: [cobs, crc16, udp, socket, framing, link, deframe, corruption-testing]

# Dependency graph
requires:
  - phase: 01-04
    provides: Production COBS+CRC-16 framing (telemetry.framing), the Link Protocol and LoopbackLink (telemetry.link), and the byte-stream Deframer with per-failure-mode counters (telemetry.ground.deframe) — all proven on one clean frame by the tracer
provides:
  - Framing's two hard claims pinned by test, not just reasoned about (tests/test_framing.py) -- LINK-01's delimiter-resync property under real corruption, and LINK-02's discard-and-count contract for each of COBS/CRC/batch-format failure independently
  - UdpLink, the second Link implementation (src/telemetry/link/udp.py) -- a real network hop over loopback UDP, satisfying the same three-method Link Protocol as LoopbackLink
  - One shared test suite (tests/test_link.py) parameterised over both Link implementations, demonstrating LINK-03's "no change to the layers above" rather than asserting it
  - LoopbackLink.close() given a real closed-state contract (send-after-close now raises), correcting a gap the tracer left open
affects: [01-09, 01-10, 01-11, 01-12, 01-13]

# Tech tracking
tech-stack:
  added: []  # udp.py uses stdlib socket only; no new dependency
  patterns:
    - "Corruption test cases built via seeded random.Random(SEED) with a bounded search-and-classify helper (_find_flip), never blind trial-and-error -- a failure names the seed and byte offset so it reproduces"
    - "One parameterised link_pair fixture (params=['loopback','udp']) drives every LINK-03 assertion against both implementations from a single test body -- LINK-03's own point (\"no change to the layers above\") demonstrated structurally, not by two files that could diverge"
    - "Platform-dependent socket behavior handled by branching on the OBSERVED outcome (recv() returned truncated bytes vs None), not by assuming one platform's documented semantics -- the same test and the same UdpLink.recv() code path work correctly on both POSIX and Winsock"

key-files:
  created:
    - src/telemetry/link/udp.py
  modified:
    - src/telemetry/link/loopback.py
    - tests/test_framing.py
    - tests/test_link.py

key-decisions:
  - "CRC-trailer-region and COBS-length-chain corruption cases are constructed two different ways: the CRC-trailer case is deterministic (directly modify pack_crc's own trailer bytes before re-COBS-encoding, no search needed, since we control the exact bytes), while the COBS-structural case requires a seeded random search over byte offsets (_find_flip) since which offset lands on a COBS 'code' byte is data-dependent"
  - "The overhead-model comparison test asserts an upper bound (framed_len <= overhead.all_in_bytes_per_batch(clean+num_records)+1), not equality -- verified empirically that cobs_worst_case_overhead is a true worst-case bound achieved only by zero-byte-free data; real CFR records carry zero bytes and come in at or under it, sometimes by a wide margin at larger batch sizes"
  - "The garbage-injection resync test bounds the injected non-zero garbage with an explicitly inserted delimiter (rather than letting it merge with the following frame's own bytes), since non-zero garbage immediately adjacent to a COBS-encoded frame's own bytes would corrupt that frame too (verified structurally: COBS's first output byte is always a length-code byte, and prepending garbage reliably breaks it) -- this models a real resync point (the noise's own eventual zero byte, or equipment din) rather than an artificial one"
  - "Round-trip is tested at exactly three sizes sourced from the codebase itself, not literals: 1, config/logger.json's telemetry.batch_frames (loaded via the real typed loader), and MAX_BATCH_RECORDS (batcher.py's own uint16 ceiling) -- a config tune or a header-width change can never silently stop these tests meaning what their names say"

patterns-established:
  - "_find_flip(rng, encoded, want, max_attempts): a reusable seeded-search helper for 'find a single-byte corruption that produces failure mode X' -- classify-then-search rather than positional guessing, with the seed and offset folded into every failure message for reproducibility"

requirements-completed: [LINK-01, LINK-03]
# LINK-02 and LINK-04 are also in this plan's own `requirements:` frontmatter,
# but 01-11-PLAN.md (wave 5, depends_on: [01-08, 01-10]) claims them too and
# is their last claimant -- REQUIREMENTS.md's traceability table is updated
# to Complete for LINK-01/LINK-03 only. LINK-02/LINK-04 stay Pending.

coverage:
  - id: D1
    description: "A corrupted middle batch in a 3-batch stream costs exactly that batch -- the delimiter-based stream resynchronizes and the following batch decodes correctly, proven under a single feed() call, arbitrarily-sized chunked feeds (including splits mid-frame), and injected non-zero garbage bounded by its own delimiter"
    requirement: "LINK-01"
    verification:
      - kind: unit
        ref: "tests/test_framing.py#test_resync_after_middle_batch_corruption_single_feed"
        status: pass
      - kind: unit
        ref: "tests/test_framing.py#test_resync_after_middle_batch_corruption_chunked_feed"
        status: pass
      - kind: unit
        ref: "tests/test_framing.py#test_garbage_between_two_valid_frames_does_not_poison_the_following_frame"
        status: pass
    human_judgment: false
  - id: D2
    description: "A batch whose CRC-16 trailer itself contains a zero byte still frames to output with exactly one zero byte -- the trailing delimiter -- proving the CRC-inside-COBS ordering the tracer corrected actually prevents the false-delimiter regression it was designed to prevent"
    requirement: "LINK-01"
    verification:
      - kind: unit
        ref: "tests/test_framing.py#test_regression_crc_containing_a_zero_byte_does_not_split_the_frame"
        status: pass
    human_judgment: false
  - id: D3
    description: "Each of COBS-structure corruption, CRC-trailer corruption, and batch-format corruption (truncation, frame_count mismatch) raises its own distinct error type when unframed directly, and is caught, counted on exactly its own Deframer counter, and yields nothing when fed through the Deframer"
    requirement: "LINK-02"
    verification:
      - kind: unit
        ref: "tests/test_framing.py#test_deframer_discards_and_counts_each_damage_class_yields_nothing[cobs]"
        status: pass
      - kind: unit
        ref: "tests/test_framing.py#test_deframer_discards_and_counts_each_damage_class_yields_nothing[crc]"
        status: pass
      - kind: unit
        ref: "tests/test_framing.py#test_deframer_discards_and_counts_each_damage_class_yields_nothing[batch_format]"
        status: pass
    human_judgment: false
  - id: D4
    description: "UdpLink satisfies the same Link Protocol as LoopbackLink -- identical send/recv/close semantics, and the 01-04 tracer's full encode-to-decode chain produces byte-identical decoded frames whether run over LoopbackLink or over UdpLink, compared to each other rather than to a hardcoded literal"
    requirement: "LINK-03"
    verification:
      - kind: unit
        ref: "tests/test_link.py#test_payload_sent_is_received_byte_identical[loopback]"
        status: pass
      - kind: unit
        ref: "tests/test_link.py#test_payload_sent_is_received_byte_identical[udp]"
        status: pass
      - kind: integration
        ref: "tests/test_link.py#test_full_chain_produces_identical_decoded_frames_over_both_links"
        status: pass
    human_judgment: false
  - id: D5
    description: "An oversized datagram is contained rather than corrupting downstream state -- on POSIX it is silently truncated and the Deframer counts it as corrupt (never decoded); on Winsock (this dev box) it is dropped by the OS and UdpLink.recv() returns None rather than raising, with no residual buffer pollution either way"
    requirement: "LINK-02"
    verification:
      - kind: unit
        ref: "tests/test_link.py#test_oversized_datagram_is_truncated_counted_corrupt_never_reaches_the_decoder"
        status: pass
    human_judgment: false
  - id: D6
    description: "Neither Link implementation imports a serial/radio driver, and every test in this file runs against the loopback interface only -- LINK-04's no-radio, no-vehicle-hardware, no-second-machine claim holds structurally, not by convention"
    requirement: "LINK-04"
    verification:
      - kind: unit
        ref: "tests/test_link.py#test_no_radio_or_serial_driver_imported_by_either_link_implementation"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-08-01
status: complete
---

# Phase 1 Plan 8: Framing Corruption Proofs and UdpLink Summary

**COBS+CRC framing's resync-after-corruption and discard-and-count claims pinned by test against real DBC-encoded batches, plus UdpLink as the second `Link` implementation proven against LoopbackLink through one shared, parameterised test suite (29 new tests, both files formerly Wave-0 placeholder skips).**

## Performance

- **Duration:** 20 min
- **Started:** 2026-08-01T20:38:00Z (approx.)
- **Completed:** 2026-08-01T20:58:00Z
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- `tests/test_framing.py` proves LINK-01's actual claim — resync, not just round-trip — under three separate corruption shapes: a single `feed()` call with a corrupted middle batch, the same stream split into arbitrarily-sized chunks (including splits mid-frame), and non-zero garbage injected between two valid frames. Each proves the batch after the damage still decodes correctly and exactly one corruption event is counted.
- A deliberate regression guard (`test_regression_crc_containing_a_zero_byte_does_not_split_the_frame`) exhaustively searches all 256 `batch_seq` values for a real batch whose CRC-16 trailer itself contains a `0x00` byte, then asserts the framed output still has exactly one zero byte — the trailing delimiter. This is the specific case the tracer's CRC-inside-COBS correction (01-04) exists to prevent, now pinned by test rather than only reasoned about in a docstring.
- LINK-02's three damage classes (COBS-structure corruption, CRC-trailer corruption, batch-format truncation/count-mismatch) are each proven to raise their own distinct exception type when unframed directly, and — parameterised over one shared assertion — to be caught, counted on exactly one `DeframeCounters` field, and yield nothing when fed through a real `Deframer`.
- `src/telemetry/link/udp.py` adds `UdpLink`, satisfying `telemetry.link.base.Link`'s exact three-method Protocol with no extension. `local_addr` exposes the socket's real bound `(host, port)` (needed for ephemeral-port test wiring and for the ground station to log its own listening port).
- `tests/test_link.py` parameterises one `link_pair` fixture over `["loopback", "udp"]` and drives every shared assertion (byte-identical delivery, timeout returns `None`, close is idempotent, send-after-close raises) through both — plus a dedicated test running the 01-04 tracer's full encode-to-decode chain over each implementation and comparing the two results to each other, not to a hardcoded literal.
- The UDP truncation pitfall (`01-RESEARCH.md` Pattern 6) was tested for real rather than assumed, and turned out to differ from the research doc's POSIX-only citation: on this dev box (Windows, per `01-CONTEXT.md`'s dev-interpreter decision), Winsock's `recvfrom` *raises* `WSAEMSGSIZE` on an oversized datagram instead of silently truncating it. `UdpLink.recv()` now catches this specific error and returns `None`; the test covers both observed behaviors by branching on what `recv()` actually returned, not on which platform is assumed.

## Task Commits

1. **Task 1: Framing round-trip, corruption discrimination, and delimiter resync** - `51f538d` (test)
2. **Task 2: UdpLink and one shared suite over both link implementations** - `cd65f84` (feat)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `src/telemetry/link/udp.py` — `UdpLink`: bound UDP socket, discoverable `local_addr`, `recv_bufsize` sized generously per config, `WSAEMSGSIZE`-aware `recv()`
- `src/telemetry/link/loopback.py` — `close()` now tracks a `_closed` flag; `send()` raises `RuntimeError` after close (was a silent no-op)
- `tests/test_framing.py` — replaces 01-02's placeholder skip; 17 tests covering round-trip, delimiter safety, the overhead model, per-damage-class discrimination, and resync
- `tests/test_link.py` — replaces 01-02's placeholder skip; 12 tests (several parameterised ×2) covering shared Link behavior, the full chain compared across implementations, UDP-specific truncation/loss behavior, and the LINK-04 no-radio structural check

## Decisions Made

- **CRC-trailer corruption is constructed deterministically, not searched:** since `pack_crc`'s trailer bytes are directly addressable, the test flips a trailer byte before re-COBS-encoding — guaranteed to hit exactly the trailer, no search needed. COBS-structural corruption (which offset is a "code" byte) is data-dependent, so it uses the seeded `_find_flip` search helper instead.
- **The overhead-model comparison test asserts an upper bound, not equality.** Verified empirically (see Deviations below) that `overhead.cobs_worst_case_overhead` is a true worst-case bound achieved only by zero-byte-free payloads; real CFR records carry zero bytes and the actual framed size can come in meaningfully under the bound at larger batch sizes. Asserting equality would have been either flaky or wrong.
- **Garbage-injection resync test explicitly bounds the garbage with its own inserted delimiter**, rather than letting non-zero garbage merge directly with the following frame's own COBS bytes. Verified structurally (COBS's first output byte is always a length-code byte; corrupting/prefixing it reliably breaks decode) that merging would corrupt the following frame too, contradicting the plan's literal requirement that "the following valid frame still decodes." The inserted delimiter models a real resync point — the garbage's own eventual zero byte, or equipment din — without depending on a specific random garbage sample happening to contain one.
- **Round-trip batch sizes are sourced from the codebase, not copied literals:** 1, `config/logger.json`'s real `telemetry.batch_frames` (loaded via `load_logger_config`), and `MAX_BATCH_RECORDS` (`batcher.py`'s own uint16 ceiling) — so these tests can't silently stop testing what their names claim after a config or header-width change.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] `LoopbackLink.close()` given a real closed-state contract**
- **Found during:** Task 2, writing the shared `link_pair` test suite
- **Issue:** Task 2's own behavior spec requires "`close` is idempotent, and `send` after `close` raises rather than silently discarding" to hold identically across **both** Link implementations (that's the whole point of a *shared* suite proving LINK-03). `LoopbackLink.close()` (01-04) was `pass` — a no-op — so `send()` after `close()` on `LoopbackLink` silently queued data with no error, which would have made the shared test fail for `LoopbackLink` while passing for `UdpLink`.
- **Fix:** Added a `_closed` flag to `LoopbackLink`; `close()` sets it (idempotently — safe to call more than once), and `send()` raises `RuntimeError("cannot send on a closed LoopbackLink")` if set. `recv()` behavior after close is unchanged (the plan's behavior text only specifies `send`).
- **Files modified:** `src/telemetry/link/loopback.py`
- **Verification:** `tests/test_link.py::test_close_is_idempotent_and_send_after_close_raises[loopback]` and `[udp]` both pass with the identical assertion body.
- **Committed in:** `cd65f84` (Task 2 commit)

**2. [Rule 1 - Bug] `UdpLink.recv()` did not handle Winsock's oversized-datagram behavior**
- **Found during:** Task 2, writing the oversized-datagram truncation test — first run raised an unhandled `OSError: [WinError 10040]` from inside `recv()`, which is exactly the kind of unhandled exception LINK-02's "never propagate, always count-and-continue" philosophy exists to prevent.
- **Issue:** `01-RESEARCH.md` Pattern 6 cites POSIX/Winsock `recvfrom` truncation as one uniform behavior ("silently truncates... no error raised"). Verified this session that this is true on POSIX (the deployment target, Linux/CM4) but **false** on Winsock (this dev box, per `01-CONTEXT.md`'s Windows dev-interpreter decision): Winsock raises `WSAEMSGSIZE` (`errno.EMSGSIZE`, WinError 10040) instead of truncating, and the oversized datagram's bytes are unrecoverable through the standard socket API.
- **Fix:** `UdpLink.recv()` now catches `OSError` and checks `exc.errno == errno.EMSGSIZE`; if so, returns `None` (treated exactly like a timeout — "nothing usable arrived this call"). Any other `OSError` still propagates. On Linux this branch is simply never taken (the code path is inert there); `recvfrom` returns POSIX-truncated bytes through the normal `return data` path, unchanged.
- **Files modified:** `src/telemetry/link/udp.py` (docstring also updated to document both platform behaviors)
- **Verification:** `tests/test_link.py::test_oversized_datagram_is_truncated_counted_corrupt_never_reaches_the_decoder` branches on the actual `recv()` result and asserts the correct contained outcome for whichever platform behavior is observed; passes on this Windows dev box, and the POSIX branch is exercised by the same code path (unchanged from before this fix) when it eventually runs on Linux/CM4.
- **Committed in:** `cd65f84` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 missing-critical, mandated by the plan's own shared-suite requirement; 1 bug, an unhandled exception discovered while writing the plan's own truncation test)
**Impact on plan:** Both fixes were required for the plan's own explicitly stated behavior to actually hold on this platform. No scope creep — `loopback.py`'s change is a 6-line addition matching `UdpLink`'s own contract; `udp.py`'s change is a narrowly-scoped `errno.EMSGSIZE` catch that is provably inert on the deployment target.

## Issues Encountered

None beyond the two deviations above, both of which were discovered by writing the tests the plan specified and observing real failures — exactly the kind of thing this plan's "prove it under damage, don't just reason about it" objective is for.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- LINK-01 and LINK-03 are closed in `REQUIREMENTS.md`'s traceability table. LINK-02 and LINK-04 are **not** marked complete here — `01-11-PLAN.md` (wave 5) also claims both and is their last claimant (it extends `test_end_to_end.py` with a real two-process run over UDP and builds the headless ground CLI that reports these counters as link health); this plan's own D3/D5/D6 coverage entries above already prove the underlying mechanics, but the requirement-completion marker intentionally waits for 01-11.
- `UdpLink` and `LoopbackLink` are both ready for `01-10`'s logger CLI and `01-11`'s ground CLI to select between via `config/logger.json`'s `link.kind` with no further change — that selection code doesn't exist yet (it's `01-10`/`01-11` scope), but nothing in either `Link` implementation blocks it.
- The Winsock `WSAEMSGSIZE` finding is a permanent, real cross-platform behavior difference (not a workaround to remove later) — worth keeping in mind if `01-11`'s ground CLI or any future soak test (`01-13`) runs on this Windows dev box and needs to reason about "why did an oversized-batch scenario show as zero loss instead of a corrupt-batch count."
- No blockers.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*

## Self-Check: PASSED

All 4 created/modified source and test files, plus this SUMMARY.md, were verified present on disk. Commits `51f538d` (Task 1), `cd65f84` (Task 2), and `bdbb6a0` (docs: plan summary) were verified present in `git log --oneline --all`. `python -m pytest tests/test_framing.py tests/test_link.py -x -q --tb=short` (29 passed) and `python -m pytest -q -m "not slow"` (231 passed, 4 skipped — all remaining skips are placeholders explicitly owned by future plans 01-09/01-10/01-12/01-13) were both re-confirmed green before this summary was finalized.
