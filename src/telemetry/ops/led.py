"""
telemetry.ops.led -- the `LedIndicator` Protocol seam (OPS-02) that lets
`HeartbeatPublisher` drive a physical status light on every write, without
this project committing to real I2C/GPIO code before a human decides the
two required packages are worth adding.

**Two methods, not three.** `telemetry.link.base.Link` is minimal because
a transport needs `send`/`recv`/`close`; a status indicator only ever needs
to be told a state and closed. This module copies that project convention
directly (a `typing.Protocol`, a minimal method surface, no ABC) rather
than growing a bespoke shape.

**The hardware target is CONFIRMED, not guessed** (03-RESEARCH.md, "THE
LED/GPIO QUESTION"): Intrepid's own public documentation repository
(`github.com/intrepidcs/neoVI_PI-docs`) ships a working reference script,
`static/downloads/membrane.py`, driving the neoVI PI's membrane-panel LEDs
through an I2C-attached LED driver at bus 10, address 0x3c. That script
imports two PyPI packages, neither of which is in this project's
`requirements.txt`: `smbus` (or its maintained fork, `smbus2`) and
`RPi.GPIO`. Adding either is a human decision under this project's
package-legitimacy-check precedent (01-01's blocking checkpoint, threat
T-03-10 in 03-03-PLAN.md's threat model) -- never a default action a plan
takes on its own. 03-03's own checkpoint task records that decision;
unless/until it says otherwise, `NullLedIndicator` below is the only
implementation shipped. A future `MembraneLedIndicator` satisfying this
same Protocol is how a real driver would be added later -- no call site
above this module (namely `HeartbeatPublisher`) would need to change.

The neoVI PI's specification page separately lists "10 programmable
tri-color LEDs" among its hardware features; the exact LED driver chip's
part number was read from a comment in the vendor's reference script and
was NOT independently confirmed against real hardware this session. This
docstring does not restate either fact as more certain than 03-RESEARCH.md
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
    """The no-op `LedIndicator` this phase ships as the default. Both
    methods are unconditionally safe to call, in any order, any number of
    times, including after `close()` -- `HeartbeatPublisher` relies on
    exactly that to keep a missing/broken physical indicator from ever
    being able to affect the status file or the publisher thread.

    A concrete `MembraneLedIndicator` (deferred -- see module docstring)
    would target the I2C bus 10 / address 0x3c LED driver this docstring
    already cites; it needs `smbus`/`smbus2` and `RPi.GPIO`, neither of
    which is installed, per the human decision this plan's checkpoint
    records."""

    def set_state(self, state: str) -> None:
        return None

    def close(self) -> None:
        return None
