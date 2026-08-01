---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 03
subsystem: config
tags: [config, fail-closed, ops-05, ops-06, allowlist]

# Dependency graph
requires:
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link (01-01)
    provides: "Human-cleared package legitimacy verdict for mcap, cobs, crccheck, python-ics"
provides:
  - "config/logger.json — the single checked-in runtime config for channels, DBC path, capture/archive/telemetry/link settings, and the critical-channel allowlist"
  - "src/telemetry/logger/config.py — LoggerConfig, LoggerConfigError, load_logger_config, resolve_allowlist"
  - "tests/conftest.py session-scoped logger_config fixture"
  - "test_requirements_pinned manifest cross-check (OPS-06)"
affects: ["01-04", "01-05", "01-06", "01-07", "01-08", "01-09", "01-10"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Config idiom: typed frozen-dataclass config, named *ConfigError exception, default_path() classmethod, fail-closed on unknown/missing keys, tested by mutating a copy of the real checked-in file — now used identically by both config/gate.json and config/logger.json"
    - "Allowlist resolution kept out of the loader as a separate free function (resolve_allowlist) so config parsing stays importable without cantools/ics"
    - "Derived constants imported from their owning module (MAX_DELTA_T_US from wire/encoder.py) rather than restated as literals"

key-files:
  created:
    - config/logger.json
    - src/telemetry/logger/__init__.py
    - src/telemetry/logger/config.py
    - tests/test_logger_config.py
  modified:
    - tests/conftest.py

key-decisions:
  - "config/logger.json lives at the repository root, not beside .planning/phases/00-.../config/gate.json — runtime config vs. phase-artifact modelling assumptions, per 01-CONTEXT.md"
  - "netid format validation (NETID_ prefix) happens in the loader without importing ics; actual resolution against real ics attributes is a test-only check (skips cleanly on a machine without ics)"
  - "archive.root_dir is resolved to an absolute path but existence is NOT checked at load — the session layer (01-05) creates it"
  - "telemetry.batch_frames' 65535 ceiling is a bare literal (no owning module exists yet to import from, unlike batch_max_age_s/MAX_DELTA_T_US) — the batch header this refers to is built in a later plan"
  - "bus labels for the two shipped channels are 'bus1'/'bus2', matching config/gate.json's bus_assignment naming from Phase 0"

patterns-established:
  - "Second use of the Phase 0 config idiom (typed loader + named *ConfigError + config_hash + default_path()) confirms it as the project's one config idiom, not a one-off"

requirements-completed: [OPS-05, OPS-06, OPS-04]

coverage:
  - id: D1
    description: "config/logger.json declares channels, DBC path, capture/archive/telemetry/link settings, and the 12-message critical-channel allowlist in one checked-in file"
    requirement: "OPS-05"
    verification:
      - kind: unit
        ref: "tests/test_logger_config.py#test_default_config_loads_clean"
        status: pass
      - kind: unit
        ref: "tests/test_logger_config.py#test_resolve_allowlist_returns_twelve_pairs_all_present_in_dbc"
        status: pass
    human_judgment: false
  - id: D2
    description: "Unknown or missing config keys raise LoggerConfigError naming the offending key at every level (top-level and each block)"
    requirement: "OPS-05"
    verification:
      - kind: unit
        ref: "tests/test_logger_config.py#test_unknown_top_level_key_raises"
        status: pass
      - kind: unit
        ref: "tests/test_logger_config.py#test_missing_required_top_level_key_raises"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every fail-closed validation branch (schema_version, dbc_path existence, empty/duplicate channels, malformed netid, non-positive queue/flush values, batch_frames uint16 ceiling, batch_max_age_s CFR ceiling, empty/duplicate allowlist, invalid link.kind, out-of-range udp port) raises LoggerConfigError"
    requirement: "OPS-05"
    verification:
      - kind: unit
        ref: "tests/test_logger_config.py (17 malformed-input tests, each pytest.raises(LoggerConfigError))"
        status: pass
    human_judgment: false
  - id: D4
    description: "requirements.txt and requirements-dev.txt cannot drift apart on any shared pin"
    requirement: "OPS-06"
    verification:
      - kind: unit
        ref: "tests/test_logger_config.py#test_requirements_pinned"
        status: pass
    human_judgment: false
  - id: D5
    description: "archive.root_dir and done_marker_filename are configured and available for 01-04/01-05's session layer"
    requirement: "OPS-04"
    verification:
      - kind: unit
        ref: "tests/test_logger_config.py#test_default_config_loads_clean (ArchiveConfig fields populated)"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-08-01
status: complete
---

# Phase 1 Plan 3: Typed Fail-Closed Loader for config/logger.json Summary

**Typed, fail-closed `config/logger.json` loader mirroring `telemetry.measure.config`'s exact shape, with a 12-message critical-channel allowlist resolved against the DBC at startup.**

## Performance

- **Duration:** 20 min
- **Tasks:** 1
- **Files modified:** 5 (4 created, 1 modified)

## Accomplishments

- `config/logger.json` at the repository root, declaring `schema_version`, `dbc_path`, two channels (MAIN/NETID_HSCAN, SENSOR/NETID_HSCAN2), `capture`, `archive` (queue depth 50000, flush every 1000 records / 0.25s), `telemetry` (queue depth 1000, batch_frames 100, batch_max_age_s 0.05, 12-message allowlist), and `link` (loopback kind + always-present UDP settings)
- `src/telemetry/logger/config.py`: `LoggerConfig`, `LoggerConfigError`, `load_logger_config`, `resolve_allowlist` — same frozen-dataclass, `default_path()`, `config_hash`, per-block `_parse_*` structure as `telemetry.measure.config`, diffing unknown/missing keys in both directions for every block
- `resolve_allowlist(config, db)` builds a `frozenset[(frame_id, is_extended)]` from the DBC's `db.messages`, verified to resolve all 12 configured names, raising `LoggerConfigError` naming every unresolvable name at once
- `telemetry.batch_max_age_s` validated as strictly below `wire/encoder.py`'s `MAX_DELTA_T_US / 1_000_000` ceiling, importing the constant rather than restating it
- `tests/test_logger_config.py`: 28 tests — happy path, config_hash stability/change, DBC-path/netid resolution checks, 17 malformed-input branches (one per behavior-block bullet), and `test_requirements_pinned` cross-checking `requirements.txt` / `requirements-dev.txt`
- `tests/conftest.py` gained a session-scoped `logger_config` fixture mirroring `gate_config`

## Task Commits

1. **Task 1: config/logger.json and its typed fail-closed loader** - `d0f50f7` (feat)

**Plan metadata:** pending (this commit)

## Files Created/Modified

- `config/logger.json` - the checked-in runtime config
- `src/telemetry/logger/__init__.py` - empty package marker
- `src/telemetry/logger/config.py` - `LoggerConfig`, `LoggerConfigError`, `load_logger_config`, `resolve_allowlist`
- `tests/test_logger_config.py` - 28 tests covering the happy path, every fail-closed branch, and the manifest cross-check
- `tests/conftest.py` - added session-scoped `logger_config` fixture

## Decisions Made

- `config/logger.json` deliberately lives at the repository root, not beside `config/gate.json`'s phase-artifact location — documented in the module docstring so a later reader does not "fix" the divergence.
- `netid` format (`NETID_`-prefixed string) is validated in the loader without importing `ics`; actual resolution against real `ics` module attributes is a test-only check (`pytest.importorskip("ics")`) so the suite still runs on a machine without the hardware SDK.
- `archive.root_dir` is resolved to an absolute path relative to the repository root but its existence is not checked at load time — the session layer (01-05) is responsible for creating it.
- The `telemetry.batch_frames` 65535 (uint16) ceiling is stated as a bare literal in `config.py` rather than imported, because no batch-header module exists yet to own that constant (unlike `batch_max_age_s`, which imports `MAX_DELTA_T_US` from the already-built `wire/encoder.py`). This asymmetry is intentional and matches what the plan's own behavior block specifies.
- Shipped channel `bus` labels are `bus1`/`bus2`, matching `config/gate.json`'s existing `bus_assignment` naming from Phase 0 rather than inventing new labels.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `resolve_allowlist` is ready for 01-04's fan-out to consume and produce the `(frame_id, is_extended)` filter keys.
- `archive.flush_every_records` / `flush_every_s` are ready for 01-04/01-06's `ArchiveWriter` fsync cadence.
- `link.kind` is ready to select `LoopbackLink` (01-04) or `UdpLink` (01-08) with no change above the config layer.
- No blockers for 01-04.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*

## Self-Check: PASSED

All created files found on disk; commit `d0f50f7` found in git log.
