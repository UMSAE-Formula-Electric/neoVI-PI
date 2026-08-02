"""
telemetry.ground.state — `SignalState`, the ground station's live-signal
store (GND-04/GND-05), built on `src/telemetry/capture/fanout.py`'s
counters/threading-discipline shape (`01-PATTERNS.md`).

**Threading discipline (mirrors `fanout.py`'s module docstring):**
`SignalState.update()` is called only from the link-receive/decode thread,
inside `cli.py`'s `on_record` closure — every decoded signal passes through
exactly there, never anywhere else. HTTP handler threads (one per connected
SSE client) only ever call `snapshot()`, which reads a copy under the same
lock `update()` writes under; no handler thread ever mutates `state`
directly. One `threading.Lock` (`self._lock`) guards the single `state`
dict, because unlike `FanOutCounters`' per-field single-writer counters,
this dict is read by a different thread class than the one that writes it —
a torn read here would show a half-written message to the pit (this plan's
own `decode thread -> HTTP handler threads` trust boundary). There is no
second, narrower lock exception to call out here the way `fanout.py` names
`_archive_hwm_lock`: everything in `state` is written and read only through
this one lock.

**Channel derivation (D-09, 02-RESEARCH.md Pattern 5 / Pitfall 2):** the
decoded record carries no `channel` field by design (GND-01's own module
docstring). `build_message_index` resolves `message_name -> (channel,
id_key)` once, at startup, from `assign_rates(db, gate_config)` (which
carries each message's `.bus`) joined against `logger_config.channels`
(which maps `.bus -> .name`) — exactly the derivation
`tests/test_end_to_end.py` already uses and tests. This function must never
run per frame; it is a pure function of the DBC and two already-loaded
config objects.

**`now_ms` is the ground station's own wall clock, never the decoded
record's hardware timestamp** (02-RESEARCH.md Pitfall 1): `frame.timestamp_us`
is a neoVI `TimeSystem` reading scaled by an explicitly-unconfirmed
constant (`TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED`,
`src/telemetry/capture/hardware_source.py`) — it is neither wall-clock nor
synchronised between the car and the pit. `SignalState.update()`'s caller
must always pass `now_ms` derived from the ground station's own clock at
receive time; see that method's docstring for the one-sentence contract.

**No eviction policy is needed** (D-11): `state` is bounded by the DBC's
fixed message set — `build_message_index` enumerates every message in the
DBC exactly once, so `state` can never grow past that count. This is a
structural fix, not a TTL, for the unbounded-growth concern
`.planning/codebase/CONCERNS.md` raised against `can-dashboard/server.js`.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Dict, NamedTuple, Optional

from telemetry.synth.rates import assign_rates

logger = logging.getLogger(__name__)

# The channel a message falls back to when its DBC-assigned bus has no
# entry in `logger_config.channels` -- a signal disappearing from the pit
# view entirely is worse than one shown under an odd label.
UNMAPPED_CHANNEL = "UNMAPPED"


class GroundStateError(Exception):
    """Raised by `build_message_index` when two distinct DBC messages would
    resolve to the same `(channel, id_key)` pair -- the state dict
    physically cannot hold both, and silently keeping one would show wrong
    values in the pit."""


class MessageLocation(NamedTuple):
    """Where one DBC message's signals live in the state dict:
    `state[channel][id_key]`. Computed once at startup by
    `build_message_index`, never per frame."""

    channel: str
    id_key: str


def build_message_index(db, logger_config, gate_config) -> Dict[str, MessageLocation]:
    """Resolve every message in `db` to the `MessageLocation` the locked
    state shape needs but the wire does not carry (D-09,
    02-RESEARCH.md Pattern 5). Reuses the exact derivation
    `tests/test_end_to_end.py` (lines ~792-804) already uses and tests,
    rather than inventing a second one: `assign_rates(db, gate_config)`
    gives each message's `.bus`; `logger_config.channels` maps `.bus ->
    .name`. A message whose bus has no configured channel falls back to
    `UNMAPPED_CHANNEL` rather than being dropped. Raises `GroundStateError`
    naming both message names if two messages would collide on the same
    `(channel, id_key)` pair. Runs once at startup; nothing in it may run
    per frame."""
    name_to_bus = {rate.name: rate.bus for rate in assign_rates(db, gate_config)}
    bus_to_channel = {channel.bus: channel.name for channel in logger_config.channels}

    index: Dict[str, MessageLocation] = {}
    claimed_by: Dict[tuple, str] = {}

    for message in db.messages:
        bus = name_to_bus.get(message.name)
        channel = bus_to_channel.get(bus, UNMAPPED_CHANNEL) if bus is not None else UNMAPPED_CHANNEL
        id_key = f"0x{message.frame_id:X}"
        location = MessageLocation(channel=channel, id_key=id_key)

        collision_key = (location.channel, location.id_key)
        if collision_key in claimed_by:
            raise GroundStateError(
                f"messages {claimed_by[collision_key]!r} and {message.name!r} "
                f"both resolve to state[{location.channel!r}][{location.id_key!r}] "
                f"-- the state dict cannot hold both"
            )
        claimed_by[collision_key] = message.name
        index[message.name] = location

    return index


@dataclass
class SignalStateCounters:
    """Mutable counters for `SignalState` (mirrors `FanOutCounters`' shape).
    Written only by the link-receive/decode thread via `update()` -- no
    lock needed, per this module's single-writer discipline (every write
    happens under `SignalState._lock` alongside the state mutation itself,
    but that lock exists for the state dict's reader/writer thread split,
    not because these counters have multiple writers)."""

    records_applied: int = 0
    records_unmapped_channel: int = 0
    unmapped_log_suppressed_count: int = 0


class SignalState:
    """The ground station's live-signal store: `state[channel][id_key] =
    {"name": message_name, "signals": {signal_name: {"value", "unit",
    "ts"}}}` -- the shape D-09 locks, mirroring `can-dashboard/server.js` so
    the ported dashboard's rendering logic needs no change."""

    def __init__(
        self,
        index: Dict[str, MessageLocation],
        counters: Optional[SignalStateCounters] = None,
    ) -> None:
        self._index = index
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, dict]] = {}
        self.counters = counters if counters is not None else SignalStateCounters()
        self._logged_unmapped_names: set = set()

    def update(self, *, message_name: str, signal: str, value, unit, now_ms: int) -> dict:
        """Apply one decoded signal to the state store under `self._lock`
        and return the broadcast payload (`type="update"` plus `channel`,
        `id`, `name`, `signal`, `value`, `unit`, `ts`) for the caller to
        hand to `SseHub.broadcast()`.

        `now_ms` MUST be the ground station's own wall clock in epoch
        milliseconds (e.g. `int(time.time() * 1000)`), taken at the moment
        this update fires -- it MUST NOT be derived from the decoded
        record's `timestamp_us` field, which is a neoVI `TimeSystem`
        reading scaled by an explicitly-unconfirmed constant and is neither
        wall-clock nor synchronised between the car and the ground station.

        An unknown `message_name` (not present in the index this
        `SignalState` was built with) is stored under `UNMAPPED_CHANNEL`
        rather than dropped -- a signal disappearing from the pit view is
        worse than an oddly-labelled one -- and counted on
        `SignalStateCounters.records_unmapped_channel`, logged once per
        message name with further occurrences counted, not re-logged."""
        location = self._index.get(message_name)
        if location is None:
            self.counters.records_unmapped_channel += 1
            if message_name in self._logged_unmapped_names:
                self.counters.unmapped_log_suppressed_count += 1
            else:
                self._logged_unmapped_names.add(message_name)
                logger.warning(
                    "signal state has no known channel/id for message_name=%r "
                    "-- storing under channel=%r; further occurrences of this "
                    "message name are counted, not re-logged",
                    message_name,
                    UNMAPPED_CHANNEL,
                )
            channel = UNMAPPED_CHANNEL
            id_key = message_name
        else:
            channel = location.channel
            id_key = location.id_key

        with self._lock:
            channel_state = self._state.setdefault(channel, {})
            message_state = channel_state.setdefault(id_key, {"name": message_name, "signals": {}})
            message_state["name"] = message_name
            message_state["signals"][signal] = {
                "value": value,
                "unit": unit or "",
                "ts": now_ms,
            }
            self.counters.records_applied += 1

        return {
            "type": "update",
            "channel": channel,
            "id": id_key,
            "name": message_name,
            "signal": signal,
            "value": value,
            "unit": unit or "",
            "ts": now_ms,
        }

    def snapshot(self) -> dict:
        """Return a rebuilt nested copy of the whole state dict (new dicts
        at channel, message, and signal level) under `self._lock`, so an
        HTTP handler thread can serialise it while the decode thread keeps
        writing. `state` is bounded by the DBC's fixed message set (D-11)
        and needs no eviction policy -- see this module's docstring."""
        with self._lock:
            return {
                channel: {
                    id_key: {
                        "name": message_state["name"],
                        "signals": {
                            signal_name: dict(signal_value)
                            for signal_name, signal_value in message_state["signals"].items()
                        },
                    }
                    for id_key, message_state in channel_state.items()
                }
                for channel, channel_state in self._state.items()
            }
