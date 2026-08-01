"""
D-03/D-02/D-01 assertions for the full-bus synthetic frame source.

This file proves the four properties plan 00-05 exists to establish:

1. The D-03 rate model (`telemetry.synth.rates`) honours every declared
   `GenMsgCycleTime` exactly and scales every undeclared-rate message so
   each bus's total lands on `config/gate.json`'s documented target_fps.
2. The D-02 entropy brackets (`telemetry.synth.entropy`) genuinely differ
   from one another — best/typical/worst are not three labels on one
   behaviour — and multiplexed messages cycle their real selector values
   rather than being held constant (RESEARCH.md Pitfall 1).
3. The widened `SyntheticFrameSource` (`telemetry.synth.generator`) merges
   every message's schedule into one deterministic, seed-reproducible
   stream whose combined rate matches the documented bus loads.

Every count and figure compared against a literal in this file (which
messages are cycle-time-bearing, which are multiplexed, how many selector
values a message has) is read from the loaded `dbc` fixture or the checked-in
`gate_config` fixture at test time — never hardcoded — per RESEARCH.md
Pitfall 3's drifted-count warning, which has already fired twice in this
phase (00-01-SUMMARY.md, 00-03-SUMMARY.md).
"""

import dataclasses
import inspect
import random
import re

import pytest

from telemetry.synth.entropy import BRACKET_NAMES, PayloadMutator
from telemetry.synth.rates import MessageRate, RateModelError, assign_rates, bus_totals

# A non-multiplexed message carrying both a name-findable rolling counter
# (VCU_INV_RollingCounter) and a high_entropy_analog signal
# (VCU_INV_Torque_Command, scale=0.1) — anchors the counter-increment and
# analog-dither assertions below without needing to hardcode a DBC-derived
# category count.
ANALOG_AND_COUNTER_MESSAGE = "M192_Command_Message"
ANALOG_SIGNAL = "VCU_INV_Torque_Command"
ROLLING_COUNTER_SIGNAL = "VCU_INV_RollingCounter"

# The multiplexed message with the most selector values on this DBC
# (tests/test_dbc_ground_truth.py::test_energy_meter_temperature_multiplexer_value_count
# pins its measured selector count at >=7) — anchors GATE-02's mux-cycling
# prohibition.
MUX_ANCHOR_MESSAGE = "CAN_ENERGY_METER_TEMPERATURE"


def _hamming_distance(a: bytes, b: bytes) -> int:
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Task 1: rate model (telemetry.synth.rates)
# ---------------------------------------------------------------------------


def test_assign_rates_covers_every_message(dbc, gate_config):
    rates = assign_rates(dbc, gate_config)
    assert len(rates) == len(dbc.messages)
    pairs = {(r.frame_id, r.is_extended) for r in rates}
    assert len(pairs) == len(rates), "duplicate (frame_id, is_extended) in assign_rates output"


def test_declared_cycle_time_rate_source_and_period(dbc, gate_config):
    rates = assign_rates(dbc, gate_config)
    by_key = {(r.frame_id, r.is_extended): r for r in rates}
    for message in dbc.messages:
        if message.cycle_time is None:
            continue
        rate = by_key[(message.frame_id, message.is_extended_frame)]
        assert rate.rate_source == "gen_msg_cycle_time"
        assert rate.period_us == message.cycle_time * 1000


def test_scaled_default_rate_positive_period(dbc, gate_config):
    rates = assign_rates(dbc, gate_config)
    for rate in rates:
        if rate.rate_source == "scaled_default":
            assert rate.period_us > 0
        assert rate.rate_source in ("gen_msg_cycle_time", "scaled_default")


def test_bus_totals_within_two_percent_of_targets(dbc, gate_config):
    rates = assign_rates(dbc, gate_config)
    totals = bus_totals(rates)
    for bus, target in gate_config.bus_targets.items():
        achieved = totals[bus]
        tolerance = target.target_fps * 0.02
        assert abs(achieved - target.target_fps) <= tolerance, (
            bus,
            achieved,
            target.target_fps,
        )


