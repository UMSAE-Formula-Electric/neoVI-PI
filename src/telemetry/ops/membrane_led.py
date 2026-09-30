"""
telemetry.ops.membrane_led -- `MembraneLedIndicator` (03-08, OPS-02 gap
closure): the first concrete implementation of the `LedIndicator` Protocol
(`telemetry.ops.led`), driving the neoVI PI's I2C membrane LED panel
(bus 10, address 0x3c) through the measured register sequence recorded in
`03-RESEARCH.md`'s "Full vendor script read" subsection (03-08 Task 1).

Before this module, `NullLedIndicator` was the only implementation that
shipped -- `03-VERIFICATION.md` recorded that as the exact reason success
criterion 2 ("someone standing at the car can tell the logger is alive and
capturing without opening a terminal") FAILED: the seam existed, nothing
drove it. This module is the concrete driver; `telemetry.logger.cli`'s
`main()` is where it gets wired in as `HeartbeatPublisher`'s `led=`
argument -- without that wiring this would be one more artifact that
exists and drives nothing, the same finding again.

**Its own module, deliberately, not an addition to `led.py`.**
`heartbeat.py` already imports `led.py` for `LedIndicator`/
`NullLedIndicator`; this module needs `HEARTBEAT_STATES` from
`telemetry.ops.heartbeat` to build its state-to-colour table, so putting
this class in `led.py` would create `led -> heartbeat -> led`, a cycle.
The chain `membrane_led -> heartbeat -> led` has no such cycle: `led.py`
imports nothing from this package.

**Lazy import, copying `telemetry.capture.hardware_source._default_sdk`'s
shape exactly, for a measured reason, not a stylistic one.** `smbus2`'s
own source (`smbus2/smbus2.py`) does `from fcntl import ioctl` at module
scope, and `fcntl` is Unix-only -- `python -c "import fcntl"` raises
`ModuleNotFoundError` on this Windows dev box, verified live this session.
A module-scope `import smbus2` here would make this module (and therefore
anything importing it, including `telemetry.logger.cli`) unimportable on
the entire development platform. `_default_bus()` below imports `smbus2`
only inside itself, only when no bus object is injected -- so constructing
`MembraneLedIndicator` with an injected fake bus never touches the real
library, and merely importing this module never does either. `python -c
"import telemetry.ops.membrane_led"` succeeding on this Windows box is
the actual proof, not decoration (T-03-32).

**All ten RGB positions are always driven the same colour, never a single
position.** Two independent reasons. First, which physical panel position
corresponds to which index is not established anywhere -- 03-RESEARCH.md
resolved the register map but never the panel layout -- so driving the
whole panel makes that unknown irrelevant to correctness. Second, the
measured write sequence (03-RESEARCH.md) writes the *entire* 30-entry PWM
array in one `write_i2c_block_data` call regardless of how many of the ten
RGB LEDs actually changed, so driving all ten costs exactly the same bus
traffic as driving one would.

**The five colours, and why these five, not just any five.** `capturing`
green, `waiting-for-hardware` blue, `booting` white, `degraded` amber,
`stopped-error` red. The pairing that matters most is
capturing-vs-waiting, because that is the literal distinction success
criterion 2 (`03-VERIFICATION.md`) asks a human standing at the car to
make without opening a terminal -- green against blue stays distinguishable
under the common red-green and blue-yellow colour-vision deficiencies,
where green against amber would not. The two attention states (`degraded`,
`stopped-error`) use the conventional amber/red pairing; confusing those
two with each other is harmless, since both mean "go look," unlike
confusing either with `capturing`. Brightness (full-scale PWM = 255 on
every populated channel) is an unmeasured starting point, not a validated
figure -- nobody has seen this panel illuminated, in daylight or
otherwise; calibrate at the Pi bring-up session (03-09), not here.

**Exactly five states, mirroring `heartbeat.py`'s own locked decision.** A
clean stop is the status file's ABSENCE, not a sixth state -- `close()`
below is what corresponds to that absence (all LEDs off, driver back into
shutdown), never a sixth colour. `_STATE_TO_COLOUR`'s import-time
completeness guard (mirroring `telemetry.ops.cli`'s `_missing_state_info`
guard beneath its own `_STATE_INFO` table) asserts every name in the
imported `HEARTBEAT_STATES` has an entry here, so a future sixth state
landing upstream fails loudly at import here instead of silently getting
no colour.

**Register values and payload shapes below are all taken verbatim from
03-RESEARCH.md's "Full vendor script read" subsection (03-08 Task 1), a
full byte-for-byte read of Intrepid's own `membrane.py` reference script
-- never invented from the register-address constants alone.** The bus
number (10) and I2C address (0x3c) are the vendor script's own values,
cited from that same source, and have NOT been independently confirmed
against this project's own hardware -- no neoVI PI with an LED panel has
been touched by this project. The exact chip part number
(`LS31FL3236A`/`IS31FL3236A`) remains unconfirmed, exactly as
`telemetry.ops.led`'s module docstring already states; nothing here
upgrades that certainty.

`set_state` lets any bus-write exception propagate out to the caller --
`HeartbeatPublisher._drive_led` already catches, counts, and
log-once-suppresses it. This module deliberately does NOT add a second
layer of catching there, which would hide failures from the counters the
publisher already maintains. The one thing `set_state` owns on its way
out through an exception is clearing its own "last state written" cache,
so the next 1 Hz tick retries instead of treating a failed write as
already applied.
"""

