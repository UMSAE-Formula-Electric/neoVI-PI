"""
telemetry.synth.entropy — the D-02 best/typical/worst payload-mutation model.

Payload entropy is exactly the quantity this gate exists to measure, and
synthetic input cannot supply an observation of it — only a model
(RESEARCH.md, `config/gate.json`'s `entropy_brackets._note`). `PayloadMutator`
implements that model: three named brackets whose dither probabilities and
bit counts are checked-in assumptions (`config/gate.json`), applied per
signal according to the structural category `telemetry.measure.classify`
already assigns that signal — never a re-derivation of that classification,
so the entropy model and the report it feeds can never silently disagree
about what a signal *is*.

Every draw comes from the `random.Random` instance the caller constructs
and passes in — this module never touches the global `random` module, so a
seeded generator stays reproducible frame for frame (D-12) and adding one
message to the DBC never shifts another message's payload stream.

Multiplexer cycling (RESEARCH.md Pitfall 1): a multiplexed message's
selector advances round-robin through every declared multiplexer id on each
call, and only the signals active under the current selector (plus every
non-multiplexed signal) are included in the packed payload. Holding a
multiplexed ID's selector constant would flatter its measured bytes/frame —
`CAN_ENERGY_METER_TEMPERATURE` packs 32 temperature signals across 7
selector values, and the real bus pays the cost of every one of them.

Payloads are packed with `message.encode(values, scaling=False,
padding=True, strict=False)` so cantools owns bit ordering, start bits, and
signed/unsigned two's-complement handling — this module only ever produces
raw (unscaled) integer values, each kept within that signal's representable
bit range (`strict=False` disables the *declared* min/max check but cantools
still enforces the bit-width range, confirmed empirically before relying on
it here).
"""

import random
import hashlib
from typing import Dict, List, Optional

from telemetry.measure.classify import classify_message
from telemetry.measure.config import EntropyBracket

BRACKET_NAMES = ("best", "typical", "worst")

_COUNTER_CATEGORIES = ("rolling_counter", "checksum")


def derive_seed(seed: int, frame_id: int, bracket_name: str) -> int:
    """Deterministically derive a per-message, per-bracket seed from the
    config seed, the message's frame_id, and the bracket name — stable
    across interpreter runs (unlike `hash()`, which is salted per-process),
    so adding a message to the DBC never shifts any other message's stream
    and the same `(seed, frame_id, bracket_name)` tuple always yields the
    same derived seed."""
    raw = f"{seed}:{frame_id}:{bracket_name}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big")


def _raw_bounds(signal):
    """The full representable raw-integer range for `signal`'s bit length,
    independent of its declared (physical) minimum/maximum — this is the
    domain `message.encode(..., strict=False)` still enforces even with
    strict-range checking disabled."""
    length = signal.length
    if signal.is_signed:
        return -(2 ** (length - 1)), (2 ** (length - 1)) - 1
    return 0, (2 ** length) - 1


class PayloadMutator:
    """Owns one message's payload evolution under one entropy bracket.
    `next_payload()` returns exactly `message.length` bytes on every call;
    `selector_value` exposes the multiplexer selector the most recent call
    used (`None` for a non-multiplexed message)."""

    def __init__(self, message, bracket: EntropyBracket, rng: random.Random):
        self.message = message
        self.bracket = bracket
        self.rng = rng

        classification = classify_message(message)
        self._category_by_signal: Dict[str, str] = {
            sc.signal_name: sc.category for sc in classification.signals
        }
        self._bounds_by_signal: Dict[str, tuple] = {
            signal.name: _raw_bounds(signal) for signal in message.signals
        }
        self._raw_values: Dict[str, int] = {
            signal.name: self._bounds_by_signal[signal.name][0]
            for signal in message.signals
        }

        self._is_multiplexed = message.is_multiplexed()
        self._selector_values: List[int] = []
        self._selector_index = -1  # advances to index 0 on the first call
        if self._is_multiplexed:
            selector_ids = set()
            for signal in message.signals:
                if signal.multiplexer_ids:
                    selector_ids.update(signal.multiplexer_ids)
            # Defensive fallback for a hypothetical multiplexed message with
            # no declared selector ids — not expected on this DBC (every
            # multiplexed message here declares at least one), but a bare
            # empty list would make selector_value's modulo divide by zero.
            self._selector_values = sorted(selector_ids) if selector_ids else [0]

    @property
    def selector_value(self) -> Optional[int]:
        """The current multiplexer selector, or `None` for a non-multiplexed
        message. Advances only when `next_payload()` is called."""
        if not self._is_multiplexed:
            return None
        return self._selector_values[self._selector_index % len(self._selector_values)]

    def next_payload(self) -> bytes:
        if self._is_multiplexed:
            self._selector_index = (self._selector_index + 1) % len(
                self._selector_values
            )
        current_selector = self.selector_value

        values = {}
        for signal in self.message.signals:
            if self._is_multiplexed and signal.is_multiplexer:
                values[signal.name] = current_selector
                continue
            if (
                self._is_multiplexed
                and signal.multiplexer_ids is not None
                and current_selector not in signal.multiplexer_ids
            ):
                continue  # not active under the current selector
            category = self._category_by_signal[signal.name]
            values[signal.name] = self._mutate_signal(signal, category)

        return self.message.encode(values, scaling=False, padding=True, strict=False)

    def _mutate_signal(self, signal, category: str) -> int:
        name = signal.name
        current = self._raw_values[name]
        raw_min, raw_max = self._bounds_by_signal[name]

        if category in _COUNTER_CATEGORIES and self.bracket.counter_increments:
            modulus = 2 ** signal.length
            new_value = (current + 1) % modulus
            self._raw_values[name] = new_value
            return new_value

        if category == "high_entropy_analog":
            new_value = current
            if self.rng.random() < self.bracket.analog_dither_prob:
                bits = min(self.bracket.analog_dither_bits, signal.length)
                if bits > 0:
                    mask = (1 << bits) - 1
                    noise = self.rng.randrange(0, mask + 1)
                    candidate = (current & ~mask) | noise
                    new_value = max(raw_min, min(raw_max, candidate))
            self._raw_values[name] = new_value
            return new_value

        # Every other signal (including "other" and, for a multiplexed
        # message, every signal collapsed to the "multiplexed" category by
        # the classifier) is re-drawn uniformly with discrete_change_prob.
        new_value = current
        if self.rng.random() < self.bracket.discrete_change_prob:
            new_value = self.rng.randint(raw_min, raw_max)
        self._raw_values[name] = new_value
        return new_value
