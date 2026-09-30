"""
telemetry.ops.led -- the `LedIndicator` Protocol seam (OPS-02) that lets
`HeartbeatPublisher` drive a physical status light on every write.

**Two methods, not three.** `telemetry.link.base.Link` is minimal because
a transport needs `send`/`recv`/`close`; a status indicator only ever needs
to be told a state and closed. This module copies that project convention
directly (a `typing.Protocol`, a minimal method surface, no ABC) rather
than growing a bespoke shape.

**The hardware target is CONFIRMED, not guessed** (03-RESEARCH.md, "THE
LED/GPIO QUESTION"): Intrepid's own public documentation repository
(`github.com/intrepidcs/neoVI_PI-docs`) ships a working reference script,
`static/downloads/membrane.py`, driving the neoVI PI's membrane-panel LEDs
through an I2C-attached LED driver at bus 10, address 0x3c.

**Decision (03-03 checkpoint, resolved 2026-09-29): the real membrane LED
IS wanted and approved this milestone** (`approve-and-replan`, not the
plan's own planned-default `defer`). Nothing was installed by that
decision -- it scoped a follow-up plan for a concrete `MembraneLedIndicator`
and sent the two candidate packages through this project's
package-legitimacy-check seam (T-03-10):

- `smbus2` -- **approved**. `SUS` verdict was the single reason
  `unknown-downloads`, a checker metadata-fetch failure, not a legitimacy
  finding (the same artifact Phase 0 adjudicated for `cantools`/`pytest`).
  Exists, not deprecated, `postinstall: null` (no code executes at install
  time). This is the one package the follow-up driver plan needs.
- `RPi.GPIO` -- **descoped, not approved**. Also `SUS`/`unknown-downloads`
  only, and substantively clean, but not currently needed: in Intrepid's
  `membrane.py` it drives `MULTI_BUTTON` (GPIO 4) / `TRIG_BUTTON` (GPIO 5),
  which are operator *input*, out of scope for OPS-01/02/03/07. The LED
  driver itself is pure I2C (bus 10, addr 0x3c) and even shuts down via an
  I2C register, so no GPIO line appears to be required. **This is strongly
  indicated, not proven** -- the follow-up plan must confirm against the
  full `membrane.py` before relying on it, and may still need to add
  `RPi.GPIO` if that confirmation goes the other way.

Setup also requires the `i2c_vc` device-tree overlay enabled in the boot
config. **The path on this car's neoVI PI is `/boot/firmware/config.txt`**
-- user-confirmed against real hardware at the 03-03 checkpoint, not a
measurement this project took and not Intrepid's own doc prose (which
still says `/boot/config.txt`, wrong for current Raspberry Pi OS Bookworm
images, which moved the boot partition mount point). Any install script
that edits this file must target `/boot/firmware/config.txt`.

`NullLedIndicator` below was the only implementation 03-03 shipped.
**03-08 adds the concrete driver**: `telemetry.ops.membrane_led.
MembraneLedIndicator` satisfies this same Protocol and is wired into
`telemetry.logger.cli`'s `HeartbeatPublisher` construction behind a
`--led-kind` flag (default: this module's no-op) -- exactly the "no call
site above this module needs to change" property this docstring predicted.
`03-VERIFICATION.md` recorded the no-op-only state as success criterion
2's FAILING gap; 03-08 moves that criterion to
*unverified-pending-hardware*, not VERIFIED -- there is still no I2C bus,
no LED driver, and no panel on any dev box this project has touched.

The neoVI PI's specification page separately lists "10 programmable
tri-color LEDs" among its hardware features; the exact LED driver chip's
part number was read from a comment in the vendor's reference script and
was NOT independently confirmed against real hardware this session. This
docstring does not restate that fact as more certain than 03-RESEARCH.md
itself claims.

Do NOT add a `/sys/class/leds` code path here. No evidence was found that
generic Pi LED sysfs entries are wired on this carrier board -- Intrepid
built a bespoke I2C panel instead, and a speculative second path would be
an unverified claim in code.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class LedIndicator(Protocol):
    """A synchronous, swappable physical-state indicator. Mirrors
    `telemetry.link.base.Link`'s structural-typing convention: any object
    satisfying this two-method surface can be injected into
    `HeartbeatPublisher` with no other call site changing.

    `set_state` is passed one of `telemetry.ops.heartbeat.HEARTBEAT_STATES`
    on every heartbeat write; this module deliberately stays ignorant of
    what those states mean or map to (colour, blink pattern, ...) -- that
    is a concrete implementation's job, not the Protocol's."""

    def set_state(self, state: str) -> None: ...

    def close(self) -> None: ...


class NullLedIndicator:
    """The no-op `LedIndicator` this plan (03-03) ships, and still the
    default kind `telemetry.logger.cli`'s `--led-kind` flag selects. Both
    methods are unconditionally safe to call, in any order, any number of
    times, including after `close()` -- `HeartbeatPublisher` relies on
    exactly that to keep a missing/broken physical indicator from ever
    being able to affect the status file or the publisher thread. It is
    also `build_led_indicator`'s fallback (`telemetry.ops.membrane_led`)
    when constructing the real driver fails for any reason.

    **A concrete `MembraneLedIndicator` now exists** (03-08,
    `telemetry.ops.membrane_led`), targeting the I2C bus 10 / address
    0x3c LED driver via `smbus2` (approved and pinned behind a linux
    platform marker). `RPi.GPIO` was confirmed, against the full vendor
    script (not just its first 30 lines), to touch only the two input
    buttons and no LED path -- it is resolved-not-needed, not added. The
    `i2c_vc` overlay in `/boot/firmware/config.txt` (user-confirmed for
    this car) and the `i2c` group grant the service user needs are both
    03-09's job, not this module's."""

    def set_state(self, state: str) -> None:
        return None

    def close(self) -> None:
        return None
