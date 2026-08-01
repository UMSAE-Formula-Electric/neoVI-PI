"""
Calibration tests for `telemetry.measure.classify` (D-04).

RESEARCH.md's Assumption A2 records that the structural classification
heuristic in `classify.py` was reasoned out for this specific DBC during
the research session, not sourced from an established CAN-tooling
library. These tests are that heuristic's only calibration: they pin the
classifier's category assignments against the members
`00-01-SUMMARY.md`/`tests/test_dbc_ground_truth.py` verified by hand. If
`classify.py` changes and one of these tests starts failing, the fix is
to re-check the new output by hand against the DBC (as this file's own
authors did) and either confirm the new output is correct or revert the
change -- not to edit the assertion here to match whatever the new code
happens to produce. An assertion in this file that silently tracks the
implementation instead of the hand-verified ground truth defeats the
entire point of a calibration suite.
"""

from telemetry.measure.classify import (
    CATEGORIES,
    category_members,
    classify_database,
)


def test_multiplexed_message_names(dbc):
    classifications = classify_database(dbc)
    actual = {
        mc.name for mc in classifications.values() if "multiplexed" in mc.categories
    }
    expected = {"CAR_ERROR_STATE", "CAN_ENERGY_METER_TEMPERATURE", "M175_Diag_Data_Message"}
    assert actual == expected, (
        f"Expected exactly the three hand-verified multiplexed messages "
        f"{expected}, classifier found {actual}. NOTE: this set is "
        f"'M175_Diag_Data_Message', NOT 'INV_Diag_Buffer' -- RESEARCH.md's "
        f"original DBC Ground Truth table named the wrong message here, "
        f"corrected in 00-01-SUMMARY.md and pinned by "
        f"tests/test_dbc_ground_truth.py::test_multiplexed_message_names. "
        f"A drift in this set means GATE-02's worst-case 'multiplexed' "
        f"bucket no longer matches the bus."
    )


def test_vcu_inv_rolling_counter_classifies_as_rolling_counter(dbc):
    classifications = classify_database(dbc)
    hit = _find_signal(classifications, "VCU_INV_RollingCounter")
    assert hit is not None, "VCU_INV_RollingCounter must exist in the DBC (see test_dbc_ground_truth.py)"
    assert hit.category == "rolling_counter", (
        f"Expected the name-findable signal 'VCU_INV_RollingCounter' to "
        f"classify as rolling_counter, got '{hit.category}' (reason: "
        f"{hit.reason}). This is one of only two name-findable rolling "
        f"counters in the whole DBC -- if the classifier misses it, it "
        f"cannot be trusted on the ~50 counters that are only structurally "
        f"findable."
    )


def test_inv_rolling_counter_classifies_as_rolling_counter(dbc):
    classifications = classify_database(dbc)
    hit = _find_signal(classifications, "INV_Rolling_Counter")
    assert hit is not None, "INV_Rolling_Counter must exist in the DBC (see test_dbc_ground_truth.py)"
    assert hit.category == "rolling_counter", (
        f"Expected the name-findable signal 'INV_Rolling_Counter' to "
        f"classify as rolling_counter, got '{hit.category}' (reason: "
        f"{hit.reason})."
    )


def test_category_members_key_set_equals_categories(dbc):
    members = category_members(classify_database(dbc))
    assert set(members.keys()) == set(CATEGORIES), (
        f"Expected category_members to expose exactly {set(CATEGORIES)}, "
        f"got {set(members.keys())}. A missing key here means a category "
        f"with zero members would be silently omitted from GATE-02's "
        f"report instead of reported as an explicit empty bucket -- "
        f"exactly the repudiation threat (T-00-10) this function exists "
        f"to close."
    )
    for category, bucket in members.items():
        assert isinstance(bucket, list), (
            f"Expected category_members['{category}'] to be a list "
            f"(possibly empty), got {type(bucket)!r}."
        )


def test_checksum_bucket_is_an_explicit_empty_or_named_candidate_set(dbc):
    """
    RESEARCH.md measured exactly 0 name-findable checksum signals in this
    DBC (grep for crc/checksum/chk substrings). That is a name-matching
    result, not a structural one -- D-04 exists precisely because name
    matching finds almost nothing on this bus, so a structural rule is
    *expected* to find candidates a name search cannot.

    Measured here: the structural checksum rule (counter-shaped, byte
    8/16 bits, wholly occupying the message's final byte(s)) is NOT
    empty on this DBC -- it flags several byte-aligned counter-shaped
    signals in a trailing byte position (e.g. heartbeat bytes, fault-code
    words, SOH percentages, a password character). None of these are
    checksums by name, and by inspection none look like real checksums
    either -- this is exactly the false-positive risk RESEARCH.md's
    Pattern 1 flagged for this heuristic (Assumption A2). The bucket is
    therefore reported here as a *named, inspectable candidate set*
    (never silently collapsed to empty and never silently omitted),
    which is what T-00-10's mitigation and the plan's own prohibition
    require -- whether the true count is 0 or not, the bucket and its
    detection method must always be visible.
    """
    members = category_members(classify_database(dbc))
    assert "checksum" in members, "checksum must be a key in category_members even if its list turns out empty"
    checksum_members = members["checksum"]
    assert isinstance(checksum_members, list)
    for msg_class in checksum_members:
        checksum_signals = [sc for sc in msg_class.signals if sc.category == "checksum"]
        assert checksum_signals, (
            f"Message '{msg_class.name}' is in the checksum bucket but has "
            f"no signal classified as checksum -- category_members must "
            f"only include messages that actually carry the category."
        )
        for sc in checksum_signals:
            assert sc.reason, (
                f"checksum classification for '{sc.signal_name}' in "
                f"'{msg_class.name}' has an empty reason -- every "
                f"classification must carry an audit trail."
            )


