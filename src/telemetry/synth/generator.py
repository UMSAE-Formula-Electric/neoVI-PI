"""
telemetry.synth.generator — SyntheticFrameSource, the D-01/D-08 synthetic
frame-source implementation.

Produces a fixed-period stream of `RawFrame`s for one or more DBC messages,
mutated by a seeded `random.Random` instance (D-12: seeded and deterministic,
never the global `random` module — see RESEARCH.md's "Standard Stack" and
Pitfall-adjacent guidance). Mirrors `src/new_logger.py::capture_thread`'s
producer discipline (module docstring: "Zero decoding, zero I/O here") —
this generator only emits `RawFrame` tuples, with no threading or queue
machinery, since the measurement tool drives it directly rather than through
a background thread.

The payload-mutation model implemented here is deliberately one behaviour —
mutate a single random byte about half the time, otherwise repeat the
previous payload verbatim — not the three best/typical/worst entropy
brackets from CONTEXT.md's D-02. Those brackets are plan 00-05's job; this
tracer slice only needs a stream that sometimes repeats (to prove the delta
path actually compresses) and sometimes changes (to prove keyframe-on-change
and gap-safe round-tripping).
"""

import random
from typing import Iterable, Iterator, List, Optional

from telemetry.wire.dictionary import IdDictionary
from telemetry.wire.frame_source import RawFrame

DEFAULT_PERIOD_S = 0.1  # fallback cadence for messages with no GenMsgCycleTime


class SyntheticFrameSource:
    """Implements `telemetry.wire.frame_source.FrameSource`. One instance
    produces one deterministic stream for a given `seed`/`duration_s`
    combination — running the CLI twice with the same seed and duration must
    produce byte-identical output."""

    def __init__(
        self,
        db,
        dictionary: IdDictionary,
        seed: int,
        duration_s: float,
        only_message_names: Optional[Iterable[str]] = None,
    ):
        self.db = db
        self.dictionary = dictionary
        self.seed = seed
        self.duration_s = duration_s
        self.only_message_names = (
            set(only_message_names) if only_message_names else None
        )

    def _select_messages(self) -> List:
        if self.only_message_names is None:
            return list(self.db.messages)
        return [m for m in self.db.messages if m.name in self.only_message_names]

    def frames(self) -> Iterator[RawFrame]:
        rng = random.Random(self.seed)
        messages = self._select_messages()
        duration_us = int(self.duration_s * 1_000_000)

        events = []  # (timestamp_us, message)
        for message in messages:
            period_s = (
                message.cycle_time / 1000.0
                if message.cycle_time
                else DEFAULT_PERIOD_S
            )
            period_us = max(1, int(period_s * 1_000_000))
            t = 0
            while t < duration_us:
                events.append((t, message))
                t += period_us

        # Deterministic ordering across messages sharing a timestamp.
        events.sort(key=lambda e: (e[0], e[1].frame_id))

        last_payload = {}
        for timestamp_us, message in events:
            previous = last_payload.get(message.frame_id)
            payload = self._next_payload(rng, message.length, previous)
            last_payload[message.frame_id] = payload
            yield RawFrame(
                timestamp_us=timestamp_us,
                frame_id=message.frame_id,
                is_extended=message.is_extended_frame,
                payload=bytes(payload),
            )

    @staticmethod
    def _next_payload(rng: random.Random, dlc: int, previous):
        if previous is None:
            return bytearray(rng.randrange(256) for _ in range(dlc))

        mutated = bytearray(previous)
        if dlc and rng.random() < 0.5:
            idx = rng.randrange(dlc)
            mutated[idx] = rng.randrange(256)
        return mutated
