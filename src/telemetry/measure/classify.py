"""
telemetry.measure.classify — D-04 structural signal/message classifier and
standalone audit CLI.

RESEARCH.md measured exactly 2 name-findable rolling counters and 0
name-findable checksums against 128 messages, so a name-only classifier
would silently under-report the categories GATE-02 requires broken out.
This module classifies every message structurally instead: bit width, bit
position, scale, offset, declared range, and cantools multiplex structure
decide the category, and a name match is only ever a *positive override*
on top of that -- never the sole detector. Every classification carries a
`reason` string naming the rule that fired and the values that triggered
it, because RESEARCH.md flags this heuristic as Assumption A2 (reasoned
out against this specific DBC, not sourced from an established
CAN-tooling library) -- the reason string is the audit trail that lets a
human overrule it.

Run standalone: `python -m telemetry.measure.classify --dbc <path>`.

Phase-0-only offline analysis tooling. Reads DBC structure only -- does
not import `telemetry.wire` or `telemetry.synth`.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import cantools

DBC_FILENAME = "epbr2026_DBC_v1.0.dbc"
# Repo-root-relative default, mirroring telemetry.measure.cli's convention:
# classify.py -> measure/ -> telemetry/ -> src/ -> repo root.
DEFAULT_DBC_PATH = str(Path(__file__).resolve().parents[3] / DBC_FILENAME)

CATEGORIES = ("rolling_counter", "checksum", "multiplexed", "high_entropy_analog", "other")

# Name substrings are checked case-insensitively against the signal name
# with underscores removed, so "VCU_INV_RollingCounter" and
# "INV_Rolling_Counter" both match "rollingcounter".
_CHECKSUM_NAME_TOKENS = ("crc", "checksum", "chk")
_ROLLING_COUNTER_NAME_TOKENS = ("rollingcounter", "alivecounter", "msgcounter", "seqcounter")

_CATEGORY_DETECTION_METHODS = {
    "rolling_counter": (
        "structural counter shape (scale=1, offset=0, length<=8, min=0, "
        "max=2**length-1) plus a rollingcounter/alivecounter/msgcounter/"
        "seqcounter name-substring override"
    ),
    "checksum": (
        "structural counter shape confined to the final byte(s) of the "
        "message (length 8 or 16, byte-aligned) plus a crc/checksum/chk "
        "name-substring override"
    ),
    "multiplexed": "cantools message.is_multiplexed()",
    "high_entropy_analog": (
        "length>=8 bits and abs(scale)<1.0 in a non-multiplexed message"
    ),
    "other": "fallback -- no structural or name rule matched",
}


def log(*args, **kwargs):
    print("[LOG]", *args, **kwargs, file=sys.stderr)


@dataclass(frozen=True)
class SignalClassification:
    signal_name: str
    message_name: str
    frame_id: int
    is_extended: bool
    category: str
    reason: str


@dataclass(frozen=True)
class MessageClassification:
    frame_id: int
    is_extended: bool
    name: str
    categories: frozenset
    signals: tuple


def _flat_start_bit(signal) -> int:
    """Return the bit position of `signal`'s LSB in a flat numbering that
    starts at 0 for the LSB of byte 0 and increases monotonically through
    the message, regardless of the signal's declared byte order.

    cantools stores `signal.start` differently depending on `byte_order`:
    for little_endian (Intel) it is already this flat LSB position; for
    big_endian (Motorola) it is expressed in the DBC's sawtooth
    bit-numbering. Empirically verified against this DBC's big_endian
    signals (e.g. Team_Data_2_Message, CAN_ENERGY_METER_TEMPERATURE) by
    encoding known values and observing which raw bytes changed: the
    translation `8 * (start // 8) + (7 - start % 8)` produces a flat start
    bit from which the occupied range is `[flat_start, flat_start +
    length - 1]` for BOTH byte orders.
    """
    if signal.byte_order == "big_endian":
        return 8 * (signal.start // 8) + (7 - (signal.start % 8))
    return signal.start


def _in_final_bytes(signal, message) -> bool:
    """True if `signal` is byte-aligned and its occupied bytes are exactly
    the trailing byte(s) of `message` -- the structural checksum position."""
    if signal.length not in (8, 16):
        return False
    flat_start = _flat_start_bit(signal)
    if flat_start % 8 != 0:
        return False
    start_byte = flat_start // 8
    num_bytes = signal.length // 8
    end_byte = start_byte + num_bytes - 1
    return end_byte == message.length - 1


def _is_counter_shaped(signal) -> bool:
    """Structural counter shape: scale=1, offset=0, min=0, max=2**length-1.

    Guards every optional cantools attribute against None (T-00-09) so a
    signal with missing range metadata falls through to `other` with a
    reason naming the missing attribute, instead of raising `TypeError` on
    a `None` comparison.
    """
    length = signal.length
    if length is None or length <= 0:
        return False
    if signal.scale is None or signal.offset is None:
        return False
    if signal.scale != 1 or signal.offset != 0:
        return False
    minimum = signal.minimum
    maximum = signal.maximum
    if minimum is None or maximum is None:
        return False
    return minimum == 0 and maximum == (2 ** length) - 1


def classify_signal(signal, message) -> tuple:
    """Classify one signal, first match wins:

    1. multiplexed  -- message.is_multiplexed() is True.
    2. checksum     -- counter shape confined to the final byte(s), length
                       8 or 16, OR a crc/checksum/chk name override.
    3. rolling_counter -- counter shape with length<=8, OR a
                       rollingcounter/alivecounter/msgcounter/seqcounter
                       name override.
    4. high_entropy_analog -- length>=8 and abs(scale)<1.0, non-multiplexed.
    5. other        -- everything else.

    Returns (category, reason); `reason` is always a non-empty string
    naming the rule and the values that triggered it.
    """
    if message.is_multiplexed():
        return "multiplexed", (
            f"message '{message.name}' reports is_multiplexed()=True via "
            f"cantools; every signal in a multiplexed message inherits "
            f"this category regardless of its own shape"
        )

    normalized_name = signal.name.lower().replace("_", "")
    counter_shape = _is_counter_shaped(signal)

    checksum_token = next((t for t in _CHECKSUM_NAME_TOKENS if t in normalized_name), None)
    if checksum_token:
        return "checksum", (
            f"name override: '{signal.name}' contains checksum-indicating "
            f"substring '{checksum_token}' (name match promotes regardless "
            f"of bit shape)"
        )
    if counter_shape and signal.length in (8, 16) and _in_final_bytes(signal, message):
        return "checksum", (
            f"structural: counter-shaped signal (scale={signal.scale}, "
            f"offset={signal.offset}, min={signal.minimum}, "
            f"max={signal.maximum}) of length {signal.length} bits wholly "
            f"occupies the final byte(s) of the {message.length}-byte "
            f"message '{message.name}'"
        )

    rolling_token = next(
        (t for t in _ROLLING_COUNTER_NAME_TOKENS if t in normalized_name), None
    )
    if rolling_token:
        return "rolling_counter", (
            f"name override: '{signal.name}' contains rolling-counter-"
            f"indicating substring '{rolling_token}' (name match promotes "
            f"regardless of bit shape)"
        )
    if counter_shape and signal.length <= 8:
        return "rolling_counter", (
            f"structural: counter shape -- scale={signal.scale}, "
            f"offset={signal.offset}, length={signal.length}<=8, "
            f"min={signal.minimum}, max={signal.maximum}==2**"
            f"{signal.length}-1"
        )

    if (
        signal.length is not None
        and signal.length >= 8
        and signal.scale is not None
        and abs(signal.scale) < 1.0
    ):
        return "high_entropy_analog", (
            f"structural: length={signal.length}>=8 bits and "
            f"abs(scale)={abs(signal.scale)}<1.0 in non-multiplexed "
            f"message '{message.name}' -- sub-unit scaling suggests analog "
            f"precision whose low bits are expected to dither"
        )

    return "other", (
        f"no structural or name rule matched: length={signal.length}, "
        f"scale={signal.scale}, offset={signal.offset}, "
        f"min={signal.minimum}, max={signal.maximum}"
    )


def classify_message(message) -> MessageClassification:
    """Classify every signal in `message`, then roll the signals' own
    categories up into the message's `categories` set. A multiplexed
    message's signals are all short-circuited to `multiplexed` by
    `classify_signal`, so the union naturally reduces to `{"multiplexed"}`;
    the explicit union-with-multiplexed below is a defensive backstop for
    a hypothetical zero-signal multiplexed message, not the common path.
    Every message ends with a non-empty `categories` set -- a message
    whose signals all classify as `other` carries `{"other"}`.
    """
    signal_classifications = []
    for signal in message.signals:
        category, reason = classify_signal(signal, message)
        signal_classifications.append(
            SignalClassification(
                signal_name=signal.name,
                message_name=message.name,
                frame_id=message.frame_id,
                is_extended=message.is_extended_frame,
                category=category,
                reason=reason,
            )
        )
    signal_classifications = tuple(signal_classifications)

    if signal_classifications:
        categories = frozenset(sc.category for sc in signal_classifications)
    else:
        categories = frozenset({"other"})

    if message.is_multiplexed():
        categories = categories | frozenset({"multiplexed"})

    return MessageClassification(
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        name=message.name,
        categories=categories,
        signals=signal_classifications,
    )


def classify_database(db) -> dict:
    """Classify every message in `db`, keyed on `(frame_id, is_extended)`
    so a standard-ID and extended-ID message sharing a numeric ID never
    collide -- mirrors the `(frame_id, is_extended_frame)` key shape
    `tests/test_dbc_ground_truth.py::test_frame_id_extended_pair_uniqueness_and_bound`
    already proved unique and bounded for this DBC."""
    return {
        (message.frame_id, message.is_extended_frame): classify_message(message)
        for message in db.messages
    }


def category_members(classifications) -> dict:
    """Roll a `classify_database(db)` mapping up into `{category: [MessageClassification, ...]}`.

    Every key in `CATEGORIES` is present with a list, even if empty --
    this is what makes "no checksums on this bus" (an empty list)
    distinguishable from "the classifier never looked" (a missing key).
    """
    members = {category: [] for category in CATEGORIES}
    values = classifications.values() if hasattr(classifications, "values") else classifications
    for msg_class in values:
        for category in msg_class.categories:
            members[category].append(msg_class)
    return members


def _representative_reason(msg_class: MessageClassification) -> str:
    """The reason for the first non-`other` signal assignment in the
    message, or the first signal's reason if every signal classified as
    `other`."""
    for sc in msg_class.signals:
        if sc.category != "other":
            return sc.reason
    if msg_class.signals:
        return msg_class.signals[0].reason
    return "message has no signals"


def _print_row(msg_class: MessageClassification) -> None:
    ext_flag = "EXT" if msg_class.is_extended else "STD"
    categories = ", ".join(sorted(msg_class.categories))
    reason = _representative_reason(msg_class)
    print(
        f"0x{msg_class.frame_id:X}  {ext_flag}  {msg_class.name:<40}  "
        f"categories=[{categories}]  reason={reason}"
    )


def _print_summary(classifications: dict) -> None:
    members = category_members(classifications)
    print()
    print("Category summary:")
    for category in CATEGORIES:
        count = len(members[category])
        if count == 0:
            print(
                f"  {category}: 0 members "
                f"(detection method: {_CATEGORY_DETECTION_METHODS[category]}) "
                f"-- explicit empty bucket, not an omission"
            )
        else:
            print(f"  {category}: {count} members")


def main():
    p = argparse.ArgumentParser(
        description=(
            "D-04 structural CAN signal/message classifier -- prints every "
            "message's worst-case category assignment with the reason it "
            "was assigned, so the classification can be audited without "
            "reading source."
        )
    )
    p.add_argument(
        "--dbc",
        default=DEFAULT_DBC_PATH,
        help="Path to the .dbc file (default: repo-root epbr2026_DBC_v1.0.dbc).",
    )
    p.add_argument(
        "--category",
        action="append",
        default=None,
        dest="category",
        choices=CATEGORIES,
        help="Restrict printed rows to messages carrying this category (repeatable).",
    )
    args = p.parse_args()

    log(f"Loading DBC: {args.dbc}")
    db = cantools.database.load_file(args.dbc)
    log(f"Loaded DBC: {args.dbc} ({len(db.messages)} messages)")

    classifications = classify_database(db)
    log(f"Classified {len(classifications)} messages")

    category_filter = set(args.category) if args.category else None

    rows_printed = 0
    for _key, msg_class in sorted(classifications.items()):
        if category_filter is not None and not (msg_class.categories & category_filter):
            continue
        rows_printed += 1
        _print_row(msg_class)

    if category_filter:
        log(f"Printed {rows_printed} message rows filtered to {sorted(category_filter)}")
    else:
        log(f"Printed {rows_printed} message rows")

    _print_summary(classifications)


if __name__ == "__main__":
    main()
