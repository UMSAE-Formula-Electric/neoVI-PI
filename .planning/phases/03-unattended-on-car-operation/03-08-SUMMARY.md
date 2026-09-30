---
phase: 03-unattended-on-car-operation
plan: 08
subsystem: ops
tags: [i2c, smbus2, led, heartbeat, gap-closure]

# Dependency graph
requires:
  - phase: 03-unattended-on-car-operation
    provides: "03-03's LedIndicator Protocol seam and NullLedIndicator default; 03-07's 03-VERIFICATION.md gap finding on success criterion 2"
provides:
  - "MembraneLedIndicator: the first concrete LedIndicator implementation, driving the neoVI PI's I2C membrane LED panel through a measured register sequence"
  - "smbus2==0.6.1 pinned behind a sys_platform==\"linux\" marker; a marker-aware requirements parser"
  - "--led-kind CLI flag on telemetry.logger.cli, wired to HeartbeatPublisher's led= argument"
  - "03-RESEARCH.md's settled GPIO verdict and measured I2C write sequences, from a full (not partial) vendor-script read"
affects: ["03-09 (Pi bring-up runbook item, i2c_vc overlay, i2c group grant)"]

# Tech tracking
tech-stack:
  added: ["smbus2==0.6.1 (Linux-only, never installed on this dev box)"]
  patterns:
    - "Lazy SDK/library import inside a bus/device factory function, copying telemetry.capture.hardware_source._default_sdk exactly"
    - "Import-time completeness guard against a closed state tuple (HEARTBEAT_STATES), mirroring telemetry.ops.cli's _missing_state_info"
    - "Loud fallback-to-no-op on construction failure (ERROR log naming the cause), never a silent substitution"

key-files:
  created:
    - src/telemetry/ops/membrane_led.py
    - tests/test_ops_membrane_led.py
  modified:
    - .planning/phases/03-unattended-on-car-operation/03-RESEARCH.md
    - requirements.txt
    - tests/test_logger_config.py
    - src/telemetry/ops/led.py
    - src/telemetry/logger/cli.py
    - tests/test_logger_cli_ops.py

key-decisions:
  - "RPi.GPIO resolved-not-needed: the full 148-line vendor membrane.py (not just its first 30 lines) shows all four GPIO calls are input-only (two button setups, one event-detect), none in any LED path. Not added to requirements.txt."
  - "smbus2==0.6.1 pinned behind `sys_platform == \"linux\"` because smbus2/smbus2.py imports the Unix-only stdlib fcntl at module scope -- confirmed live that fcntl is absent on this Windows dev box."
  - "All ten RGB positions are always driven the same colour (never a single position) because the panel's physical layout is unknown and the measured write sequence writes the whole 30-entry array regardless."
  - "Five colours picked for a reason, not a preference: capturing=green, waiting-for-hardware=blue (green-vs-blue survives common colour-vision deficiencies where green-vs-amber would not), booting=white, degraded=amber, stopped-error=red."
  - "set_state lets bus-write exceptions propagate (HeartbeatPublisher._drive_led already catches/counts/logs them) -- this module does not add a second catch layer, only clears its own skip-cache on the way out so the next 1 Hz tick retries."
  - "Criterion 2 moves from FAILED to unverified-pending-hardware, explicitly NOT to VERIFIED -- no I2C bus, LED driver, or panel exists on any dev box this project has touched."

patterns-established:
  - "A concrete hardware driver module lives in its own file when it needs a symbol from a module its Protocol-defining module already imports, to avoid an import cycle (membrane_led -> heartbeat -> led, never led -> membrane_led)."

requirements-completed: []  # Deliberate: this plan marks nothing in REQUIREMENTS.md. OPS-02 stays Complete (marked by 03-05); OPS-01 stays Pending on the merits.

