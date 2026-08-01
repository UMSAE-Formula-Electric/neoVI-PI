"""
telemetry.synth.generator — SyntheticFrameSource, the D-01/D-08 synthetic
frame-source implementation.

Widened from the tracer's single-behaviour, single-ID form (plan 00-02) to
the full bus: every message in the DBC is emitted at the D-03 rate
`telemetry.synth.rates.assign_rates` assigns it, mutated by a per-message
`telemetry.synth.entropy.PayloadMutator` under one of the three D-02 entropy
brackets. `only_message_names` narrows which messages are actually yielded
without changing any other message's schedule or per-message payload
stream — the rate model and every mutator are always built from the *full*
message set, so a single-ID run and a full-bus run agree on that ID's
timestamps and payloads.

Mirrors `src/new_logger.py::capture_thread`'s producer discipline (module
docstring: "Zero decoding, zero I/O here") — this generator only emits
`RawFrame` tuples, with no threading or queue machinery of any kind, since
the measurement tool drives it directly rather than through a background
thread.
"""

import random
from typing import Iterable, Iterator, List, Optional

from telemetry.measure.config import GateConfig
from telemetry.synth.entropy import PayloadMutator, derive_seed
from telemetry.synth.rates import MessageRate, assign_rates
from telemetry.wire.dictionary import IdDictionary
from telemetry.wire.frame_source import RawFrame


class SyntheticFrameSource:
    """Implements `telemetry.wire.frame_source.FrameSource`. One instance
    produces one deterministic stream for a given `config.seed`/`duration_s`
    combination — running the CLI twice with the same seed and duration must
    produce byte-identical output."""

    def __init__(
        self,
        db,
        dictionary: IdDictionary,
        config: GateConfig,
        bracket_name: str,
        duration_s: Optional[float] = None,
        only_message_names: Optional[Iterable[str]] = None,
    ):
        if bracket_name not in config.entropy_brackets:
            raise ValueError(
                f"bracket_name={bracket_name!r} is not one of "
                f"{sorted(config.entropy_brackets)}"
            )

        self.db = db
        self.dictionary = dictionary
        self.config = config
        self.bracket_name = bracket_name
        self.duration_s = duration_s if duration_s is not None else config.duration_s
        self.only_message_names = (
            set(only_message_names) if only_message_names else None
        )

        # Always computed from the full message set, never from a filtered
        # subset — only_message_names narrows what frames() yields, not what
        # schedule this source is built from (see module docstring).
        self.rates: List[MessageRate] = assign_rates(db, config)

    def _message_by_key(self) -> dict:
        return {(m.frame_id, m.is_extended_frame): m for m in self.db.messages}

    def _selected_rates(self) -> List[MessageRate]:
        if self.only_message_names is None:
            return self.rates
        return [r for r in self.rates if r.name in self.only_message_names]

    def frames(self) -> Iterator[RawFrame]:
        bracket = self.config.entropy_brackets[self.bracket_name]
        duration_us = int(self.duration_s * 1_000_000)
        message_by_key = self._message_by_key()

        mutators = {}
        events = []  # (timestamp_us, frame_id, is_extended)
        for rate in self._selected_rates():
            key = (rate.frame_id, rate.is_extended)
            message = message_by_key[key]
            seed = derive_seed(self.config.seed, rate.frame_id, self.bracket_name)
            mutators[key] = PayloadMutator(message, bracket, random.Random(seed))

            t = 0
            while t < duration_us:
                events.append((t, rate.frame_id, rate.is_extended))
                t += rate.period_us

        # Deterministic ordering across messages sharing a timestamp: by
        # ascending frame_id, then ascending is_extended (False before True).
        events.sort(key=lambda e: (e[0], e[1], e[2]))

        for timestamp_us, frame_id, is_extended in events:
            mutator = mutators[(frame_id, is_extended)]
            payload = mutator.next_payload()
            yield RawFrame(
                timestamp_us=timestamp_us,
                frame_id=frame_id,
                is_extended=is_extended,
                payload=payload,
            )
