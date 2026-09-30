# Phase 3: Unattended On-Car Operation - Research

**Researched:** 2026-08-09
**Domain:** Linux process supervision (systemd), embedded status reporting, disk-space monitoring, and one confirmed hardware-indicator surface — all stdlib-only on the Python side
**Confidence:** HIGH on everything independently verifiable this session (systemd behavior, `os.replace`, `shutil.disk_usage`, `time.monotonic`, `ics` exception surface); the neoVI PI LED surface moved from "unverified" to **CONFIRMED** via the vendor's own published reference implementation; real Pi boot behavior remains genuinely untestable from this Windows dev box and stays a single named UAT item, per the locked decision.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Boot & Supervision (OPS-01)**
- A systemd service unit starts the logger at power-up. Not cron `@reboot`, not a hand-rolled init script.
- Restart policy is `Restart=always` with a bounded rate limit (`StartLimitIntervalSec` / `StartLimitBurst`). A crash mid-session must recover unattended, but a crash-loop must remain visible.
- If the neoVI hardware is not present at boot, the logger stays alive, retries with backoff, and reports `waiting-for-hardware`. This is distinct from an error state and must be visible in the heartbeat.
- The unit file ships in-repo under `deploy/`, with an install script. Version-controlled and reproducible.

**Heartbeat & Liveness (OPS-02)**
- The primary indicator is a heartbeat status file (JSON) plus a `telemetry-status` CLI that renders it. Any physical LED sits behind a thin, optional abstraction. Planning/research MUST confirm the real LED/GPIO surface before any LED code is written; if a usable LED exists, it is driven *through* the abstraction, not instead of the status file.
- Five distinguishable states: `booting`, `waiting-for-hardware`, `capturing`, `degraded`, `stopped-error`.
- Heartbeat is written at 1 Hz and considered stale after 5 s.
- No remote readout this phase. Local status file and CLI only.

**Disk Space (OPS-03)**
- Two-stage thresholds — `warn` and `critical` — both configurable in `config/logger.json`, via the existing typed, fail-closed config loader pattern.
- At critical: refuse to START a new session, warn loudly during a run in progress, and NEVER auto-delete.
- Surfaced in three places: the heartbeat state, a startup log line, and an explicit runbook check step.
- Measured with stdlib `shutil.disk_usage` against the archive root. Not `psutil`, not shelling out to `df`.

**Runbook & Verifiability (OPS-07)**
- The runbook lives at `docs/runbook.md`, joining `docs/power-pull-test.md`.
- Audience is explicitly someone who did not build the system. Must cover: starting a session, confirming health, retrieving the data, and what to do for each bad heartbeat state.
- OS-touching code sits behind thin abstractions with fakes, so the logic is unit-testable on the Windows dev box; the unit file gets a parse/lint test; real boot behaviour becomes ONE explicit Pi UAT item.
- Ops logic lives inside the existing logger process, in a new `src/telemetry/ops/` module. No separate supervisor process.

### Claude's Discretion

No "you decide" answers were recorded — all 16 questions across the 4 areas were accepted as recommended. Discretion remains for: heartbeat file format details and exact field names, backoff curve for hardware retry, the specific default threshold values (must be config-driven regardless), install-script mechanics, and `telemetry-status` output formatting.

### Deferred Ideas (OUT OF SCOPE)

- **Remote/link-borne heartbeat** → Phase 6. Pushing the heartbeat over the radio link is explicitly not this phase.
- **Automated off-car data retrieval** → Phase 8. This phase's runbook covers manual retrieval only.
- **Auto-pruning or rotation of old sessions** → rejected outright for this phase.
- **`psutil` for richer system metrics** → not needed for OPS-03 and would re-trigger the package legitimacy gate.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS-01 | The logger starts automatically on power-up with no keyboard, screen, or login | systemd unit template (verified against real `systemd-analyze verify`, §"systemd Unit"), install-script pattern, `waiting-for-hardware` retry design (§"Hardware Presence Detection") |
| OPS-02 | The logger exposes a heartbeat indicating it is alive and capturing | Atomic JSON heartbeat write/read pattern (§"Atomic Heartbeat Writes"), `time.monotonic()` cross-process semantics correction (§"Common Pitfalls" Pitfall 5), five-state design, `telemetry-status` CLI shape, LED abstraction with a now-**confirmed** concrete hardware target (§"THE LED/GPIO QUESTION") |
| OPS-03 | Remaining disk space is monitored and surfaced before it becomes critical | `shutil.disk_usage` POSIX semantics verified against CPython source (§"Disk Space Semantics"), two-stage threshold config extension pattern |
| OPS-07 | A written runbook covers starting a session, checking health, and retrieving data | Runbook structure precedent from `docs/power-pull-test.md` (§"Runbook Structure"), state→action mapping table |

</phase_requirements>

## Summary

Every open technical question in this phase's research brief resolved to a concrete, verifiable answer this session — including the one the phase deliberately left open. The Intrepid neoVI PI **does** expose a real, software-controllable status-indication surface: 10 programmable tri-color (RGB) LEDs on an I2C-attached LED driver, documented and shipped with a working reference script in Intrepid's own public docs repository. Driving it for real requires two Python packages (`smbus`/`smbus2`, `RPi.GPIO`) that are not in `requirements.txt` today — under this project's zero-new-dependency / package-legitimacy-gate precedent, that means the LED abstraction gets built now (a two-or-three-method `typing.Protocol`, exactly like `Link` and `FrameSource`), a `NullLedIndicator` no-op implementation ships as the default, and a concrete `MembraneLedIndicator` is explicitly out of scope for this phase pending a human checkpoint on the two new packages. This is precisely the outcome CONTEXT.md pre-authorized ("if a usable LED exists, it is driven through the abstraction, not instead of the status file") — it does not require reopening the phase boundary.

The systemd questions resolved with unusual precision because the dev machine has a working WSL Ubuntu instance with a real `systemd-analyze` binary, which is a *validation tool*, not a runtime dependency — using it to lint a unit file does not reopen the already-settled "native Windows CPython, no WSL in the toolchain" decision. Live verification against `systemd-analyze verify` (systemd 259) confirms `StartLimitIntervalSec`/`StartLimitBurst` are **`[Unit]`-section-only** on any systemd this project will ever run against (Raspberry Pi OS Bookworm ships systemd 252; the rule has held since systemd 230, released 2016) — placing them in `[Service]` does not error, it silently *ignores* the key, which is a strictly worse failure mode than a hard error. `configparser` cannot safely lint a real unit file: with `strict=True` (the default) it raises on the second `After=` line; with `strict=False` it silently keeps only the *last* value and drops the rest — both confirmed live against a representative unit file this session. A parse/lint test therefore needs a small hand-rolled structural checker, not `configparser`.

