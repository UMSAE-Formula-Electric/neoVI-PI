"""
telemetry.synth.rates — the D-03 rate model.

Every message that declares a `GenMsgCycleTime` (cantools: `message.cycle_time`
not `None`) is emitted at exactly that period. Every other message has no
measured rate at all — RESEARCH.md's ground truth (re-verified in
`tests/test_dbc_ground_truth.py`, whose measured cycle-time-bearing and
undeclared-message counts are the authority for this DBC, not a copy pasted
here) is that only a minority of this DBC's messages carry a declared cycle
time; the remainder get a seed period from `config/gate.json`'s
`default_period_ms_by_ecu.seed_period_ms_by_ecu`, scaled per bus at runtime
so each bus's combined declared + scaled-default total lands on
`config/gate.json`'s `bus_targets.<bus>.target_fps`.

Both `bus_assignment` (which ECU rides which physical bus) and
`default_period_ms_by_ecu` (the seed periods for undeclared-rate messages)
are MODELLED inputs read verbatim from `config/gate.json` — see that file's
own `_note`/`confirmed` fields — never properties the DBC itself states.
Nothing in `epbr2026_DBC_v1.0.dbc` names a bus per message, and nothing in
it states a rate for the undeclared messages; this module's whole job is
applying the checked-in model, not inventing one.

No count read from the DBC (total message count, cycle-time-bearing count,
undeclared count, sender/node count) is ever hardcoded here — every one of
those figures is read from `db.messages` / `GateConfig` at call time, per
RESEARCH.md Pitfall 3's drifted-count warning.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from telemetry.measure.config import GateConfig

# The DBC's placeholder for "no declared sender" — cantools passes this
# through from the BO_ line's transmitter field verbatim rather than
# collapsing it to an empty senders list.
_VECTOR_PLACEHOLDER_SENDER = "Vector__XXX"

# The fallback key inside `default_period_ms_by_ecu.seed_period_ms_by_ecu`
# for a message with no declared (or unmapped) sender.
NO_SENDER_KEY = "NO_SENDER"


class RateModelError(Exception):
    """Raised when a bus's declared-cycle-time messages alone already meet
    or exceed that bus's `target_fps` — the model would have to shrink or
    silently drop a scaled-default message to make the arithmetic work,
    which this module refuses to do (T-00-21)."""


@dataclass(frozen=True)
class MessageRate:
    """One message's assigned emission rate. `rate_source` is either
    `"gen_msg_cycle_time"` (the DBC declared this rate) or
    `"scaled_default"` (this module assigned it to hit the bus's documented
    load) — a report reading this field can always tell measured from
    modelled, which is exactly what a reader of this gate's numbers needs
    to be able to do."""

    frame_id: int
    is_extended: bool
    name: str
    sender: Optional[str]
    bus: str
    period_us: int
    rate_hz: float
    rate_source: str  # "gen_msg_cycle_time" | "scaled_default"


def _resolve_sender(message) -> Optional[str]:
    """The message's first declared sender, or `None` for an empty sender
    list or the DBC's `Vector__XXX` placeholder — both mean "no declared
    sender" for the purposes of bus assignment and seed-period lookup."""
    senders = message.senders
    if not senders:
        return None
    sender = senders[0]
    if sender == _VECTOR_PLACEHOLDER_SENDER:
        return None
    return sender


def _resolve_bus(sender: Optional[str], config: GateConfig) -> str:
    """`bus_assignment.by_ecu[sender]`, falling back to
    `bus_assignment.default_bus` for a message with no declared sender or a
    sender not present in the by_ecu map."""
    by_ecu = config.bus_assignment.get("by_ecu", {})
    default_bus = config.bus_assignment.get("default_bus")
    if sender is not None and sender in by_ecu:
        return by_ecu[sender]
    return default_bus


def _seed_period_ms(sender: Optional[str], config: GateConfig) -> float:
    """The seed period (milliseconds) for a message with no declared cycle
    time, read from `default_period_ms_by_ecu.seed_period_ms_by_ecu`. Falls
    back to the `NO_SENDER` entry for a message with no declared sender or a
    sender the map does not cover."""
    seed_map = config.default_period_ms_by_ecu.get("seed_period_ms_by_ecu", {})
    key = sender if sender is not None and sender in seed_map else NO_SENDER_KEY
    return float(seed_map[key])