import logging
from typing import Dict, Optional, Tuple

from telemetry.ops.heartbeat import (
    HEARTBEAT_STATES,
    STATE_BOOTING,
    STATE_CAPTURING,
    STATE_DEGRADED,
    STATE_STOPPED_ERROR,
    STATE_WAITING_FOR_HARDWARE,
)
from telemetry.ops.led import NullLedIndicator

logger = logging.getLogger(__name__)

# The vendor script's own values (03-RESEARCH.md "Full vendor script
# read") -- NOT independently confirmed against this project's own
# hardware. Overridable as MembraneLedIndicator constructor keyword
# arguments.
DEFAULT_I2C_BUS_NUMBER = 10
DEFAULT_LED_ADDRESS = 0x3C

# Register addresses, verbatim from the vendor script (03-RESEARCH.md).
_LED_DRIVER_SHUTDOWN_REG = 0x00
_LED_DRIVER_PWM_PORT_OFFSET = 0x01
_LED_DRIVER_PWM_UPDATE_REG = 0x25
_LED_DRIVER_LED_CONTROL_REG = 0x26

# Payload shapes, verbatim from the vendor script.
_NUMBER_OF_LEDS = 30  # 10 RGB LEDs * 3 colour channels (RED/GREEN/BLUE)
_NUMBER_OF_RGB_LEDS = 10
_RED_OFFSET = 0
_GREEN_OFFSET = 1
_BLUE_OFFSET = 2

# `led_ctrl` in the vendor script: [LED_ON | LED_SL_HALF_CURRENT] * 30 --
# the combined value (0x03), not either constant alone, is what the
# vendor script actually writes to LED_DRIVER_LED_CONTROL_REG.
_LED_ON = 0x01
_LED_SL_HALF_CURRENT = 0x02
_LED_CONTROL_VALUE = _LED_ON | _LED_SL_HALF_CURRENT  # 0x03

# Values written to LED_DRIVER_SHUTDOWN_REG: 0x01 takes the driver out of
# shutdown (construction), 0x00 puts it back into shutdown (close()).
_SHUTDOWN_TAKE_OUT_OF_SHUTDOWN = 0x01
_SHUTDOWN_PUT_INTO_SHUTDOWN = 0x00

# The vendor script's own PWM-update "pulse" value -- write_byte_data's
# third argument is always 0x00 at every call site that touches
# LED_DRIVER_PWM_UPDATE_REG in membrane.py; the register address, not this
# value, is what actually tells the driver to update.
_PWM_UPDATE_PULSE_VALUE = 0x00

# Brightness is unmeasured -- see module docstring. Full-scale is a
# starting point to calibrate at the Pi bring-up session (03-09), not a
# validated figure.
_PWM_FULL_SCALE = 255
_PWM_OFF = 0

_COLOUR_CAPTURING = (_PWM_OFF, _PWM_FULL_SCALE, _PWM_OFF)  # green
_COLOUR_WAITING_FOR_HARDWARE = (_PWM_OFF, _PWM_OFF, _PWM_FULL_SCALE)  # blue
_COLOUR_BOOTING = (_PWM_FULL_SCALE, _PWM_FULL_SCALE, _PWM_FULL_SCALE)  # white
_COLOUR_DEGRADED = (_PWM_FULL_SCALE, 191, _PWM_OFF)  # amber
_COLOUR_STOPPED_ERROR = (_PWM_FULL_SCALE, _PWM_OFF, _PWM_OFF)  # red

# Keyed by the imported state constants, not retyped string literals --
# see module docstring; restating instead of importing is exactly what
# WR-04 was in this same subsystem, two plans ago.
_STATE_TO_COLOUR: Dict[str, Tuple[int, int, int]] = {
    STATE_BOOTING: _COLOUR_BOOTING,
    STATE_WAITING_FOR_HARDWARE: _COLOUR_WAITING_FOR_HARDWARE,
    STATE_CAPTURING: _COLOUR_CAPTURING,
    STATE_DEGRADED: _COLOUR_DEGRADED,
    STATE_STOPPED_ERROR: _COLOUR_STOPPED_ERROR,
}

_missing_colour = set(HEARTBEAT_STATES) - set(_STATE_TO_COLOUR)
if _missing_colour:
    # A hard failure at import, not a silently uncoloured state -- mirrors
    # telemetry.ops.cli's _missing_state_info guard beneath _STATE_INFO.
    raise RuntimeError(
        "telemetry.ops.membrane_led._STATE_TO_COLOUR is missing entries "
        f"for {sorted(_missing_colour)} present in "
        "telemetry.ops.heartbeat.HEARTBEAT_STATES -- pick a colour before "
        "shipping a new heartbeat state"
    )