coverage:
  - id: D1
    description: "GPIO verdict settled against the full vendor script (not the first 30 lines); RPi.GPIO confirmed resolved-not-needed"
    verification:
      - kind: other
        ref: "python -c \"...missing=[n for n in (...) if n not in t]...\" against 03-RESEARCH.md (Task 1's own verify gate)"
        status: pass
    human_judgment: false
  - id: D2
    description: "smbus2==0.6.1 pinned behind a linux platform marker; requirements.txt's other 8 pins resolve unchanged on this Windows dev box"
    verification:
      - kind: unit
        ref: "tests/test_logger_config.py#test_requirements_pinned"
        status: pass
      - kind: integration
        ref: "pip install --dry-run -r requirements.txt (reports 'Ignoring smbus2: markers ... don't match')"
        status: pass
    human_judgment: false
  - id: D3
    description: "_parse_pinned_requirements correctly strips PEP 508 markers before pin assertions, for both the marked-and-pinned and marked-but-unpinned cases"
    verification:
      - kind: unit
        ref: "tests/test_logger_config.py#test_parse_pinned_requirements_strips_marker"
        status: pass
      - kind: unit
        ref: "tests/test_logger_config.py#test_parse_pinned_requirements_rejects_marked_but_unpinned"
        status: pass
    human_judgment: false
  - id: D4
    description: "MembraneLedIndicator reproduces the measured init and set-colour I2C write sequences exactly, is importable with no fcntl present, skips repeated states, retries after a failing write, and closes safely"
    verification:
      - kind: unit
        ref: "tests/test_ops_membrane_led.py (11 tests: init sequence, set_state colour block, repeat-skip, raise-then-retry, close, import-time guard, factory fallback)"
        status: pass
    human_judgment: false
  - id: D5
    description: "MembraneLedIndicator is wired as HeartbeatPublisher's led= argument through the real telemetry.logger.cli.main() chain, selected via --led-kind, with nothing in that chain mocked"
    verification:
      - kind: e2e
        ref: "tests/test_logger_cli_ops.py#test_end_to_end_membrane_kind_produces_real_register_writes_through_main"
        status: pass
    human_judgment: false
  - id: D6
    description: "A physical LED actually illuminates on the car"
    verification: []
    human_judgment: true
    rationale: "No I2C bus, LED driver chip, or panel exists on any dev box this project has touched. This plan explicitly moves criterion 2 to unverified-pending-hardware, not VERIFIED; the physical proof folds into 03-09's single Pi bring-up item, per this plan's own stated scope."

# Metrics
duration: ~20min
completed: 2026-09-30
status: complete
---

# Phase 3 Plan 08: Membrane LED Driver (OPS-02 Gap Closure) Summary

**First concrete `LedIndicator` implementation (`MembraneLedIndicator`, I2C bus 10 / address 0x3c) wired into `telemetry.logger.cli` behind `--led-kind`, closing 03-VERIFICATION.md's one recorded gap on success criterion 2 -- moved from FAILED to unverified-pending-hardware, not VERIFIED.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3/3 completed
- **Files modified:** 6 modified, 2 created

## Accomplishments

