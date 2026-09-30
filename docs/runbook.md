# Operating the UMSAE Telemetry Logger

A runbook for starting a session on the car, confirming it is healthy, and
retrieving the data afterward — written for a team member who did not build
this system and has no context from planning. If you can open a terminal,
you have everything you need.

This document covers **OPS-01, OPS-02, OPS-03, and OPS-07**: starting
automatically with no keyboard/screen/login, the heartbeat health signal,
disk-space monitoring, and this runbook itself.

**What this does NOT cover:** automated off-car data retrieval does not
exist yet — that is a later phase. "Retrieving the data" below is a manual
procedure only. This document also does not describe a physical status LED:
none ships in this phase (see "Pi bring-up" below for what is actually
planned there).

---

## First-time install on the car

Run this once, as root, from inside a deployed checkout of this repository
at `/opt/telemetry` — the exact path the shipped systemd unit's
`WorkingDirectory=` names:

```
sudo bash deploy/install.sh
```

**Prerequisite:** a full checkout of this repository must already exist at
`/opt/telemetry`, with `src/telemetry` and `config/logger.json` both present.
`deploy/install.sh` does not clone or copy the repository itself — getting a
checkout onto the Pi is a separate deployment step this script deliberately
does not make for you, and it will refuse to run (with a clear error) if
that checkout is not already there.

What the one command does, in order:

1. Creates the `telemetry` system service account, idempotently — if it
   already exists, it is not recreated.
2. Confirms `/opt/telemetry` looks like a real deployed checkout.
3. Installs `deploy/telemetry-logger.service` to
   `/etc/systemd/system/telemetry-logger.service` with explicit `644`
   permissions, reloads systemd's unit cache, then enables and starts the
   service immediately (`enable --now`) — it will also start on every future
   boot without this step being repeated.
4. Creates the archive root (`/opt/telemetry/sessions`) and the heartbeat
   file's parent directory (`/opt/telemetry/var`), and gives the unprivileged
   `telemetry` account ownership of both, so the service can actually write
   to them on first boot.

---

## Starting a session

Apply power. That is the entire procedure.

There is no screen to look at, no keyboard to plug in, and no login step —
the unit installed above starts `telemetry.logger.cli` automatically on
boot, before anyone could log in even if they wanted to. If you have
operated a different logger before and are looking for a "press start"
step, there is not one here: it happens by itself, every time, as soon as
the car has power.

---

## Confirming it is healthy

Run the status reader — a **separate process** from the logger itself, so
checking health never risks disturbing a capture in progress:

- From the repository root on a dev box: `python -m telemetry.ops.cli`
- On the car (deployed layout): `cd /opt/telemetry && PYTHONPATH=src python3 -m telemetry.ops.cli`

Add `--json` to either form for a single machine-readable line instead
(`python -m telemetry.ops.cli --json`) — useful for scripting a check, and
for the disk-space step below.

