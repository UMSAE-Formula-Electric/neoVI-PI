"""
Behaviour-first tests for `telemetry.ops.membrane_led` (03-08, OPS-02 gap
closure): the first concrete `LedIndicator` implementation.

**What these tests prove, and what they do not.** Every assertion here
runs against a recording fake bus that captures each call as
`(method, address, register, payload)`. That proves the register writes
this code *intends* -- the exact sequences 03-RESEARCH.md's "Full vendor
script read" subsection measured from Intrepid's own reference script.
It does NOT prove a light turns on: there is no I2C bus, no LED driver
chip, and no panel on this dev box, and nothing in this file claims
otherwise. That physical proof folds into the single Pi bring-up
verification 03-09 extends, not a second hardware trip.
"""

import importlib.util
import sys

import pytest

from telemetry.ops.heartbeat import (
    STATE_BOOTING,
    STATE_CAPTURING,
    STATE_DEGRADED,
    STATE_STOPPED_ERROR,
    STATE_WAITING_FOR_HARDWARE,
)
from telemetry.ops.led import LedIndicator, NullLedIndicator
from telemetry.ops.membrane_led import (
    DEFAULT_LED_ADDRESS,
    LED_KIND_MEMBRANE,
    LED_KIND_NULL,
    MembraneLedIndicator,
    _STATE_TO_COLOUR,
    build_led_indicator,
)

# Register addresses, verbatim from 03-RESEARCH.md's "Full vendor script
# read" subsection -- asserted here as literal values, not re-imported
# from the module's own (private) constants, so a test typo can't
# silently agree with a code typo.
_SHUTDOWN_REG = 0x00
_PWM_PORT_OFFSET_REG = 0x01
_PWM_UPDATE_REG = 0x25
_LED_CONTROL_REG = 0x26

_LED_CONTROL_VALUE = 0x03  # LED_ON (0x01) | LED_SL_HALF_CURRENT (0x02)
_NUMBER_OF_LEDS = 30


def _full_scale_block(red: int, green: int, blue: int):
    block = [0] * _NUMBER_OF_LEDS
    for led_index in range(10):
        block[3 * led_index + 0] = red
        block[3 * led_index + 1] = green
        block[3 * led_index + 2] = blue
    return block


class _RecordingBus:
    """A fake `smbus2.SMBus` that records every call as
    `(method, address, register, payload)`. `fail_next_write` makes
    exactly the next write raise (and nothing else), for the
    clears-cache-and-retries test below."""

    def __init__(self):
        self.calls = []
        self.fail_next_write = False

    def _record_or_raise(self, call):
        if self.fail_next_write:
            self.fail_next_write = False
            raise RuntimeError("simulated bus write failure")
        self.calls.append(call)

    def write_byte_data(self, address, register, value):
        self._record_or_raise(("write_byte_data", address, register, value))

    def write_i2c_block_data(self, address, register, data):
        self._record_or_raise(
            ("write_i2c_block_data", address, register, list(data))
        )

    def close(self):
        self.calls.append(("close", None, None, None))


def test_module_imports_without_the_real_smbus2_library():
    # The proof that matters most is `python -c "import
    # telemetry.ops.membrane_led"` on this Windows box (03-08 Task 3's
    # plan verify gate) -- this file already imported the module above
    # without that import failing. Re-assert it did not need `smbus2` to
    # do so (every test below injects a fake bus; none constructs the
    # real one).
    assert "smbus2" not in sys.modules


def test_construction_performs_measured_init_sequence_and_nothing_else():
    bus = _RecordingBus()
    MembraneLedIndicator(bus=bus)

    assert bus.calls == [
        ("write_byte_data", DEFAULT_LED_ADDRESS, _SHUTDOWN_REG, 0x01),
        (
            "write_i2c_block_data",
            DEFAULT_LED_ADDRESS,
            _LED_CONTROL_REG,
            [_LED_CONTROL_VALUE] * _NUMBER_OF_LEDS,
        ),
        ("write_byte_data", DEFAULT_LED_ADDRESS, _PWM_UPDATE_REG, 0x00),
    ]