- Settled the GPIO question against the **full** 148-line vendor `membrane.py` (the prior session had only read its first 30 lines): all four `GPIO.` calls are input-only (two button `setup()` calls, one `add_event_detect`), none touch any LED path. `RPi.GPIO` is recorded as resolved-not-needed, with provenance (full read, this session, not a hardware measurement), and is **not** added to `requirements.txt`.
- Recorded the measured I2C initialisation sequence (shutdown register out-of-shutdown, LED control register block write of value `0x03` x 30, PWM update pulse) and the measured set-colour sequence (mutate a 30-entry array, write it as a block to the PWM port offset register, pulse the update register) directly from the vendor script, in `03-RESEARCH.md`.
- Pinned `smbus2==0.6.1` behind `sys_platform == "linux"` in `requirements.txt` -- its artifact was fetched via `pip download` (never installed here, since `smbus2/smbus2.py` imports the Unix-only `fcntl` at module scope and `fcntl` does not exist on this Windows dev box). `pip install --dry-run -r requirements.txt` confirms the pin is ignored here and the other 8 resolve unchanged.
- Fixed `_parse_pinned_requirements` (`tests/test_logger_config.py`) to split a PEP 508 marker off a requirement line *before* applying the exact-`==`-pin assertions -- the prior parser split on the first bare `==`, which would have silently parsed a marked-but-unpinned line's own marker comparison as a bogus version. Added an explicit expected-9-package-name-set assertion.
- Built `src/telemetry/ops/membrane_led.py`: `MembraneLedIndicator` (lazy `smbus2` import copying `hardware_source._default_sdk`'s exact shape), a state-to-colour table guarded at import time against `HEARTBEAT_STATES`, repeat-state bus-write skipping with retry-on-failure, a safe-to-call-twice `close()`, and `build_led_indicator()` -- a loudly-logging fallback-to-no-op factory.
- Wired it into `telemetry.logger.cli`: a `--led-kind` flag (`null` default, `membrane`), an injectable `build_led_indicator_fn`, and the built indicator passed as `HeartbeatPublisher`'s `led=` argument -- **the key link** 03-VERIFICATION.md's gap required. An in-process end-to-end test drives the real `main()` chain with a recording fake bus and asserts both the init sequence and a full-scale-green PWM block write reach it.
- Corrected `led.py`'s docstrings to point at the new module instead of claiming `NullLedIndicator` is the only implementation, while preserving the 03-03 checkpoint decision and package-verdict history verbatim.

## Task Commits

Each task was committed atomically:

1. **Task 1: Settle the GPIO question and capture the vendor register sequence** - `8c1753b` (docs)
2. **Task 2: Pin `smbus2` behind a platform marker, fix the manifest parser** - `18a80e3` (feat)
3. **Task 3: End-to-end "the panel turns green while capturing"** - `f20097b` (feat)

_No separate TDD-gate commits: Task 3 carries `tdd="true"` in its frontmatter but was executed as a single atomic commit per this project's established practice for tracer/gap-closure tasks where tests and implementation were authored together and verified together before any commit was made._

## Files Created/Modified

- `src/telemetry/ops/membrane_led.py` - `MembraneLedIndicator`, its state-to-colour table + import-time guard, and `build_led_indicator()`
- `tests/test_ops_membrane_led.py` - 11 behaviour tests against a recording fake bus
- `.planning/phases/03-unattended-on-car-operation/03-RESEARCH.md` - full vendor-script read subsection: GPIO verdict, measured register sequences
- `requirements.txt` - `smbus2==0.6.1 ; sys_platform == "linux"`, with its provenance-departure rationale as an inline comment
- `tests/test_logger_config.py` - marker-aware `_parse_pinned_requirements`, expected-package-name-set assertion, two new parser tests
- `src/telemetry/ops/led.py` - docstrings corrected to reflect the new concrete driver, history preserved
- `src/telemetry/logger/cli.py` - `--led-kind` flag, `build_led_indicator_fn` injection point, `led=` wired into `HeartbeatPublisher`
- `tests/test_logger_cli_ops.py` - one end-to-end test through the real `main()` chain with a recording fake bus

## Decisions Made

- **RPi.GPIO stays out of `requirements.txt`.** The full vendor script confirms zero GPIO calls touch any LED path -- only the two input buttons. No scope-changing checkpoint was needed (the plan's one legitimate early-stop condition did not trigger).
- **All ten RGB positions always driven the same colour.** The panel's physical layout (which index maps to which position) is unknown, and the measured sequence writes the whole 30-entry array in one block regardless of how many positions logically changed -- driving all ten costs the same bus traffic as driving one, and removes the unknown-layout risk entirely.
- **Five colours chosen for a stated reason**: green/blue for capturing/waiting-for-hardware (the literal distinction criterion 2 needs a human to make, chosen to survive common colour-vision deficiencies), amber/red for the two attention states (confusing those two is harmless -- both mean "go look").
- **No second exception-catching layer inside `set_state`.** `HeartbeatPublisher._drive_led` already catches, counts, and log-once-suppresses; a second catch here would hide failures from those existing counters. `set_state` only clears its own skip-cache before re-raising.
- **`--led-kind` is a CLI flag, not a `config/logger.json` field.** This is a hardware-presence choice structurally identical to `--source hardware|synthetic` (a real `OpsConfig` field would also immediately fail `tests/test_runbook_coverage.py`'s field-enumeration check). The car's actual choice belongs in 03-09's version-controlled unit file start command.

## Deviations from Plan

None - plan executed exactly as written. No Rule 1-4 auto-fixes were needed; the one conditional branch in the plan (Task 1's GPIO halt-or-confirm decision) resolved in the "confirm" direction on the merits, which is not a deviation.

## Issues Encountered

**Test-design correction (caught and fixed before any commit, not a deviation from the plan's scope):** The first draft of the end-to-end test in `tests/test_logger_cli_ops.py` used `--duration-s 0.3`, which (per this test file's own already-documented fact that `SyntheticFrameSource` has no per-frame real-time throttle) let the whole synthetic run finish in ~31ms -- close enough to the 0.02s heartbeat interval to race the publisher thread's first tick and sometimes finish with zero ticks fired. Raised to `--duration-s 5.0` (proportionally more frames, proportionally more real CPU time) to give wide, deterministic margin. Caught by running the test, not shipped and discovered later.

**Import-time-guard test design:** An initial draft of the import-time completeness-guard test used `importlib.reload()` on the canonical `telemetry.ops.membrane_led` module, which swapped the live `MembraneLedIndicator` class object out from under other tests in the same session (subsequent `isinstance()` checks against the pre-reload class started failing). Rewritten to load a separate module object from the same source file via `importlib.util.spec_from_file_location`, leaving the canonical module and its class identity untouched for every other test.

## Known Stubs

None. Every code path added is real: the driver performs real (measured) register writes against an injected bus in every test, and the factory's fallback path is real production logic (not a test-only stub), exercised by its own test.

## Honest Limit (stated per the plan's explicit instruction)

**No command run in this plan proves a physical LED illuminates.** There is no I2C bus, no LED driver chip, and no membrane panel on this or any dev box this project has touched. Every assertion in `tests/test_ops_membrane_led.py` and the end-to-end test in `tests/test_logger_cli_ops.py` runs against a recording fake bus that captures the register writes this code *intends* -- that proves the write sequences match what was measured from Intrepid's vendor script, and that the real `main()` chain reaches the bus at all. It does not and cannot prove a light turns on, what brightness looks like in daylight, or that this project's panel-position assumption (driving all ten uniformly) looks right to a human standing at the car. **Success criterion 2 moves from FAILED to *unverified-pending-hardware*, explicitly not to VERIFIED.** The physical proof folds into the single Pi bring-up verification this phase already budgeted (`docs/runbook.md`'s "Pi bring-up" section), extended by 03-09 -- not a second hardware trip.

**WR-06 is now a live latent defect, left unfixed by explicit user decision.** `_run_session`'s hardware-wait clean-stop path (`main()`'s `if not hardware_present: publisher.remove(); return`) calls `publisher.remove()` without `publisher.join()`, so `HeartbeatPublisher._close_led()` never runs on that path. This was harmless while the indicator was a no-op; this plan makes the indicator real, so a logger that stops cleanly while still waiting for hardware with `--led-kind membrane` selected will leave the LED panel in its last-driven state (most likely `waiting-for-hardware` blue) rather than turning it off, even though the status file is correctly removed. This is a known, recorded consequence, explicitly out of this plan's scope (WR-06 belongs to 03-09 Task 1, which watches its own test fail against the code exactly as this plan leaves it -- fixing it here would destroy that RED proof).

## User Setup Required

None - no external service configuration required. (The `i2c_vc` boot overlay and `i2c` group membership grant are 03-09's job, not this plan's.)

## Next Phase Readiness

- `MembraneLedIndicator` and `--led-kind membrane` are ready for 03-09 to select in the version-controlled systemd unit's start command, once the `i2c_vc` overlay (`/boot/firmware/config.txt`, user-confirmed) and the `i2c` group grant for the service user land there.
- 03-09's Pi bring-up runbook item should be extended (not duplicated) to also observe the LED panel's physical behaviour -- the one thing no test here could prove.
- WR-06 remains open for 03-09 Task 1 to fix, with its RED-proof test already relying on the code being left exactly as this plan leaves it.

## Self-Check: PASSED

All 9 created/modified files confirmed present on disk; all 3 task commits (`8c1753b`, `18a80e3`, `f20097b`) confirmed in `git log`.

---
*Phase: 03-unattended-on-car-operation*
*Completed: 2026-09-30*