`shutil.disk_usage(...).free` on Linux is `f_bavail * f_frsize` (confirmed against CPython's own `Lib/shutil.py`) — space available to an *unprivileged* user, already excluding root-reserved blocks. This is exactly the honest number for a threshold check, since the logger runs as a non-root systemd service user. `os.replace()`'s atomicity is a documented POSIX guarantee (confirmed against CPython's `Doc/library/os.rst`), making temp-write-then-`os.replace` the correct heartbeat-write pattern, mirroring the project's own `mark_done()` precedent. `time.monotonic()` is comparable across processes on the same machine as of Python 3.5 (`"the clock is now the same for all processes"` — confirmed against the official docs) — this **corrects** the research brief's own premise that it is not comparable across processes. The real caveat is narrower and more dangerous: the clock's reference point resets at *reboot*, not at process restart, so a stale heartbeat file surviving across a reboot boundary (crash-looped past `StartLimitBurst`, then the whole machine restarted) can produce a nonsensical (often negative) staleness delta that a naive `now - written_at > threshold` check would misread as "fresh." This must be guarded explicitly.

**Primary recommendation:** Build every OS-touching concern (heartbeat writer/reader, disk check, hardware-presence probe, LED abstraction) as small, injectable, `Protocol`-typed units inside a new `src/telemetry/ops/` package, exercised by fakes on Windows exactly like `Link`/`FrameSource` already are; ship the systemd unit and install script under `deploy/`, lint the unit file with a hand-rolled structural checker (not `configparser`); and confine everything that genuinely cannot run off the CM4 — real boot ordering, the actual I2C LED driver, `systemd-analyze verify` on the true target systemd — to one named Pi UAT item plus one explicitly deferred LED-driver checkpoint, mirroring how Phase 1 confined its three hardware-only items.

## Architectural Responsibility Map

This phase has no browser/frontend/CDN tier — it is a single-process embedded logger supervised by the OS. The standard web-app tier vocabulary does not fit; the table below uses this project's actual layers instead (see `.claude/CLAUDE.md`'s Component Responsibilities).

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Process start/restart on boot, crash-loop rate limiting | OS (systemd) | — | systemd already owns ordering, restart policy, and journal capture — no application code should reimplement any of this (locked decision) |
| `waiting-for-hardware` retry/backoff | Logger process (`telemetry.ops`, called from `logger/cli.py`) | OS (systemd `Restart=always` is the outer safety net if the process ever does exit) | The retry must be visible in the heartbeat mid-loop, which only application code can do; systemd only sees process exit/restart, not internal state |
| Heartbeat write (1 Hz) | Logger process (`telemetry.ops.heartbeat`) | Local filesystem (target of the atomic write) | The logger process already owns the counters the heartbeat reports; a separate writer would duplicate state (locked decision, explicitly rejects a second process) |
| Heartbeat read/render | `telemetry-status` CLI (new, separate process, `telemetry.ops.cli`) | Local filesystem (source of the read) | Deliberately a different process from the writer — "legible to someone standing at the car" implies a human runs it on demand, not that it lives inside the logger's own stdout |
| Disk-space check | Logger process at startup + mid-session (`telemetry.ops.disk_monitor`) | Local filesystem (`shutil.disk_usage` target) | Refusing to start a session and warning mid-run are both actions only the process holding the archive writer can take |
| LED indication (if ever implemented) | Logger process, behind `LedIndicator` Protocol | I2C bus / GPIO (hardware) | Confirmed real hardware surface exists (§ below), but concrete wiring needs two new dependencies gated behind a checkpoint — not this phase's default path |
| Runbook | Documentation (`docs/runbook.md`) | — | Not code; consumed by a human, not a process |

## THE LED/GPIO QUESTION — Resolved

**CONFIRMED, not UNCONFIRMED.** The neoVI PI has a real, documented, software-controllable status-indication surface.

`[CITED: intrepidcs.com/products/vehicle-network-adapters/neovipi/neovi-pi-specifications/]` — the specification page lists **"10 programmable tri-color LEDs"** among the device's hardware features, separately from a set of **"CAN/CAN FD channel status LEDs"** (link/activity indicators, presumably firmware/hardware-driven — no evidence found that these are software-addressable, and this project has no reason to try).

`[CITED: github.com/intrepidcs/neoVI_PI-docs — docs/control-membrane-leds-and-trigger-button.md]` — Intrepid's own public documentation repository has a page titled **"Controlling Membrane LEDs and Trigger Button"**, and ships a working reference implementation at `static/downloads/membrane.py`. Setup requires enabling the `i2c_vc` device-tree overlay:
```bash
echo "dtparam=i2c_vc=on" | sudo tee -a /boot/config.txt
sudo reboot
```
(On current Raspberry Pi OS Bookworm images this file may be at `/boot/firmware/config.txt` rather than `/boot/config.txt` — Bookworm moved the boot partition mount point.)

**RESOLVED 2026-09-29 — the path on this car's neoVI PI is `/boot/firmware/config.txt`.** Confirmed by the user at plan 03-03's package checkpoint, superseding the `[ASSUMED]` flag this line previously carried. Provenance is **user-confirmed against their own hardware**, not a measurement taken by this project and not Intrepid doc prose (Intrepid's own page still says `/boot/config.txt`, which is wrong for Bookworm) — recorded this way deliberately, per `.claude/CLAUDE.md`'s rule against letting a prose figure stand in for a verified one. Any install script that edits this file must target `/boot/firmware/config.txt`.

`[CITED: github.com/intrepidcs/neoVI_PI-docs — static/downloads/membrane.py, first 30 lines fetched verbatim this session]`:
```python
import smbus
import threading
import RPi.GPIO as GPIO

NUMBER_OF_LEDS = 30
NUMBER_OF_RGB_LEDS = 10
RED_OFFSET = 0
GREEN_OFFSET = 1
BLUE_OFFSET = 2

#I2C ID where the LED Driver is on
I2C_ID = 10

#Address for the LS31FL3236A   (likely IS31FL3236A — a 36-channel PWM LED driver; OCR/typo not independently resolved)
LED_ADDRESS = 0x3c
LED_DRIVER_SHUTDOWN_REG = 0x00
LED_DRIVER_PWM_PORT_OFFSET = 0x01
LED_DRIVER_PWM_UPDATE_REG = 0x25
LED_DRIVER_LED_CONTROL_REG = 0x26

LED_ON = 0x01
LED_OFF = 0x00
LED_SL_HALF_CURRENT = 0x02

CONNECT_TO_PC_LED = 0
```
The reference script also names a `MULTI_BUTTON` (GPIO pin 4) and `TRIG_BUTTON` (GPIO pin 5) — a physical trigger button also exists but is out of scope for this phase (status indication only, no operator input is part of OPS-01/02/03/07).

**What this means for the plan:**

1. **Two new runtime dependencies would be required for a real driver**: `smbus` (or its actively-maintained fork `smbus2`) and `RPi.GPIO`. Neither is stdlib. Both are `[ASSUMED]` in the sense that their exact PyPI package names/versions were not run through `pip index versions` or the package-legitimacy-check seam this session — but their *existence and role* is not a guess; it comes directly from Intrepid's own vendor reference script, not from web search or training-data recall. Do not install them in this phase.
2. **This phase's zero-new-dependency constraint is a hard stop for the concrete implementation**, not for the abstraction. Per this project's precedent (`01-01`'s package-legitimacy-gate blocking checkpoint), adding `smbus2`/`RPi.GPIO` is a `checkpoint:human-verify`-gated decision for a *future* phase or an explicitly-scoped follow-up, not a default action here.
3. **Build the `LedIndicator` Protocol now** (2–3 methods, mirroring `Link`/`FrameSource`'s minimal-surface convention), ship a `NullLedIndicator` default that satisfies it and does nothing, and wire the heartbeat writer to call it unconditionally (so the call site exists and is tested, even though the concrete implementation is a no-op). This satisfies CONTEXT.md's exact instruction: *"if a usable LED exists, it is driven through the abstraction, not instead of the status file"* — a usable LED does exist, but "driven through the abstraction" does not require the abstraction be non-trivial *this phase*.
4. **What remains genuinely unconfirmed**: whether standard CM4 carrier-board LEDs (`/sys/class/leds/*`, e.g. an ACT/PWR LED path some Pi HATs expose) are wired on the neoVI PI's specific carrier board at all — no evidence either way was found, and it is very likely **not** applicable, since Intrepid built a bespoke I2C-driven membrane LED panel instead of relying on any generic Pi `/sys/class/leds` entries. Do not implement a `/sys/class/leds` code path speculatively.

### Full vendor script read — settled 2026-09-30 (03-08 Task 1)

`[VERIFIED: github.com/intrepidcs/neoVI_PI-docs, raw fetch of the complete
static/downloads/membrane.py this session — all 148 lines read verbatim,
not the first-30-lines excerpt cited above, and not a summarizing fetch.]`
This supersedes the "strongly indicated, not proven" language in the
Package Legitimacy Audit below with a settled verdict.

**A. The GPIO verdict: CONFIRMED `RPi.GPIO` is resolved-not-needed.** Every
`GPIO.` call in the full script, enumerated exhaustively:

| Call | Pin/argument | Purpose |
|------|--------------|---------|
| `GPIO.setmode(GPIO.BCM)` | — | numbering scheme only |
| `GPIO.setup(MULTI_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)` | pin 4 | input pull-up |
| `GPIO.setup(TRIG_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)` | pin 5 | input pull-up |
| `GPIO.add_event_detect(MULTI_BUTTON, GPIO.RISING, callback=IncrementMultiState, bouncetime=100)` | pin 4 | rising-edge callback |

That is the complete set — four calls, zero of them touching an LED. Every
LED write in the script (`StartLEDUpdaterThread`, `SetMembraneRGBLED`,
`SetAllRGBLEDs`, and the module-level init block under `if __name__ ==
'__main__':`) goes exclusively through `i2c.write_byte_data`/
`i2c.write_i2c_block_data` — none of the four `GPIO.` calls appears inside
or adjacent to any LED-writing function. **This directly confirms the
prior session's summarizing-fetch corroboration** (recorded above as
"strongly indicated, not proven"); that corroboration is now upgraded to a
verbatim, byte-for-byte read of the whole file, not a second corroboration.
Provenance is still a full read of the *vendor's reference script*, not a
measurement against this project's own real hardware — no neoVI PI with an
LED panel has been touched by this project. `RPi.GPIO` is **not** added to
`requirements.txt` by Task 2 as a result.

**B. The initialisation write sequence**, in order, straight out of the
script's `if __name__ == '__main__':` block (lines 111-120 of the fetched
file):

1. `i2c = smbus.SMBus(I2C_ID)` — opens bus 10.
2. `i2c.write_byte_data(LED_ADDRESS, LED_DRIVER_SHUTDOWN_REG, 0x01)` — takes
   the driver out of shutdown. Register `0x00`, value `0x01`.
3. `i2c.write_i2c_block_data(LED_ADDRESS, LED_DRIVER_LED_CONTROL_REG,
   led_ctrl)` — writes the 30-entry `led_ctrl` block to register `0x26`.
   `led_ctrl = [LED_ON | LED_SL_HALF_CURRENT] * NUMBER_OF_LEDS` — literal
   value per entry is `0x01 | 0x02 = 0x03`, literal length `30`
   (`NUMBER_OF_LEDS`). The constants alone (recorded above) do not give
   this combined value; this is the first read of the actual combination.
4. `i2c.write_byte_data(LED_ADDRESS, LED_DRIVER_PWM_UPDATE_REG, 0x00)` —
   pulses the update register. Register `0x25`, value `0x00`.

**C. The set-colour write sequence.** `SetMembraneRGBLED(ledNumber, red,
green, blue)` mutates a module-level flat array, `led_map` (initialised
`[0x00] * NUMBER_OF_LEDS`, length **30**, confirmed), at
`led_map[3*ledNumber + RED_OFFSET(0)]`, `led_map[3*ledNumber +
GREEN_OFFSET(1)]`, `led_map[3*ledNumber + BLUE_OFFSET(2)]`. `SetAllRGBLEDs`
calls that once per RGB LED (`range(0, 10)` — all ten). The actual bus
write happens separately, in `StartLEDUpdaterThread` (a 0.1 s
`threading.Timer` loop in the vendor script, not invoked synchronously
after a colour is set):

1. `i2c.write_i2c_block_data(LED_ADDRESS, LED_DRIVER_PWM_PORT_OFFSET,
   led_map)` — writes the whole 30-entry array to register `0x01`.
2. `i2c.write_byte_data(LED_ADDRESS, LED_DRIVER_PWM_UPDATE_REG, 0x00)` —
   pulses the update register again. Register `0x25`, value `0x00`.

The vendor's own timer-thread indirection is a UI-polling detail of its
multi-button colour-wheel demo (`multiState`/`Color_Wheel`), irrelevant to
this project's single-state indicator; Task 3's driver performs these same
two writes synchronously right after mutating its own array, which changes
when the bus is written, not the register sequence or payload shape being
recorded here.

**D. `smbus2` call-surface check — re-confirmed.** `class SMBus` in the
downloaded `smbus2-0.6.1-py2.py3-none-any.whl` exposes `open`, `close`,
`write_byte_data`, and `write_i2c_block_data` — the exact four calls B and
C above use (`SMBus(I2C_ID)` maps to `open` at construction). Recorded as
verified-against-the-wheel per the prior session's check; this session's
Task 1 did not need to re-run it, since the call names above are unchanged
from what B/C already needed.

**Not re-confirmed this session, still carried forward unverified:** the
`LS31FL3236A`/`IS31FL3236A` part-number comment in the script, and the
LED-driver chip's real part number — this read looked only at Python
control flow, not at chip datasheets, and does not upgrade that claim's
certainty beyond what the section above already states.

## Standard Stack

### Core

No new runtime packages. Everything in this phase is stdlib on the Python side.

| Module | Version | Purpose | Why Standard |
|--------|---------|---------|--------------|
| `os` | stdlib (3.12.10 installed, target CM4 likely 3.11+) | `os.replace` atomic rename, `os.fsync`, `os.getpid` | POSIX rename atomicity is a language-level guarantee, not a library feature — no reason to depend on anything else |
| `shutil` | stdlib | `shutil.disk_usage` | Locked decision; avoids `psutil`/`df` |
| `json` | stdlib | Heartbeat file serialization | Matches every other machine-readable output in this codebase (`logger/cli.py`, `ground/cli.py` both already emit JSON) |
| `time` | stdlib | `time.monotonic()` for staleness comparison | See correction below — comparable across processes on the same boot, not across reboots |
| `configparser` | stdlib | **Not recommended** for unit-file linting — see Pitfall below | Included here only to document why it was rejected |
| `threading` | stdlib | Backoff/retry loop timing, mirrors existing `threading.Timer` watchdog pattern in `logger/cli.py` | Already the project's established concurrency primitive |

### Supporting

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| systemd | 252 on Raspberry Pi OS Bookworm `[CITED: Debian 12 package archive, via web search this session]`; 259 in this dev box's WSL Ubuntu instance `[VERIFIED: wsl -e systemctl --version, this session]` | Process supervision, restart policy, journal capture | Locked decision — the deployment OS already has it |
| `systemd-analyze verify` | Whatever ships with the target systemd | Unit-file semantic validation | **Only available on Linux.** Usable from this Windows dev box via WSL as a validation tool (not a toolchain dependency) — see "Testing systemd from Windows" below |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| systemd `Restart=always` | Hand-rolled bash watchdog loop | Rejected by locked decision — reinvents ordering, restart-rate-limiting, and journal capture systemd already provides for free |
| `shutil.disk_usage` | `psutil.disk_usage` | Rejected by locked decision — new dependency, re-triggers the package legitimacy gate for no functional gain (`psutil` wraps the exact same `statvfs`/`GetDiskFreeSpaceEx` calls) |
| `configparser` for unit-file lint | Hand-rolled line-based structural checker | `configparser` is unsafe for real unit files (duplicate-key handling proven wrong this session) — see Pitfalls |
| I2C `smbus`/`smbus2` + `RPi.GPIO` for real LED control | `NullLedIndicator` now, real driver later behind a checkpoint | Two new dependencies; correct decision per project precedent is to gate, not silently add |

**Installation:** None. `requirements.txt` is unchanged by this phase.

**Version verification:** No new packages to verify against a registry. `python-ics==1!26.3.9` (already pinned) was re-confirmed installed this session via `pip show python-ics`.

## Package Legitimacy Audit

Not applicable — this phase installs zero new runtime packages, per the locked "zero new runtime dependencies" constraint. The two packages a real LED driver would need are named below for the record, sourced from Intrepid's own reference script (not from web search or training-data recall), but neither is installed, evaluated against the legitimacy-check seam, or added to `requirements.txt` in this phase:

| Package | Registry | Verdict | Disposition |
|---------|----------|---------|-------------|
| `smbus2` | PyPI | **Ran 2026-09-29: `SUS`, sole reason `unknown-downloads`** | **Approved.** Exists; repo `github.com/kplindegaard/smbus2`; not deprecated; **`postinstall: null`**; last published 2026-04-09. `unknown-downloads` is a checker-fetch failure, not a legitimacy finding — the identical artifact Phase 0 adjudicated for `cantools`/`pytest` (see STATE.md Decisions, 2026-07-31). This is the one package the status LED needs. |
| `RPi.GPIO` | PyPI | **Ran 2026-09-29: `SUS`, sole reason `unknown-downloads`** | **Not needed — descoped.** Signals otherwise clean (exists; repo `sourceforge.net/projects/raspberry-gpio-python`; not deprecated; `postinstall: null`) but **last published 2022-02-06**. In Intrepid's `membrane.py` it drives `MULTI_BUTTON` (GPIO 4) and `TRIG_BUTTON` (GPIO 5) — operator *input*, out of scope for OPS-01/02/03/07. The LED driver is pure I2C (bus 10, addr `0x3c`) and even shuts down via an I2C register (`LED_DRIVER_SHUTDOWN_REG = 0x00`), so no GPIO line appears to be required. **Strongly indicated, not proven:** the driver plan must confirm against the full `membrane.py` before relying on it. The CM4 (BCM2711) is unaffected by the Pi 5 `lgpio`/`rpi-lgpio` migration, so this remains available if a GPIO line does turn out to be needed. |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** `smbus2` and `RPi.GPIO` both returned `SUS`, each for the single reason `unknown-downloads` — a metadata-fetch failure in the checker, not a supply-chain signal. Both were reviewed on their substantive signals (existence, repo, deprecation, `postinstall`) and neither executes code at install time. `smbus2` is approved for the follow-up driver plan; `RPi.GPIO` is descoped rather than approved.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
                         │              systemd (OS tier)           │
                         │  telemetry-logger.service                │
                         │  Restart=always, StartLimitIntervalSec/  │
                         │  StartLimitBurst in [Unit]                │
                         └──────────────────┬────────────────────────┘
                                             │ starts / restarts
                                             ▼
   power-up, no login ──────────────►┌───────────────────────────────────────┐
                                      │   telemetry.logger.cli main()         │
                                      │   (existing Phase 1/2 process)        │
                                      │                                       │
                                      │  ┌─────────────────────────────────┐  │
                                      │  │  telemetry.ops (NEW)            │  │
                                      │  │                                 │  │
   neoVI hardware ───probe──────────►│  │  hardware_wait: retry+backoff   │  │
   (may not be present at boot)      │  │      │                          │  │
                                      │  │      ▼                          │  │
                                      │  │  heartbeat.write(state) ────────┼──┼──► var/status.json (atomic:
                                      │  │      ▲   at 1 Hz                │  │      tmp write + os.replace)
                                      │  │      │                          │  │            │
                                      │  │  disk_monitor.check() ──────────┤  │            │
                                      │  │      │  (shutil.disk_usage      │  │            │
                                      │  │      │   against archive.root)  │  │            │
                                      │  │      ▼                          │  │            │
                                      │  │  led.LedIndicator (Protocol) ───┼──┼──► [deferred: I2C LED, or
                                      │  │      (NullLedIndicator today)   │  │      NullLedIndicator no-op]
                                      │  └─────────────────────────────────┘  │            │
                                      │                                       │            │
                                      │  existing FanOut / ArchiveRunner /    │            │
                                      │  TelemetryPipeline (Phase 1, untouched)│           │
                                      └───────────────────────────────────────┘            │
                                                                                            │
   "someone standing at the car" ──runs──►  telemetry.ops.cli (telemetry-status)  ◄─────────┘
                                            separate process, reads var/status.json,
                                            renders human-readable state + staleness
```

### Recommended Project Structure

```
deploy/
├── telemetry-logger.service   # systemd unit, checked in
└── install.sh                 # copies unit, daemon-reload, enable --now

docs/
└── runbook.md                 # start / verify health / retrieve / troubleshoot-by-state

src/telemetry/ops/
├── __init__.py
├── config.py           # OpsConfig dataclass block, extends telemetry.logger.config's shape
├── heartbeat.py         # HeartbeatState constants, HeartbeatWriter (atomic write), read_heartbeat()
├── disk_monitor.py      # DiskState (ok/warn/critical), check_disk_space()
├── hardware_wait.py     # wait_for_hardware(sdk, stop_event, on_state) retry/backoff loop
├── led.py               # LedIndicator Protocol + NullLedIndicator
└── cli.py                # telemetry-status entry point (python -m telemetry.ops.cli)

tests/
├── test_ops_heartbeat.py
├── test_ops_disk_monitor.py
├── test_ops_hardware_wait.py
├── test_ops_led.py
├── test_ops_cli.py
└── test_deploy_unit_file.py   # structural lint of deploy/telemetry-logger.service
```

### Pattern 1: systemd unit — verified structure

Verified this session by writing a draft unit, copying it into a real Linux filesystem inside WSL (copying via `/mnt/c/...` produced a spurious "file is marked executable" warning from a `drvfs` permission quirk — copy into the native WSL filesystem, or `chmod 644` explicitly, before verifying), and running the actual `systemd-analyze verify` binary (systemd 259) against it:

```ini
# deploy/telemetry-logger.service
[Unit]
Description=UMSAE telemetry logger
After=network.target local-fs.target
Wants=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=telemetry
WorkingDirectory=/opt/telemetry
Environment=PYTHONPATH=src
ExecStart=/usr/bin/python3 -m telemetry.logger.cli
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

`[VERIFIED: systemd-analyze verify, this session, systemd 259 via WSL Ubuntu]` — this exact file produces **zero warnings and exit code 0**. The same file with `StartLimitIntervalSec`/`StartLimitBurst` moved into `[Service]` instead produces, verbatim:

```
telemetry-logger.service:14: Unknown key 'StartLimitIntervalSec' in section [Service], ignoring.
```
— i.e. **not a parse error**, a silent no-op. This is the answer to research question 2's ambiguity: on any systemd this project will run against (Bookworm's 252, or the 259 tested here — the `[Unit]`-only placement has held since systemd 230, released 2016), these two keys belong in `[Unit]`. Do not place them in `[Service]`; the unit will load and *look* fine, and only fail to actually rate-limit restarts, which is a much worse failure mode than a load-time error.

**`After=`/`Wants=` for a device that may not be present at boot:** do not add `After=` or `Requires=` on any udev-generated device unit for the neoVI hardware. The whole point of the `waiting-for-hardware` state is that the *application* handles this race with its own retry loop (§ Hardware Presence Detection below) — encoding a hardware dependency at the systemd level would either block startup indefinitely or require guessing a udev device-unit name that has not been established and may not even exist for this device class. `After=local-fs.target` is enough to ensure the archive root's filesystem (the onboard NVMe, `[ASSUMED]` to be the root filesystem itself on this carrier board — not independently confirmed) is mounted before the logger starts.

### Pattern 2: Install script

```bash
#!/usr/bin/env bash
set -euo pipefail
UNIT_NAME="telemetry-logger.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sudo install -m 644 "${SCRIPT_DIR}/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable --now "${UNIT_NAME}"
```
`install -m 644` avoids the spurious "marked executable" warning observed live this session when a unit file's permission bits carry an execute bit through a copy. `daemon-reload` before `enable --now` is required any time the unit file on disk changed — systemd caches unit definitions.

### Pattern 3: Atomic heartbeat writes

```python
# telemetry/ops/heartbeat.py — sketch, not final code
import json
import os
import time
from pathlib import Path

def write_heartbeat(path: Path, payload: dict) -> None:
    """Write `payload` to `path` atomically. The temp file MUST be created
    in the same directory as `path` -- os.replace()'s atomicity is a POSIX
    rename() guarantee that only holds within one filesystem, and cross-
    device rename can fail outright (verified against CPython's own
    Doc/library/os.rst this session)."""
    tmp_path = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)  # atomic on POSIX; readers never see a torn write
```
`[VERIFIED: Doc/library/os.rst, python/cpython 3.12 branch, fetched this session]` — the canonical text: *"If successful, the renaming will be an atomic operation (this is a POSIX requirement)... The operation may fail if src and dst are on different filesystems."* The `.tmp-{pid}` suffix avoids collision if, hypothetically, two writers ever ran against the same path (should never happen given the locked "no separate supervisor process" decision, but costs nothing to guard).

### Pattern 4: Hardware presence probe (`waiting-for-hardware`)

`telemetry.capture.hardware_source.HardwareFrameSource.open()` (existing, Phase 1) already establishes the correct exception surface — reuse it, do not reinvent it:

```python
def wait_for_hardware(sdk, stop_event, poll_backoff_s, on_waiting) -> bool:
    """Returns True once devices are found, False if stop_event fires first.
    Treats BOTH a caught sdk.RuntimeError and an empty devices tuple as
    'not present yet' -- see the two confirmed/unconfirmed cases below."""
    while not stop_event.is_set():
        try:
            devices = sdk.find_devices()
        except sdk.RuntimeError:       # NEVER the builtin RuntimeError
            devices = ()
        if devices:
            return True
        on_waiting()                    # heartbeat -> waiting-for-hardware
        stop_event.wait(timeout=poll_backoff_s)
    return False
```

Two distinct conditions both surface through `sdk.find_devices()`, and only one is fully verified:

- **`[VERIFIED: live against installed python-ics 1!26.3.9, this session]`** — with the native driver library entirely absent (this Windows dev box has no `icsneo40.dll`), `find_devices()` **raises `ics.RuntimeError`** (`Error: find_devices(): Failed to Retrieve address of function 'icsneoFindDevices'...`). Confirmed again: `issubclass(ics.RuntimeError, builtins.RuntimeError)` is `False` — the module docstring's warning about this is correct and this session re-confirms it independently.
- **`[ASSUMED — inferred from existing, already-merged code, not independently re-verified this session]`** — with the driver present but zero devices physically attached (the expected CM4/Linux condition during the boot race this feature exists for), `find_devices()` is expected to return an **empty tuple**, not raise. This is what `HardwareFrameSource.open()`'s own code already assumes (`if not devices: raise DeviceNotFoundError`), reviewed and merged in Phase 1. No Linux box with the real driver installed and zero devices attached was available to re-test this exact condition this session. The probe above is written to handle **both** outcomes identically and safely regardless of which is actually true on the CM4, so this gap does not block planning — but it should be confirmed on first real Pi bring-up (natural fit for the same Pi UAT item that already covers dual-bus hardware capture).

### Pattern 5: Disk-space check

```python
import shutil
from pathlib import Path

def check_disk_space(archive_root: Path, warn_bytes: int, critical_bytes: int) -> str:
    usage = shutil.disk_usage(archive_root)   # injectable via a thin wrapper for tests
    if usage.free < critical_bytes:
        return "critical"
    if usage.free < warn_bytes:
        return "warn"
    return "ok"
```
For tests on Windows, wrap `shutil.disk_usage` behind a one-line seam (`disk_usage_fn: Callable[[Path], os.statvfs_result-like] = shutil.disk_usage`) so a fake can return arbitrary `(total, used, free)` tuples without touching the real filesystem — same injectable-callable convention already used for the archive writer's `clock=` parameter.

### Pattern 6: `LedIndicator` Protocol

```python
# telemetry/ops/led.py
from typing import Protocol

class LedIndicator(Protocol):
    """Mirrors Link/FrameSource's minimal-surface convention."""
    def set_state(self, state: str) -> None: ...
    def close(self) -> None: ...

class NullLedIndicator:
    """Default implementation this phase ships. A real MembraneLedIndicator
    (I2C, smbus2 + RPi.GPIO) is deferred behind a checkpoint -- see
    'THE LED/GPIO QUESTION' above."""
    def set_state(self, state: str) -> None:
        pass
    def close(self) -> None:
        pass
```

### Anti-Patterns to Avoid

- **Writing the heartbeat file directly with `open(path, "w")`**: a reader (`telemetry-status`, a different process) can observe a partially-written file mid-write. Always temp-write + `os.replace`.
- **Using `configparser` to validate the shipped unit file**: proven this session to silently corrupt or reject valid systemd syntax (repeated `After=`/`Environment=` lines). Use a small structural line-checker instead.
- **Comparing `time.monotonic()` values across a reboot boundary without a guard**: see Pitfall 5.
- **Encoding hardware presence as a systemd unit dependency** (`After=some-device.device`): the whole reason the retry/backoff lives in application code is that the device's udev unit name is not established and the race is expected, not exceptional.
- **`assert total == used + free`** on Linux `shutil.disk_usage` output: false in general because `used` is computed from `f_bfree` (all free blocks) while `free` is computed from `f_bavail` (free blocks available to unprivileged users) — see Disk Space Semantics below.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Process restart on crash, boot-time start | A bash watchdog loop or cron `@reboot` script | systemd `Restart=always` + `StartLimitIntervalSec`/`StartLimitBurst` | Locked decision; systemd already gives ordering, journal capture, and rate-limited restart for free |
| Atomic status-file publication | Direct `open(path, "w")` write, or a file lock | temp-write + `os.replace()` | POSIX rename atomicity is a language/OS guarantee, not something to reimplement with locking |
| Disk-free measurement | Shelling out to `df` and parsing its output | `shutil.disk_usage` | Locked decision; `df`-parsing is fragile across locales/versions and `shutil.disk_usage` already wraps the same `statvfs` call |
| Unit-file validation | A `configparser`-based linter | A small hand-rolled structural checker (§ below), or `systemd-analyze verify` via WSL as a supplementary manual check | `configparser` demonstrably mishandles valid systemd syntax (proven this session) |
| Hardware-presence retry | A new polling mechanism independent of `python-ics` | Reuse `sdk.find_devices()`, exactly as `HardwareFrameSource.open()` already does, wrapped in a retry loop | One SDK entry point for "is hardware here," not two divergent implementations |

**Key insight:** every "don't hand-roll" item above already has a stdlib or OS-level primitive that provides the correct guarantee (atomicity, rate-limiting, disk semantics) — this phase's job is wiring, not invention.

## Runtime State Inventory

Not applicable — this is not a rename/refactor/migration phase. It adds new files and one new config section; it does not rename or move any existing runtime state, stored data, or OS-registered artifact. Confirmed by reading `03-CONTEXT.md`'s phase boundary ("Any change to the capture, archive, or telemetry data paths themselves... this phase observes them, it does not modify them") and `.claude/CLAUDE.md`.

## Common Pitfalls

### Pitfall 1: `StartLimitIntervalSec`/`StartLimitBurst` silently ignored in the wrong section
**What goes wrong:** The unit loads without error; restarts are simply never rate-limited, so a crash-loop is silent instead of visible — the exact failure mode the locked decision says must stay visible.
**Why it happens:** These keys moved from `[Service]` to `[Unit]` in systemd 230 (2016); older tutorials and AI training data both still show the old placement, and systemd does not treat an unrecognized key as fatal — it logs `Unknown key '...', ignoring` and continues.
**How to avoid:** Put both keys in `[Unit]`. Verified this session (§ Pattern 1).
**Warning signs:** `systemd-analyze verify` output containing `Unknown key`, or (on the real Pi) `journalctl -u telemetry-logger` never showing rate-limiting after repeated manual crashes.

### Pitfall 2: `configparser` corrupts or rejects valid unit-file syntax
**What goes wrong:** `configparser.ConfigParser()` (default `strict=True`) raises `DuplicateOptionError` on a second `After=` line — completely valid, common systemd syntax. `strict=False` "succeeds" but silently **drops every value except the last** for a repeated key, which is actively misleading, not merely incomplete.
**Why it happens:** INI format (what `configparser` implements) treats each key as unique per section by design; systemd's unit-file grammar deliberately allows (and in several directives, *requires* the ability to) repeat a key to append.
**How to avoid:** `[VERIFIED: tested live this session]` — write a small line-based structural checker instead: verify `[Section]` headers match a known set, every non-blank/non-comment line matches `Key=Value`, and (optionally) that known required keys are present at least once. Do not attempt semantic validation (dependency graphs, directive-specific type checking) on Windows — that is exactly what `systemd-analyze verify` is for, and it is only available on real systemd.
**Warning signs:** A "passing" unit-file test that silently accepts a file with only one of two intended `After=` targets.

### Pitfall 3: `os.replace` across filesystems
**What goes wrong:** If the heartbeat temp file is created somewhere other than the target's own directory (e.g. `/tmp` while the target is on the NVMe-backed archive path), `os.replace` can fail outright rather than silently doing something wrong — but only if `/tmp` and the target happen to be different mounts, which is easy to get right in development (single filesystem) and wrong on a real embedded image with a tmpfs `/tmp`.
**Why it happens:** POSIX `rename()`'s atomicity guarantee is scoped to a single filesystem; cross-device rename is a different, non-atomic operation that many platforms simply refuse.
**How to avoid:** Always create the temp file in the *same directory* as the target path (`path.with_suffix(...)`), never in a fixed temp directory.
**Warning signs:** `OSError: [Errno 18] Invalid cross-device link` on the real Pi that never reproduces in dev-box tests (because the dev box likely has one filesystem for everything).

### Pitfall 4: `ics.RuntimeError` vs builtin `RuntimeError`
**What goes wrong:** A bare `except RuntimeError:` around the hardware-presence probe silently fails to catch the SDK's actual exception, so "no driver present" propagates as an unhandled exception and crashes the process instead of transitioning to `waiting-for-hardware`.
**Why it happens:** `ics.RuntimeError`'s MRO is `(ics.ics.RuntimeError, Exception, BaseException, object)` — it does not subclass the builtin. Already a documented, previously-verified project fact (`hardware_source.py`'s own docstring); re-confirmed live again this session.
**How to avoid:** Always catch via the injected SDK object's own attribute (`sdk.RuntimeError`), exactly as `HardwareFrameSource` already does — never the bare builtin name.
**Warning signs:** A hardware-presence probe that works in tests (against a fake SDK whose exception happens to subclass the builtin) but crashes the real process on the CM4.