The logger republishes its status file every `heartbeat_interval_s` seconds
(1 second, by default in `config/logger.json`'s `ops` block) at the path
named by `heartbeat_path` (`var/status.json` by default — `/opt/telemetry/var/status.json`
on the deployed layout). If the file's age ever exceeds `heartbeat_stale_after_s`
(5 seconds, by default), the reading is reported **stale** regardless of
which state it last recorded — staleness always outranks the state itself,
in both the headline and the exit code, so a status file frozen mid-`capturing`
can never read as healthy just because that was good news at the time.

Every fresh reading names one of five states:

| State | What it means | What to do |
|---|---|---|
| `booting` | The logger has started and is loading its configuration and DBC. | Expected to last well under a second. If it persists, check the journal: `journalctl -u telemetry-logger.service -e`. |
| `waiting-for-hardware` | The logger is alive and retrying — the CAN bus is most likely not powered yet. | **This is the normal power-up sequence on this car, not a fault.** The CM4 usually finishes booting before the CAN bus itself is powered, so this state appears briefly on almost every start and clears itself once the bus comes up. |
| `capturing` | The logger is recording. | Read the JSON `extras` (or the evidence line the plain-text form prints) to confirm frames are actually moving — session name, frames/s, and frame counts submitted vs. archived. |
| `degraded` | Still recording, but something needs attention. | Read the `detail` field (JSON) or the detail line (plain text) for what — most commonly a disk-space band; see "Checking remaining space" below. |
| `stopped-error` | The logger stopped and did not finish cleanly — this session's archive will have no completion marker. | Check the journal: `journalctl -u telemetry-logger.service -e`. |

---

## Reading the exit code

`telemetry.ops.cli` (aliased `telemetry-status` in its own docstrings) exits
with one of five codes, useful whether you are reading it by eye or from a
script:

| Exit code | Meaning | What it means for a script |
|---|---|---|
| `0` | Fresh reading; state is `booting`, `waiting-for-hardware`, or `capturing`. | The logger is alive and doing what it should — the "all clear" code. |
| `1` | The status file exists but could not be read or parsed, or the command's own config could not be loaded. | Treat as an unknown/error condition; the error text names the exact file and reason. |
| `2` | Fresh reading; state is `degraded` or `stopped-error`. | Alive, but something needs a human's attention — read `detail`. |
| `3` | Stale — the file has not been updated recently enough to trust, regardless of which state it last recorded. | Treat as "health not confirmed." A dead logger frozen on a good-looking last state must never read as healthy, so this always wins over whatever state is inside. |
| `4` | No status file exists at the configured path at all. | Expected after a clean stop. If the service is actually *running* with no file at all, see "When something is wrong" below — that combination is not this code's normal meaning. |

---

## Checking remaining space

Run the status command with `--json` and read two fields inside the
`extras` object: `disk_free_bytes` and `disk_state` (one of `ok`, `warn`,
`critical`). These two fields are populated once the logger has reached
`capturing` or `degraded` — during the brief `booting`/`waiting-for-hardware`
window before that, the authoritative source is the startup line in the
journal instead (`journalctl -u telemetry-logger.service -e`, look for
"disk space at startup").

The two thresholds behind the `disk_state` band are configured in
`config/logger.json`'s `ops` block as `disk_warn_free_bytes` and
`disk_critical_free_bytes` — shipped today as 20 GiB (`21474836480`) and
5 GiB (`5368709120`) respectively. **These are CHOSEN round numbers, not
measurements** — no full-rate session's real archive growth rate has been
measured on this car yet, so calibrate both once a real session's size is
known, rather than trusting these figures as validated.

What to do at each band:

- **`ok`** — nothing to do.
- **`warn`** — no action is required immediately, but plan to free space or
  grow the archive volume before the next several sessions.
- **`critical`** — the logger **refuses to START a new session** below this
  band (it exits, logs the free-bytes and threshold figures, and leaves a
  `stopped-error` heartbeat naming both). It **never stops a run already in
  progress** — a partially-written session is worth more than no session at
  all — but it will log loudly (rate-limited) while the band persists.
  **Nothing in this system ever deletes, rotates, or prunes session data**,
  in any band, ever; freeing space is always a human action taken outside
  this software.

---

## Retrieving the data

Sessions live under the archive root configured by `archive.root_dir` in
`config/logger.json` — `sessions/` relative to the repository root by
default, which is `/opt/telemetry/sessions` on the deployed layout (the same
path `deploy/install.sh` creates and gives the `telemetry` account
ownership of).

Each session is its own directory. **Only a session directory that also
contains the `.done` marker file is finished** — an interrupted session (a
crash, a bad shutdown, an archive that did not close cleanly) is
deliberately left *without* that marker, on purpose: its data up to the
interruption is real and usable, but the session did not close cleanly and
that fact must stay visible, not be hidden by a marker file that would
imply otherwise.

Copy **whole session directories**, not individual files inside them.
Automated off-car retrieval does not exist yet — it is a later phase; for
now, retrieval is manual (`scp`, a USB drive, or pulling the NVMe and
mounting it elsewhere).

---

## When something is wrong

Two situations a reader cannot otherwise diagnose from the status command
alone:

**A service that is running, but there is no status file at all.** This
means the logger's configuration failed to parse *before* the heartbeat
file's own path was even known — the earliest point `config.ops.heartbeat_path`
becomes known is right after a successful config load, so a config error
before that point produces no file, not a `stopped-error` file. The reason
is in the journal, not in any status file:

```
journalctl -u telemetry-logger.service -e
```

**An age figure you do not trust because the machine has rebooted.** A
status file's reported age is measured against a monotonic clock whose
reference point resets at every reboot. If the machine has rebooted since a
stale file was last written (for example, the unit crash-looped past its
restart budget, and then the whole machine was power-cycled), that file's
age cannot be reasoned about numerically — `telemetry-status` detects this
specific case and reports it as its own reason
(`clock-went-backwards`) rather than folding it into ordinary staleness. A
running logger rewrites this file within a second of starting; if it has
not, re-run the status command rather than reasoning about the stale
number, and treat the logger as not running until a fresh reading appears.

---

## Pi bring-up: the one hardware-only verification (OPS-01)

This is the single item in this phase that cannot be checked anywhere but
on the actual car — nothing runnable on a dev box can prove a car boots
into this unit with no one present. It mirrors how `docs/power-pull-test.md`
holds ARCH-03 open against a real power-pull rather than an automated
proxy: a structural lint proves a unit file's *shape*; only running it on
real hardware proves it actually boots into the service.

**Procedure:**

1. **Install**, per "First-time install on the car" above.
2. **Reboot with the CAN bus unpowered.** Confirm the service comes up on
   its own (no keyboard, no screen, no login) and `telemetry-status`
   reports `waiting-for-hardware`. **Pass:** the state reaches
   `waiting-for-hardware` on its own within a few seconds of boot, with no
   manual intervention.
3. **Power the CAN bus** while the unit is still waiting. Confirm the state
   becomes `capturing` with frames actually moving (check the evidence
   line/`extras` for a non-zero `frames_per_s`). **Pass:** the transition
   from `waiting-for-hardware` to `capturing` happens on its own, with
   frames flowing, and no restart of the service was needed.
4. **Reboot again, this time with the bus already powered.** Confirm the
   service reaches `capturing` on its own, with no manual intervention at
   all. **Pass:** `capturing` is reached without anyone touching the car.

**While the car is in front of you, also confirm** — these are open
questions carried forward specifically for this item, not separate hardware
UAT entries:

- Whether the SDK's device lookup returns an empty result or raises an
  exception when the driver is present but nothing is attached (both are
  currently treated identically by `wait_for_hardware`, so this does not
  block anything, but should be confirmed).
- Whether the archive filesystem mounts in time under
  `After=local-fs.target`'s ordering, or needs an explicit, stronger mount
  dependency if the archive volume turns out to mount later/separately.
- The `/opt/telemetry` deployment layout itself (the checkout genuinely
  lives there, with `src/telemetry` and `config/logger.json` present).
- The `telemetry` service-account creation step actually succeeding on real
  Raspberry Pi OS Bookworm.
- The archive-root and heartbeat-directory ownership (`chown telemetry:telemetry`)
  actually granting the unprivileged process write access it needs on first
  boot.

**OPS-01 stays Pending in `.planning/REQUIREMENTS.md` until this section has
actually been run and passed** — exactly the same discipline
`docs/power-pull-test.md` established for ARCH-03: a green test suite and a
verified-clean unit-file structure are necessary, but neither is a
substitute for this physical procedure.