def test_set_state_capturing_writes_full_scale_green_block():
    bus = _RecordingBus()
    indicator = MembraneLedIndicator(bus=bus)
    bus.calls.clear()

    indicator.set_state(STATE_CAPTURING)

    green_block = _full_scale_block(red=0, green=255, blue=0)
    assert all(entry == 0 for entry in green_block[0::3])  # every red entry
    assert all(entry == 0 for entry in green_block[2::3])  # every blue entry
    assert bus.calls == [
        (
            "write_i2c_block_data",
            DEFAULT_LED_ADDRESS,
            _PWM_PORT_OFFSET_REG,
            green_block,
        ),
        ("write_byte_data", DEFAULT_LED_ADDRESS, _PWM_UPDATE_REG, 0x00),
    ]


def test_repeated_state_touches_the_bus_only_once():
    bus = _RecordingBus()
    indicator = MembraneLedIndicator(bus=bus)
    bus.calls.clear()

    indicator.set_state(STATE_CAPTURING)
    after_first = len(bus.calls)
    indicator.set_state(STATE_CAPTURING)

    assert len(bus.calls) == after_first, "second identical state must skip the bus"


def test_raising_write_clears_the_cache_so_the_next_call_retries():
    bus = _RecordingBus()
    indicator = MembraneLedIndicator(bus=bus)
    bus.calls.clear()

    bus.fail_next_write = True
    with pytest.raises(RuntimeError, match="simulated bus write failure"):
        indicator.set_state(STATE_CAPTURING)

    # Retrying the SAME state must not be treated as already-applied --
    # the failure above cleared the skip cache.
    indicator.set_state(STATE_CAPTURING)
    assert len(bus.calls) == 2  # the block write + the update pulse


def test_close_writes_all_zero_block_shuts_down_and_is_safe_to_call_twice():
    bus = _RecordingBus()
    indicator = MembraneLedIndicator(bus=bus)
    bus.calls.clear()

    indicator.close()

    assert bus.calls == [
        (
            "write_i2c_block_data",
            DEFAULT_LED_ADDRESS,
            _PWM_PORT_OFFSET_REG,
            [0] * _NUMBER_OF_LEDS,
        ),
        ("write_byte_data", DEFAULT_LED_ADDRESS, _PWM_UPDATE_REG, 0x00),
        ("write_byte_data", DEFAULT_LED_ADDRESS, _SHUTDOWN_REG, 0x00),
        ("close", None, None, None),
    ]

    bus.calls.clear()
    indicator.close()  # safe to call twice -- no second round of writes
    assert bus.calls == []


def test_set_state_after_close_does_not_raise():
    bus = _RecordingBus()
    indicator = MembraneLedIndicator(bus=bus)
    indicator.close()
    bus.calls.clear()

    indicator.set_state(STATE_CAPTURING)  # must not raise -- bus is closed

    assert bus.calls == [], "no write should reach the already-closed bus"


@pytest.mark.parametrize(
    "state",
    [STATE_BOOTING, STATE_WAITING_FOR_HARDWARE, STATE_DEGRADED, STATE_STOPPED_ERROR],
)
def test_set_state_writes_its_own_distinct_pwm_block_for_every_non_capturing_state(state):
    """03-08 only asserted `capturing`'s block (the tracer). These are the
    other four -- parameterised over the driver's own table rather than
    hand-listing four near-identical test bodies, so a future colour edit
    updates the expectation for free instead of leaving a case untested."""
    bus = _RecordingBus()
    indicator = MembraneLedIndicator(bus=bus)
    bus.calls.clear()

    indicator.set_state(state)

    red, green, blue = _STATE_TO_COLOUR[state].rgb
    expected_block = _full_scale_block(red=red, green=green, blue=blue)
    assert bus.calls == [
        (
            "write_i2c_block_data",
            DEFAULT_LED_ADDRESS,
            _PWM_PORT_OFFSET_REG,
            expected_block,
        ),
        ("write_byte_data", DEFAULT_LED_ADDRESS, _PWM_UPDATE_REG, 0x00),
    ]