def test_every_message_classified_exactly_once_with_nonempty_categories(dbc):
    classifications = classify_database(dbc)
    assert len(classifications) == len(dbc.messages), (
        f"Expected classify_database to produce exactly one entry per DBC "
        f"message ({len(dbc.messages)}), got {len(classifications)} -- a "
        f"mismatch means a CAN ID silently fell out of (or was double- "
        f"counted in) the worst-case analysis."
    )
    for key, msg_class in classifications.items():
        assert msg_class.categories, (
            f"Message '{msg_class.name}' (key={key}) has an empty "
            f"categories set -- every message must receive at least one "
            f"category assignment so no CAN ID can silently fall out of "
            f"GATE-02's worst-case analysis."
        )


def test_high_entropy_analog_members_satisfy_shape(dbc):
    classifications = classify_database(dbc)
    members = category_members(classifications)
    high_entropy_members = members["high_entropy_analog"]
    assert high_entropy_members, (
        "Expected at least one high_entropy_analog member -- this DBC has "
        "many sub-unit-scaled analog sensor signals (e.g. 0.1/0.01 scale "
        "temperatures), so an empty bucket here would indicate the shape "
        "rule itself is broken, not that the bus has no analog channels."
    )
    for msg_class in high_entropy_members:
        analog_signals = [sc for sc in msg_class.signals if sc.category == "high_entropy_analog"]
        assert analog_signals, (
            f"Message '{msg_class.name}' is in the high_entropy_analog "
            f"bucket but has no signal classified as such."
        )
        for sc in analog_signals:
            signal = _get_signal_by_name(dbc, msg_class.name, sc.signal_name)
            assert signal.length >= 8 and abs(signal.scale) < 1.0, (
                f"'{sc.signal_name}' in '{msg_class.name}' classified as "
                f"high_entropy_analog but its actual shape (length="
                f"{signal.length}, scale={signal.scale}) does not satisfy "
                f"length>=8 and abs(scale)<1.0 -- the classifier's category "
                f"and the signal's real shape have diverged."
            )


def test_enum_like_signal_does_not_over_fire_as_rolling_counter(dbc):
    """
    Selects its subject by scanning the database for a signal whose
    declared range is NOT the counter shape's power-of-two-minus-one
    (scale=1, offset=0, min=0, max < 2**length - 1) -- e.g. a small enum
    or flag field -- rather than hardcoding a signal name, so this test
    stays valid across DBC revisions. Demonstrates the counter shape does
    not over-fire on enums just because they also happen to have
    scale=1/offset=0/min=0.
    """
    candidate = None
    for message in dbc.messages:
        if message.is_multiplexed():
            continue
        for signal in message.signals:
            if signal.length is None or signal.length <= 0:
                continue
            if signal.scale != 1 or signal.offset != 0:
                continue
            if signal.minimum != 0 or signal.maximum is None:
                continue
            if signal.maximum >= (2 ** signal.length) - 1:
                continue
            normalized = signal.name.lower().replace("_", "")
            if any(t in normalized for t in ("rollingcounter", "alivecounter", "msgcounter", "seqcounter", "crc", "checksum", "chk")):
                continue
            candidate = (message, signal)
            break
        if candidate:
            break

    assert candidate is not None, (
        "Expected to find at least one non-multiplexed enum/flag-shaped "
        "signal (scale=1, offset=0, min=0, max < 2**length-1, no counter-"
        "indicating name) in the DBC to use as the over-fire probe. If "
        "this fails, the DBC no longer contains such a signal and this "
        "test's premise needs re-checking by hand."
    )

    message, signal = candidate
    classifications = classify_database(dbc)
    msg_class = classifications[(message.frame_id, message.is_extended_frame)]
    sc = next(s for s in msg_class.signals if s.signal_name == signal.name)
    assert sc.category != "rolling_counter", (
        f"'{signal.name}' in '{message.name}' has max={signal.maximum} < "
        f"2**{signal.length}-1={2 ** signal.length - 1} -- it is NOT "
        f"counter-shaped, but classified as rolling_counter anyway "
        f"(reason: {sc.reason}). The counter-shape rule is over-firing on "
        f"an enum/flag field."
    )


def _find_signal(classifications, signal_name):
    for msg_class in classifications.values():
        for sc in msg_class.signals:
            if sc.signal_name == signal_name:
                return sc
    return None


def _get_signal_by_name(dbc, message_name, signal_name):
    message = dbc.get_message_by_name(message_name)
    for signal in message.signals:
        if signal.name == signal_name:
            return signal
    raise AssertionError(f"signal '{signal_name}' not found in message '{message_name}'")