def _default_bus(bus_number: int):
    """Lazily imports `smbus2` and opens `bus_number`. Imported only
    here, only when no bus object is injected -- see the module docstring
    for why a module-scope import would make this module unimportable on
    this dev platform."""
    import smbus2

    return smbus2.SMBus(bus_number)


class MembraneLedIndicator:
    """Drives the neoVI PI's I2C membrane LED panel. Satisfies
    `telemetry.ops.led.LedIndicator` structurally (no subclassing -- see
    that Protocol's own docstring on why)."""

    def __init__(
        self,
        bus: Optional[object] = None,
        *,
        bus_number: int = DEFAULT_I2C_BUS_NUMBER,
        address: int = DEFAULT_LED_ADDRESS,
    ) -> None:
        self._address = address
        self._bus = bus if bus is not None else _default_bus(bus_number)
        self._last_state: Optional[str] = None
        self._closed = False

        # The measured initialisation sequence (03-RESEARCH.md): take the
        # driver out of shutdown, write every LED's control register as
        # one block, then pulse the PWM update register.
        self._bus.write_byte_data(
            self._address,
            _LED_DRIVER_SHUTDOWN_REG,
            _SHUTDOWN_TAKE_OUT_OF_SHUTDOWN,
        )
        self._bus.write_i2c_block_data(
            self._address,
            _LED_DRIVER_LED_CONTROL_REG,
            [_LED_CONTROL_VALUE] * _NUMBER_OF_LEDS,
        )
        self._bus.write_byte_data(
            self._address, _LED_DRIVER_PWM_UPDATE_REG, _PWM_UPDATE_PULSE_VALUE
        )

    def set_state(self, state: str) -> None:
        """Writes `state`'s colour to all ten RGB positions, skipping the
        bus write entirely if `state` equals the last one actually
        written -- the publisher calls this at 1 Hz, and most ticks see
        no transition. A raising write clears the skip cache (so the next
        tick retries) and propagates -- see the module docstring for why
        this deliberately does NOT catch."""
        if state == self._last_state:
            return

        red, green, blue = _STATE_TO_COLOUR[state]
        pwm_block = [0] * _NUMBER_OF_LEDS
        for led_index in range(_NUMBER_OF_RGB_LEDS):
            pwm_block[3 * led_index + _RED_OFFSET] = red
            pwm_block[3 * led_index + _GREEN_OFFSET] = green
            pwm_block[3 * led_index + _BLUE_OFFSET] = blue

        try:
            self._bus.write_i2c_block_data(
                self._address, _LED_DRIVER_PWM_PORT_OFFSET, pwm_block
            )
            self._bus.write_byte_data(
                self._address, _LED_DRIVER_PWM_UPDATE_REG, _PWM_UPDATE_PULSE_VALUE
            )
        except Exception:
            self._last_state = None
            raise
        self._last_state = state

    def close(self) -> None:
        """All LEDs off, driver back into shutdown, bus closed -- the
        status file's absence is the "not running" signal (heartbeat.py's
        locked decision), and this is its physical-indicator counterpart.
        Safe to call twice, mirroring `NullLedIndicator`'s "safe in any
        order, any number of times" contract."""
        if self._closed:
            return
        self._closed = True
        self._bus.write_i2c_block_data(
            self._address, _LED_DRIVER_PWM_PORT_OFFSET, [0] * _NUMBER_OF_LEDS
        )
        self._bus.write_byte_data(
            self._address, _LED_DRIVER_PWM_UPDATE_REG, _PWM_UPDATE_PULSE_VALUE
        )
        self._bus.write_byte_data(
            self._address, _LED_DRIVER_SHUTDOWN_REG, _SHUTDOWN_PUT_INTO_SHUTDOWN
        )
        self._bus.close()


LED_KIND_NULL = "null"
LED_KIND_MEMBRANE = "membrane"
VALID_LED_KINDS = (LED_KIND_NULL, LED_KIND_MEMBRANE)
DEFAULT_LED_KIND = LED_KIND_NULL


def build_led_indicator(kind: str = DEFAULT_LED_KIND, *, bus: Optional[object] = None):
    """Factory: returns the no-op indicator for the default kind. For the
    membrane kind, constructs the real driver, and on ANY construction
    exception logs at ERROR naming the cause and falls back to the no-op
    indicator instead -- a missing/broken I2C bus must never stop the
    logger from logging (T-03-31). This fallback is deliberately loud: a
    silent one would let criterion 2 fail invisibly on the car, the same
    shape of defect this whole plan exists to fix (T-03-33)."""
    if kind == LED_KIND_MEMBRANE:
        try:
            return MembraneLedIndicator(bus=bus)
        except Exception as exc:
            logger.error(
                "failed to construct MembraneLedIndicator (kind=%r): %s -- "
                "falling back to the no-op indicator; the logger continues "
                "recording, only the physical status light is unavailable",
                kind,
                exc,
                exc_info=True,
            )
            return NullLedIndicator()
    return NullLedIndicator()