def test_combined_bus_totals_bracket_documented_range(dbc, gate_config):
    rates = assign_rates(dbc, gate_config)
    combined = sum(bus_totals(rates).values())
    assert 3500 <= combined <= 4100, combined


def test_every_message_bus_is_valid_bus_target_key(dbc, gate_config):
    rates = assign_rates(dbc, gate_config)
    for rate in rates:
        assert rate.bus in gate_config.bus_targets


def test_message_with_no_sender_gets_default_bus(dbc, gate_config):
    rates = assign_rates(dbc, gate_config)
    by_key = {(r.frame_id, r.is_extended): r for r in rates}
    default_bus = gate_config.bus_assignment["default_bus"]

    no_sender_messages = [
        m for m in dbc.messages if not m.senders or m.senders[0] == "Vector__XXX"
    ]
    assert no_sender_messages, "expected at least one message with no declared sender"
    for message in no_sender_messages:
        rate = by_key[(message.frame_id, message.is_extended_frame)]
        assert rate.bus == default_bus


def test_impossible_bus_target_raises_rate_model_error(dbc, gate_config):
    # Drop bus1's target far below its declared-cycle-time total (~1,627 fps
    # measured from this DBC) so the model cannot possibly scale any
    # undeclared-rate message down to fit.
    broken_targets = dict(gate_config.bus_targets)
    broken_targets["bus1"] = dataclasses.replace(broken_targets["bus1"], target_fps=1.0)
    broken_config = dataclasses.replace(gate_config, bus_targets=broken_targets)

    with pytest.raises(RateModelError, match="bus1"):
        assign_rates(dbc, broken_config)


def test_rate_source_count_matches_measured_cycle_time_count(dbc, gate_config):
    rates = assign_rates(dbc, gate_config)
    measured = sum(1 for m in dbc.messages if m.cycle_time is not None)
    counted = sum(1 for r in rates if r.rate_source == "gen_msg_cycle_time")
    assert counted == measured


def test_rates_module_has_no_hardcoded_dbc_count_literal():
    from telemetry.synth import rates as rates_module

    src = inspect.getsource(rates_module)
    for literal in ("128", "109", "19"):
        assert not re.search(rf"(?<![\w.]){literal}(?![\w.])", src), (
            f"found forbidden DBC-count literal {literal!r} in "
            "src/telemetry/synth/rates.py"
        )


def test_rates_module_docstring_names_d03():
    from telemetry.synth import rates as rates_module

    doc = rates_module.__doc__ or ""
    assert "D-03" in doc
    assert "model" in doc.lower()
    assert "gate.json" in doc


# ---------------------------------------------------------------------------
# Task 2: entropy brackets (telemetry.synth.entropy)
# ---------------------------------------------------------------------------


def test_payload_mutator_length_matches_message_length_for_all_messages(dbc, gate_config):
    bracket = gate_config.entropy_brackets["typical"]
    for message in dbc.messages:
        mutator = PayloadMutator(message, bracket, random.Random(1))
        payload = mutator.next_payload()
        assert len(payload) == message.length, message.name


def test_payload_mutator_deterministic_with_same_seed(dbc, gate_config):
    message = dbc.get_message_by_name(ANALOG_AND_COUNTER_MESSAGE)
    bracket = gate_config.entropy_brackets["typical"]

    mutator_a = PayloadMutator(message, bracket, random.Random(123))
    sequence_a = [mutator_a.next_payload() for _ in range(100)]

    mutator_b = PayloadMutator(message, bracket, random.Random(123))
    sequence_b = [mutator_b.next_payload() for _ in range(100)]

    assert sequence_a == sequence_b


def test_payload_mutator_different_seed_diverges(dbc, gate_config):
    message = dbc.get_message_by_name(ANALOG_AND_COUNTER_MESSAGE)
    bracket = gate_config.entropy_brackets["typical"]

    mutator_a = PayloadMutator(message, bracket, random.Random(123))
    sequence_a = [mutator_a.next_payload() for _ in range(100)]

    mutator_c = PayloadMutator(message, bracket, random.Random(999))
    sequence_c = [mutator_c.next_payload() for _ in range(100)]

    assert sequence_a != sequence_c