### Pitfall 5: `time.monotonic()` staleness check across a reboot boundary
**What goes wrong:** If a heartbeat file from a *previous boot* survives (e.g. the systemd unit crash-looped past `StartLimitBurst` and the whole Pi was then power-cycled, or the file is just being inspected by hand well after the fact), its `written_at` monotonic value was measured against the *previous* boot's clock reference. A new `time.monotonic()` call on the current boot can be smaller than that stale value, producing a **negative** `now - written_at` — which a naive `if now - written_at > 5.0: stale` check reads as **not stale** (false negative — the worst possible outcome for a health indicator).
**Why it happens:** `[VERIFIED: docs.python.org/3/library/time.html, fetched this session]` — `time.monotonic()`'s docs state *"Changed in version 3.5: the clock is now the same for all processes"*, i.e. it **is** safely comparable across two different processes on the same running system (this **corrects** the research brief's premise that it is not) — but the clock's reference point resets at reboot, not at process restart. Two processes on the *same boot* compare correctly; a file surviving *across* a reboot does not.
**How to avoid:** Guard the staleness comparison: treat any negative `now - written_at` (or one implausibly large, e.g. hours, for a 1 Hz heartbeat) as **stale**, not fresh — `age = max(0, now - written_at)` is not sufficient by itself since it would still read "0 = fresh"; explicitly check `now < written_at` and report stale/unknown in that branch. In practice this rarely bites in normal operation, because the systemd service overwrites the heartbeat within its first second of any successful start — but it will bite if a human inspects a stale file from a machine that has been rebooted since the process last ran, which is exactly a "should I trust what I'm looking at" moment the runbook needs to call out explicitly.
**Warning signs:** `telemetry-status` reporting a session as "alive" immediately after a power cycle, before the logger has actually restarted.

