---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 01
subsystem: supply-chain
tags: [package-legitimacy, gate, dependencies]

# Dependency graph
requires: []
provides:
  - "Human-cleared package legitimacy verdict for mcap, cobs, crccheck, and python-ics"
  - "Unblocks 01-02, which pins these four in requirements.txt under OPS-06"
affects: ["01-02", "01-04", "01-05", "01-06", "01-08", "01-09"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A [SUS] package-legitimacy verdict is never auto-approvable; a human clears it and the verdict is recorded for later audit"

key-files:
  created:
    - .planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-01-SUMMARY.md
  modified: []

requirements: [OPS-06]
---

# Plan 01-01 Summary — Package Legitimacy Gate

**Executed:** 2026-08-01
**Tasks:** 1/1 (single `checkpoint:human-verify`, gate `blocking-human`)
**Files changed:** none — this plan is a gate, not an implementation

## Verdict

**APPROVED — all four packages cleared by the user on 2026-08-01.**

| Package | Version | Checker flag | Verdict |
|---|---|---|---|
| `mcap` | 1.4.0 | `unknown-downloads` | ✓ approved |
| `cobs` | 1.2.2 | `unknown-downloads` | ✓ approved |
| `crccheck` | 1.3.1 | `unknown-downloads` | ✓ approved |
| `python-ics` | `1!26.3.9` | `too-new`, `unknown-downloads` | ✓ approved |

No package was rejected. 01-02 may pin all four.

## Why the flags were not treated as legitimacy findings

Every flag is a checker metadata artifact rather than a signal about the package:

- **`unknown-downloads`** (all four) — the checker could not fetch a download count. This is the
  same flag Phase 0 resolved for `cantools` and `pytest` (STATE.md, Phase 0 2026-07-31); it says
  nothing about the package's provenance.
- **`too-new`** (`python-ics` only) — Intrepid Control Systems ships calendar-versioned point
  releases, so the *point release* is recent even though the project is not. The release history
  spans years.

Two facts specific to this project weighed on the decision and are recorded so a later auditor
does not have to re-derive them:

1. **`python-ics` is not a new dependency.** `src/new_logger.py` already does `import ics` and has
   since before this milestone. Pinning it formalizes a dependency the repository already carries
   rather than introducing one.
2. **`crccheck` was already installed in the dev environment**, despite Phase 0's decision D-06
   stating that COBS and CRC-16 libraries would stay uninstalled. `01-RESEARCH.md` flagged this as
   an untraced environment-state discrepancy (Assumption A5). Approving it deliberately is what
   closes that discrepancy — the alternative was leaving a package present that nobody had chosen.
   The user was offered an explicit option to reject `crccheck` and implement CRC-16 inline
   (~30 lines) instead, and declined it in favour of the dependency.

## Deviations

None. The plan specified a human gate; a human cleared it.

## Notes for later plans

- **01-02** owns writing `requirements.txt` with exact pins. Note that `python-ics` must be pinned
  as `1!26.3.9` (PEP 440 epoch 1), not `26.3.9` — `01-RESEARCH.md`'s illustrative install line
  drops the epoch and is wrong on that point; 01-02 already carries the correction and an
  `<automated>` verify asserting each pin equals the installed version.
- **D-06's original "no COBS/CRC library" position is now superseded** for CRC specifically. If a
  later phase revisits framing, the record is that this was a deliberate, cleared choice rather
  than dependency drift.