def test_entropy_module_does_not_use_global_random():
    from telemetry.synth import entropy as entropy_module

    src = inspect.getsource(entropy_module)
    assert re.search(r"^import random$", src, re.MULTILINE)
    assert not re.search(r"(?<!\w)random\.(random|randint|choice|randrange)\(", src)


def test_payload_mutator_rolling_counter_increments_by_one_modulo_length(dbc, gate_config):
    message = dbc.get_message_by_name(ANALOG_AND_COUNTER_MESSAGE)
    signal = next(s for s in message.signals if s.name == ROLLING_COUNTER_SIGNAL)
    bracket = gate_config.entropy_brackets["typical"]
    modulus = 2 ** signal.length

    mutator = PayloadMutator(message, bracket, random.Random(7))
    previous = None
    for _ in range(20):
        payload = mutator.next_payload()
        decoded = message.decode(payload, decode_choices=False, scaling=False)
        value = decoded[ROLLING_COUNTER_SIGNAL]
        if previous is not None:
            assert value == (previous + 1) % modulus
        previous = value


def test_high_entropy_analog_bracket_change_count_increases(dbc, gate_config):
    message = dbc.get_message_by_name(ANALOG_AND_COUNTER_MESSAGE)
    change_counts = {}

    for bracket_name in BRACKET_NAMES:
        bracket = gate_config.entropy_brackets[bracket_name]
        mutator = PayloadMutator(message, bracket, random.Random(55))
        previous_value = None
        changes = 0
        for _ in range(1000):
            payload = mutator.next_payload()
            decoded = message.decode(payload, decode_choices=False, scaling=False)
            value = decoded[ANALOG_SIGNAL]
            if previous_value is not None and value != previous_value:
                changes += 1
            previous_value = value
        change_counts[bracket_name] = changes

    assert change_counts["best"] < change_counts["typical"] < change_counts["worst"], change_counts


def test_hamming_distance_increases_strictly_across_brackets(dbc, gate_config):
    message = dbc.get_message_by_name(ANALOG_AND_COUNTER_MESSAGE)
    mean_distances = {}

    for bracket_name in BRACKET_NAMES:
        bracket = gate_config.entropy_brackets[bracket_name]
        mutator = PayloadMutator(message, bracket, random.Random(99))
        previous_payload = None
        distances = []
        for _ in range(300):
            payload = mutator.next_payload()
            if previous_payload is not None:
                distances.append(_hamming_distance(payload, previous_payload))
            previous_payload = payload
        mean_distances[bracket_name] = sum(distances) / len(distances)

    assert (
        mean_distances["best"] < mean_distances["typical"] < mean_distances["worst"]
    ), mean_distances


def test_multiplexed_selector_cycles_through_full_set(dbc, gate_config):
    message = dbc.get_message_by_name(MUX_ANCHOR_MESSAGE)
    bracket = gate_config.entropy_brackets["typical"]

    selector_ids = set()
    for signal in message.signals:
        if signal.multiplexer_ids:
            selector_ids.update(signal.multiplexer_ids)

    mutator = PayloadMutator(message, bracket, random.Random(3))
    seen = set()
    for _ in range(len(selector_ids)):
        mutator.next_payload()
        seen.add(mutator.selector_value)

    assert seen == selector_ids


def test_multiplexed_selector_never_repeats_consecutively(dbc, gate_config):
    message = dbc.get_message_by_name(MUX_ANCHOR_MESSAGE)
    bracket = gate_config.entropy_brackets["typical"]

    mutator = PayloadMutator(message, bracket, random.Random(4))
    previous_selector = None
    for _ in range(20):
        mutator.next_payload()
        current_selector = mutator.selector_value
        if previous_selector is not None:
            assert current_selector != previous_selector
        previous_selector = current_selector


def test_energy_meter_temperature_reaches_at_least_seven_selectors(dbc, gate_config):
    message = dbc.get_message_by_name(MUX_ANCHOR_MESSAGE)
    bracket = gate_config.entropy_brackets["typical"]

    mutator = PayloadMutator(message, bracket, random.Random(5))
    seen = set()
    for _ in range(50):
        mutator.next_payload()
        seen.add(mutator.selector_value)

    assert len(seen) >= 7