### Pitfall 6: `used + free != total` on Linux
**What goes wrong:** A test or a display line that asserts `usage.total == usage.used + usage.free` will occasionally be false on real Linux filesystems.
**Why it happens:** `[VERIFIED: python/cpython Lib/shutil.py, fetched this session]` — the POSIX branch computes `free = f_bavail * f_frsize` (blocks available to an *unprivileged* user) but `used = (f_blocks - f_bfree) * f_frsize` (using `f_bfree`, *all* free blocks, including root-reserved ones). `f_bavail <= f_bfree` whenever the filesystem reserves blocks for root (ext4's default ~5% reserve), so `used + free` can be slightly less than `total`. This is intentional — it matches `df`'s own long-standing behavior — not a bug to "fix."
**How to avoid:** Threshold logic should compare `usage.free` against the configured bytes directly; never derive a "percent used" figure by assuming `used + free == total`.
**Warning signs:** A disk-usage unit test with a hardcoded `total = used + free` fixture that would fail against real `os.statvfs` output.

## Code Examples

### Reading a heartbeat file for the status CLI

```python
# Source: pattern derived from this session's verified os.replace/shutil.disk_usage findings
import json
import time
from pathlib import Path

def read_heartbeat(path: Path, stale_after_s: float) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    now = time.monotonic()
    written_at = raw["written_at_monotonic"]
    age = now - written_at
    raw["stale"] = age < 0 or age > stale_after_s   # Pitfall 5 guard
    return raw
```

### Disk usage POSIX semantics, straight from CPython

```python
# Source: python/cpython Lib/shutil.py, 3.12 branch, fetched verbatim this session
def disk_usage(path):
    st = os.statvfs(path)
    free = st.f_bavail * st.f_frsize   # unprivileged-available -- the honest number
    total = st.f_blocks * st.f_frsize
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    return _ntuple_diskusage(total, used, free)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `StartLimitInterval`/`StartLimitBurst` in `[Service]` | `StartLimitIntervalSec`/`StartLimitBurst` in `[Unit]` | systemd 230, 2016 | Any tutorial or training-data example predating this is wrong for every systemd this project will run against |
| `RPi.GPIO` as the default GPIO library for all Raspberry Pi models | `lgpio`/`rpi-lgpio` recommended on Pi 5-class boards (different GPIO chip) | Pi 5 launch, 2023 | Does not affect the CM4 (same BCM2711 SoC family as Pi 4) — `RPi.GPIO` remains the vendor-referenced choice for the neoVI PI's own membrane script, `[CITED]` |

**Deprecated/outdated:** None specific to this phase's stdlib-only surface — `os.replace`, `shutil.disk_usage`, and `time.monotonic` are all long-stable stdlib APIs with no pending deprecation.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ics.find_devices()` returns an empty tuple (rather than raising) when the driver is present but zero devices are attached, on Linux | Pattern 4 (Hardware Presence Probe) | Low — the probe is written to handle both outcomes identically; wrong only changes which branch fires, not correctness. Confirm on first real Pi bring-up. |
| A2 | The neoVI PI's archive/root filesystem is on the same mount as the boot filesystem (`local-fs.target` is sufficient ordering) | Pattern 1 (systemd Unit) | Low-medium — if the NVMe archive is a separate, later-mounting filesystem, the unit needs an explicit `After=` on that mount unit instead; would surface immediately as a startup failure on first real deployment, not silently |
| A3 | Raspberry Pi OS Bookworm's boot config lives at `/boot/firmware/config.txt` rather than `/boot/config.txt` for the `i2c_vc` overlay needed by the LED driver | THE LED/GPIO QUESTION | None for this phase (LED driver is deferred entirely) — relevant only if/when a future phase implements `MembraneLedIndicator` |
| A4 | `smbus`/`smbus2` and `RPi.GPIO` PyPI package names/current versions, beyond their role confirmed in Intrepid's reference script | Package Legitimacy Audit | None for this phase (not installed) — must be verified via `pip index versions` and the legitimacy-check seam before any future phase installs them |

**If this table is empty:** N/A — see above.

## Open Questions (RESOLVED)

> Both questions below carry answers that the plans act on, so neither blocks execution.
> Q1 is resolved by construction — `After=local-fs.target` is correct either way, and 03-06
> implements exactly that. Q2 is out of scope — the LED I2C driver is deferred behind 03-03's
> blocking package checkpoint, so the `config.txt` path is never read this phase.

1. **Does the CM4's archive filesystem mount at the same point in boot as the root filesystem?**
   - What we know: the project treats the NVMe as "onboard" storage; no evidence found of a separate late-mounting partition.
   - What's unclear: whether Intrepid's reference image partitions the NVMe such that the archive path is a distinct mount from `/`.
   - Recommendation: use `After=local-fs.target` (already covers all locally-mounted filesystems generically) rather than guessing a specific mount unit name — this is correct regardless of how the answer to this question resolves.

2. **Exact `/boot/config.txt` vs `/boot/firmware/config.txt` path for the `i2c_vc` overlay on the shipped neoVI PI image.**
   - What we know: Intrepid's own doc says `/boot/config.txt`; generic Bookworm images moved this to `/boot/firmware/config.txt`.
   - What's unclear: which convention Intrepid's own shipped OS image (which may not be a stock Bookworm image) actually uses.
   - Recommendation: irrelevant to this phase (LED driver deferred); resolve only if/when a future phase implements `MembraneLedIndicator`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|--------------|-----------|---------|----------|
| systemd | OPS-01 unit supervision | ✗ on dev box (native Windows has no systemd); ✓ via WSL Ubuntu for validation only | 259 (WSL Ubuntu) `[VERIFIED this session]`; 252 expected on target Bookworm `[CITED]` | Structural unit-file lint (hand-rolled, § Pitfall 2) runs everywhere; real semantic verification confined to WSL (supplementary) or the Pi UAT item |
| Real neoVI hardware / native driver | Hardware-presence probe, real LED I2C bus | ✗ (no driver, no hardware on this dev box) | — | `sdk.RuntimeError` path already exercised live this session with the driver-absent condition; fake-SDK injection (existing `HardwareFrameSource` convention) covers unit tests |
| I2C bus 10 / IS31FL3236A LED driver | Concrete `MembraneLedIndicator` (deferred) | ✗ | — | `NullLedIndicator` ships this phase; real driver is out of scope |
| `smbus2`/`RPi.GPIO` | Concrete `MembraneLedIndicator` (deferred) | ✗ (not installed, deliberately) | — | See above |

**Missing dependencies with no fallback:** None that block this phase — every OS-touching concern has either a working fallback (WSL for `systemd-analyze`, fake SDK for hardware) or is explicitly deferred (LED driver).

**Missing dependencies with fallback:** systemd semantic verification (WSL), real hardware presence (fake SDK), real LED hardware (`NullLedIndicator`).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 `[VERIFIED: requirements.txt]` |
| Config file | `pytest.ini` (`pythonpath = src`, `testpaths = tests`, `addopts = -ra`, marker `slow`) |
| Quick run command | `python -m pytest -x -q --tb=short` (matches `.planning/config.json`'s `workflow.test_command`) |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| OPS-01 | systemd unit loads with correct `[Unit]`-section restart-rate-limit keys, no unknown-key warnings | unit (structural lint, no real systemd needed) | `pytest tests/test_deploy_unit_file.py -x` | ❌ Wave 0 |
| OPS-01 | `wait_for_hardware` retries on both `sdk.RuntimeError` and empty-tuple, emits `waiting-for-hardware` heartbeat, exits cleanly on `stop_event` | unit (fake SDK) | `pytest tests/test_ops_hardware_wait.py -x` | ❌ Wave 0 |
| OPS-02 | Heartbeat writer produces valid JSON atomically (temp file gone, target readable mid-loop from a second handle) | unit | `pytest tests/test_ops_heartbeat.py -x` | ❌ Wave 0 |
| OPS-02 | Staleness check correctly flags negative/implausible age as stale (Pitfall 5 regression) | unit | `pytest tests/test_ops_heartbeat.py -x -k stale` | ❌ Wave 0 |
| OPS-02 | `telemetry-status` CLI renders all 5 states legibly, reports staleness | unit (subprocess or direct call against a fixture heartbeat file) | `pytest tests/test_ops_cli.py -x` | ❌ Wave 0 |
| OPS-03 | Disk check returns `ok`/`warn`/`critical` correctly at threshold boundaries; refuses new session at `critical` | unit (injected fake `disk_usage`) | `pytest tests/test_ops_disk_monitor.py -x` | ❌ Wave 0 |
| OPS-03 | `config/logger.json`'s new `ops` section round-trips through the typed loader, rejects malformed thresholds | unit | `pytest tests/test_logger_config.py -x -k ops` | ❌ Wave 0 (extends existing file) |
| OPS-07 | `docs/runbook.md` exists and names every heartbeat state at least once | unit (content-presence check, not prose grading) | `pytest tests/test_runbook_coverage.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest -x -q --tb=short`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`, plus the one named Pi UAT item (real boot, real systemd, real hardware race) recorded exactly as Phase 1 recorded its three hardware-only items.

### Wave 0 Gaps

- [ ] `tests/test_deploy_unit_file.py` — covers OPS-01 (structural lint)
- [ ] `tests/test_ops_hardware_wait.py` — covers OPS-01 (retry/backoff)
- [ ] `tests/test_ops_heartbeat.py` — covers OPS-02
- [ ] `tests/test_ops_disk_monitor.py` — covers OPS-03
- [ ] `tests/test_ops_cli.py` — covers OPS-02
- [ ] `tests/test_runbook_coverage.py` — covers OPS-07
- [ ] No new framework install needed — pytest already present and configured.

## Security Domain

`security_enforcement` is `true`, `security_asvs_level: 1` in `.planning/config.json`.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|----------------|---------|-------------------|
| V2 Authentication | No | No new authenticated surface — the heartbeat file and `telemetry-status` CLI are local-only, no network exposure this phase |
| V3 Session Management | No | N/A |
| V4 Access Control | Partial | The systemd unit should run as a dedicated non-root `User=` (not root), matching least-privilege — this also means any future I2C/GPIO LED work will need explicit group membership (`i2c`, `gpio`), a concrete reason to keep it deferred/gated rather than default-on |
| V5 Input Validation | Yes | The new `ops` section of `config/logger.json` goes through the existing typed, fail-closed `LoggerConfigError`-raising loader — same discipline as every other config block, never a silent default |
| V6 Cryptography | No | Nothing in this phase touches cryptographic material |

### Known Threat Patterns for this phase's stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Heartbeat/status file world-writable, tampered with to hide a real failure | Tampering | File permissions inherited from the systemd service's `User=`/`umask`; not a network-exposed file this phase, so risk is limited to local access (already implied by physical access to the car) |
| Install script run as root without verifying the unit file's own permission bits first | Elevation of Privilege | `install -m 644` sets explicit permissions rather than trusting the source file's bits (also fixes the cosmetic "marked executable" warning observed live) |
| systemd service running as root unnecessarily | Elevation of Privilege | Dedicated `User=` in the unit, non-root, consistent with V4 above |

## Sources

### Primary (HIGH confidence — verified this session via a tool)
- `python/cpython` (3.12 branch) `Lib/shutil.py` — `shutil.disk_usage` POSIX implementation, fetched and reproduced verbatim
- `python/cpython` (3.12 branch) `Doc/library/os.rst` — `os.replace` atomicity guarantee, fetched and reproduced verbatim
- `docs.python.org/3/library/time.html` — `time.monotonic()` cross-process comparability (`"the clock is now the same for all processes"`, since 3.5), fetched this session
- `ics` (`python-ics==1!26.3.9`) installed package, this session: `ics.RuntimeError` MRO, `ics.find_devices()` behavior with no native driver, `ics.find_devices` docstring
- `systemd-analyze verify` (systemd 259, via WSL Ubuntu on this dev box) — live verification of the drafted unit file, both correct and incorrect `StartLimitIntervalSec` placement
- `configparser` (stdlib) — live test of `strict=True`/`strict=False` behavior against a representative unit file with duplicate keys
- `os.replace` sanity check (same-directory temp-then-replace round trip on the dev box)

### Secondary (MEDIUM confidence — official/vendor documentation, not independently re-run)
- `intrepidcs.com/products/vehicle-network-adapters/neovipi/neovi-pi-specifications/` — "10 programmable tri-color LEDs", "CAN/CAN FD channel status LEDs"
- `github.com/intrepidcs/neoVI_PI-docs` — `docs/control-membrane-leds-and-trigger-button.md`, `static/downloads/membrane.py` (first 30 lines fetched verbatim)
- Web search: Raspberry Pi OS Bookworm ships systemd 252 (Debian 12 package archive)

### Tertiary (LOW confidence — flagged in Assumptions Log)
- `/boot/config.txt` vs `/boot/firmware/config.txt` path for the neoVI PI's specific shipped image (A3)
- `ics.find_devices()`'s exact return behavior on Linux with driver present but zero devices attached (A1)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every module used is stdlib, no version ambiguity
- Architecture: HIGH — patterns directly mirror already-reviewed Phase 1/2 code (`Link`, `FrameSource`, `mark_done`, `HardwareFrameSource.open()`)
- Pitfalls: HIGH — five of six pitfalls verified live via tool this session (systemd, configparser, os.replace docs, time.monotonic docs, shutil.disk_usage source); one (A1, Linux driver-present-zero-device behavior) explicitly flagged as inferred, not re-verified
- LED/GPIO hardware surface: MEDIUM-HIGH — confirmed via vendor's own public reference implementation (not training-data guess, not web-search inference), but the exact PWM driver chip identity (OCR'd as "LS31FL3236A", almost certainly IS31FL3236A) and the CM4 image's boot-config path were not independently cross-verified against real hardware

**Research date:** 2026-08-09
**Valid until:** 30 days for the stdlib/systemd findings (stable APIs, stable OS); the LED/GPIO vendor documentation should be re-checked if this phase's LED work is ever picked up, since it lives in Intrepid's own docs repo and could change without this project's knowledge