def test_no_two_heartbeat_states_share_the_same_pwm_block():
    """Set-size check over the driver's own table -- a future colour edit
    that accidentally collides two states fails here instead of on the
    car, where the two would be indistinguishable to a human standing at
    it."""
    rgb_triples = [colour.rgb for colour in _STATE_TO_COLOUR.values()]
    assert len(set(rgb_triples)) == len(rgb_triples)


def test_every_colour_has_a_name_and_no_two_names_collide():
    names = [colour.name for colour in _STATE_TO_COLOUR.values()]
    assert all(isinstance(name, str) and name for name in names)
    assert len(set(names)) == len(names)


def test_set_state_raises_naming_the_offending_value_for_an_unknown_state():
    bus = _RecordingBus()
    indicator = MembraneLedIndicator(bus=bus)
    bus.calls.clear()

    with pytest.raises(ValueError, match="bogus-unknown-state"):
        indicator.set_state("bogus-unknown-state")

    assert bus.calls == [], "an unknown state must raise, never write"


def test_import_time_guard_fails_loudly_on_a_missing_colour(monkeypatch):
    """A sixth heartbeat state landing upstream must fail at import here,
    not silently get no colour -- mirrors `telemetry.ops.cli`'s
    `_missing_state_info` guard.

    Executes a SEPARATE module object loaded from the same source file,
    rather than `importlib.reload`-ing the canonical
    `telemetry.ops.membrane_led` module in place -- a reload would swap
    the live `MembraneLedIndicator` class object out from under every
    other test in this session that already holds a reference to the
    original class (`isinstance` checks against the pre-reload class
    would then spuriously fail), for no benefit: the guard logic under
    test does not depend on being the one-and-only loaded copy."""
    import telemetry.ops.heartbeat as heartbeat_module
    import telemetry.ops.membrane_led as canonical_module

    monkeypatch.setattr(
        heartbeat_module,
        "HEARTBEAT_STATES",
        heartbeat_module.HEARTBEAT_STATES + ("bogus-sixth-state",),
    )

    spec = importlib.util.spec_from_file_location(
        "telemetry.ops.membrane_led__import_guard_check",
        canonical_module.__file__,
    )
    fresh_module = importlib.util.module_from_spec(spec)
    with pytest.raises(RuntimeError, match="bogus-sixth-state"):
        spec.loader.exec_module(fresh_module)


def test_colour_table_covers_every_heartbeat_state():
    from telemetry.ops.heartbeat import HEARTBEAT_STATES
    from telemetry.ops.membrane_led import _STATE_TO_COLOUR

    assert set(_STATE_TO_COLOUR) == set(HEARTBEAT_STATES)
    assert {
        STATE_BOOTING,
        STATE_WAITING_FOR_HARDWARE,
        STATE_CAPTURING,
        STATE_DEGRADED,
        STATE_STOPPED_ERROR,
    } == set(HEARTBEAT_STATES)


def test_factory_returns_null_indicator_for_the_default_kind():
    indicator = build_led_indicator(LED_KIND_NULL)
    assert isinstance(indicator, NullLedIndicator)


def test_factory_returns_membrane_indicator_for_the_membrane_kind():
    bus = _RecordingBus()
    indicator = build_led_indicator(LED_KIND_MEMBRANE, bus=bus)
    assert isinstance(indicator, MembraneLedIndicator)
    assert isinstance(indicator, LedIndicator)


def test_factory_falls_back_to_null_and_logs_error_on_construction_failure(caplog):
    class _RaisingBus:
        def write_byte_data(self, *args, **kwargs):
            raise RuntimeError("simulated bus open failure")

    with caplog.at_level("ERROR", logger="telemetry.ops.membrane_led"):
        indicator = build_led_indicator(LED_KIND_MEMBRANE, bus=_RaisingBus())

    assert isinstance(indicator, NullLedIndicator)
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    assert "simulated bus open failure" in error_records[0].message
    assert "MembraneLedIndicator" in error_records[0].message
