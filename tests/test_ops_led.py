"""
Behaviour-first tests for `telemetry.ops.led` (03-03, OPS-02's physical-
indicator seam). `NullLedIndicator` is the only implementation this plan
ships -- these tests pin that it satisfies `LedIndicator` structurally and
that both of its methods are unconditionally safe to call, including after
`close()`, since a future concrete driver swapped in behind the same
Protocol must never regress either guarantee.
"""

import pytest

from telemetry.ops.heartbeat import HEARTBEAT_STATES
from telemetry.ops.led import LedIndicator, NullLedIndicator


def test_null_led_indicator_satisfies_led_indicator_protocol():
    indicator = NullLedIndicator()
    assert isinstance(indicator, LedIndicator)


@pytest.mark.parametrize("state", HEARTBEAT_STATES)
def test_set_state_accepts_every_heartbeat_state_and_returns_none(state):
    indicator = NullLedIndicator()
    assert indicator.set_state(state) is None


def test_set_state_and_close_are_safe_to_call_repeatedly_and_after_close():
    indicator = NullLedIndicator()
    indicator.set_state("booting")
    indicator.set_state("capturing")
    indicator.close()
    # Safe after close -- a future concrete driver's close() might be
    # terminal, but the no-op default must tolerate calls in any order.
    indicator.set_state("degraded")
    indicator.close()