def assign_rates(db, config: GateConfig) -> List[MessageRate]:
    """Assign every message in `db` a `MessageRate`, per the D-03 algorithm:

    1. Resolve each message's bus from its sender via `bus_assignment`.
    2. A message with a declared `cycle_time` gets `period_us = cycle_time
       * 1000` and `rate_source = "gen_msg_cycle_time"`.
    3. Every other message gets a seed period from
       `default_period_ms_by_ecu.seed_period_ms_by_ecu`.
    4. Per bus, solve one scale factor so declared_fps + scaled_seed_fps ==
       bus_targets[bus].target_fps, and apply it to every step-3 message's
       period on that bus.
    5. A bus whose declared total alone already meets or exceeds its target
       raises `RateModelError` naming the bus, the declared total, and the
       target — never clamped, never silently dropped.
    """
    declared_records = []
    undeclared_records = []

    for message in db.messages:
        sender = _resolve_sender(message)
        bus = _resolve_bus(sender, config)
        record = {"message": message, "sender": sender, "bus": bus}
        if message.cycle_time is not None:
            record["period_us"] = message.cycle_time * 1000
            declared_records.append(record)
        else:
            record["seed_period_ms"] = _seed_period_ms(sender, config)
            undeclared_records.append(record)

    declared_fps_by_bus: Dict[str, float] = {bus: 0.0 for bus in config.bus_targets}
    for record in declared_records:
        declared_fps_by_bus[record["bus"]] += 1_000_000.0 / record["period_us"]

    seed_fps_by_bus: Dict[str, float] = {bus: 0.0 for bus in config.bus_targets}
    for record in undeclared_records:
        seed_fps_by_bus[record["bus"]] += 1000.0 / record["seed_period_ms"]

    scale_by_bus: Dict[str, float] = {}
    for bus, target in config.bus_targets.items():
        target_fps = target.target_fps
        declared_fps = declared_fps_by_bus.get(bus, 0.0)
        remaining_fps = target_fps - declared_fps
        if remaining_fps <= 0:
            raise RateModelError(
                f"bus {bus!r}: declared-cycle-time messages alone total "
                f"{declared_fps:.4f} fps, which already meets or exceeds "
                f"the documented target_fps of {target_fps!r} — cannot "
                f"scale any undeclared-rate message down to fit without "
                f"silently dropping or clamping a message"
            )
        seed_fps = seed_fps_by_bus.get(bus, 0.0)
        # A bus with no undeclared-rate messages has nothing to scale; the
        # factor is unused in that case (the loop below never reads it).
        scale_by_bus[bus] = (remaining_fps / seed_fps) if seed_fps > 0 else 1.0

    rates: List[MessageRate] = []

    for record in declared_records:
        message = record["message"]
        period_us = record["period_us"]
        rates.append(
            MessageRate(
                frame_id=message.frame_id,
                is_extended=message.is_extended_frame,
                name=message.name,
                sender=record["sender"],
                bus=record["bus"],
                period_us=period_us,
                rate_hz=1_000_000.0 / period_us,
                rate_source="gen_msg_cycle_time",
            )
        )

    for record in undeclared_records:
        message = record["message"]
        bus = record["bus"]
        seed_period_us = record["seed_period_ms"] * 1000.0
        scale = scale_by_bus[bus]
        scaled_period_us = seed_period_us / scale
        period_us = max(1, round(scaled_period_us))
        rates.append(
            MessageRate(
                frame_id=message.frame_id,
                is_extended=message.is_extended_frame,
                name=message.name,
                sender=record["sender"],
                bus=bus,
                period_us=period_us,
                rate_hz=1_000_000.0 / period_us,
                rate_source="scaled_default",
            )
        )

    return rates


def bus_totals(rates: List[MessageRate]) -> Dict[str, float]:
    """Sum `rate_hz` per bus across `rates` — the achieved frames/s per bus
    this rate assignment actually produces, for comparison against
    `bus_targets.<bus>.target_fps`."""
    totals: Dict[str, float] = {}
    for rate in rates:
        totals[rate.bus] = totals.get(rate.bus, 0.0) + rate.rate_hz
    return totals
