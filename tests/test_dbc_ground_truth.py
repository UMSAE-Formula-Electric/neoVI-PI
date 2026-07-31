"""
Executable ground-truth assertions for epbr2026_DBC_v1.0.dbc.

Every count and name set here is read from the loaded database at test time,
never hardcoded as a module-level constant in src/ (RESEARCH.md Pitfall 3
records that the "~21 messages with GenMsgCycleTime" figure already drifted
once from an earlier estimate to a measured 23 — and this test's own
measurement below found the true cantools-visible count to be lower still,
see the module-level note under `test_cycle_time_bearing_message_count`).
If `epbr2026_DBC_v1.0.dbc` ever changes shape, these tests fail loudly
instead of letting a stale assumption propagate into the encoder/measurement
tooling built in later plans.
"""


def test_total_message_count(dbc):
    actual = len(dbc.messages)
    assert actual == 128, (
        f"Expected exactly 128 BO_ messages in epbr2026_DBC_v1.0.dbc, found {actual}. "
        "A changed message count invalidates every downstream bytes/frame figure "
        "this phase's gate depends on."
    )


def test_cycle_time_bearing_message_count(dbc):
    # NOTE (deviation from RESEARCH.md, recorded in 00-01-SUMMARY.md): RESEARCH.md's
    # "DBC Ground Truth" table states 23 messages carry GenMsgCycleTime. That figure
    # was a grep count of every line containing the string "GenMsgCycleTime", which
    # includes the BA_DEF_ and BA_DEF_DEF_ attribute-definition lines (2) alongside
    # the 21 actual per-message BA_ assignments. Of those 21, two assign an explicit
    # value of 0 (BO_ 194, BO_ 193) — the DBC convention (and cantools' own
    # `cycle_time` property) treats 0 as "not periodic", surfacing as None, not 0.
    # The true count of messages with a non-None cycle_time, read from cantools at
    # runtime, is 19. This test asserts the measured truth, not the research prose.
    actual = sum(1 for m in dbc.messages if m.cycle_time is not None)
    assert actual == 19, (
        f"Expected 19 messages with a non-None cycle_time (measured via cantools' "
        f"`message.cycle_time`, which treats an explicit GenMsgCycleTime of 0 as "
        f"non-periodic), found {actual}. This count feeds D-03's rate assignment — "
        "a drift here means the rate-scaling logic in a later plan is working from "
        "a stale population of cycle-time-bearing messages."
    )


def test_multiplexed_message_names(dbc):
    # NOTE (deviation from RESEARCH.md, recorded in 00-01-SUMMARY.md): RESEARCH.md's
    # "DBC Ground Truth" table names the third multiplexed message as `INV_Diag_Buffer`.
    # Measured directly here: `INV_Diag_Buffer` exists in the DBC but
    # `is_multiplexed()` is False for it (none of its 5 signals declare
    # `is_multiplexer`/`multiplexer_ids`). The actual third multiplexed message is
    # `M175_Diag_Data_Message` (6 mux values, 0-5, matching the "diagnostic buffer"
    # shape RESEARCH.md described but attributed to the wrong message name).
    actual = {m.name for m in dbc.messages if m.is_multiplexed()}
    expected = {"CAR_ERROR_STATE", "CAN_ENERGY_METER_TEMPERATURE", "M175_Diag_Data_Message"}
    assert actual == expected, (
        f"Expected the multiplexed message set to be exactly {expected}, "
        f"measured {actual}. GATE-02's worst-case 'multiplexed' bucket is built "
        "directly from this set — a drift here means the classifier in a later "
        "plan silently omits or misclassifies a multiplexed message."
    )


def test_energy_meter_temperature_multiplexer_value_count(dbc):
    msg = dbc.get_message_by_name("CAN_ENERGY_METER_TEMPERATURE")
    mux_values = set()
    for signal in msg.signals:
        if signal.multiplexer_ids:
            mux_values.update(signal.multiplexer_ids)
    assert len(mux_values) >= 7, (
        f"Expected CAN_ENERGY_METER_TEMPERATURE to expose at least 7 distinct "
        f"multiplexer selector values, found {len(mux_values)} ({sorted(mux_values)}). "
        "This message packs the most temperature signals of any multiplexed "
        "message in the DBC and anchors GATE-02's mux-cost measurement."
    )


def test_no_nested_multiplexing(dbc):
    # The A5 probe: RESEARCH.md flagged that the DBC declares
    # `MultiplexExtEnabled = Yes` but that no nested/extended multiplexing was
    # found — checked only by regex, not by loading with cantools. This walks
    # every signal in every message and asserts no signal is simultaneously a
    # multiplexer selector (`is_multiplexer`) AND itself gated by another
    # signal's multiplexer_ids (i.e. multiplexing nested more than one level).
    violations = []
    for message in dbc.messages:
        for signal in message.signals:
            if signal.is_multiplexer and signal.multiplexer_ids is not None:
                violations.append((message.name, signal.name))

    assert not violations, (
        f"Found nested multiplexing in: {violations}. This means "
        "MultiplexExtEnabled = Yes is genuinely in use in this DBC (not just "
        "declared) and the XOR-delta encoding design in a later plan must "
        "account for multi-level multiplexer selectors, not assume a single "
        "flat multiplexer_ids list per signal."
    )


def test_rolling_counter_signals_exist(dbc):
    signal_names = {
        signal.name
        for message in dbc.messages
        for signal in message.signals
    }
    for expected_name in ("VCU_INV_RollingCounter", "INV_Rolling_Counter"):
        assert expected_name in signal_names, (
            f"Expected signal '{expected_name}' to exist somewhere in the DBC "
            "(one of the only two name-findable rolling counters) but it was "
            "not found. GATE-02's worst-case rolling-counter category depends "
            "on these signals existing for the classifier to catch by name as "
            "a positive-signal cross-check."
        )


def test_extended_frame_ids_below_marker_bit(dbc):
    extended_messages = [m for m in dbc.messages if m.is_extended_frame]
    assert extended_messages, (
        "Expected at least one message with is_extended_frame == True "
        "(e.g. the IMU messages or a diagnostic message with a 29-bit ID); "
        "found none. The ID dictionary's extended-ID handling would be "
        "untested against a real example."
    )
    for message in dbc.messages:
        assert message.frame_id < 2**29, (
            f"Message '{message.name}' has frame_id {message.frame_id} which is "
            ">= 2**29 — the extended-ID marker bit (0x80000000) appears not to "
            "have been stripped by cantools for this message. Building the ID "
            "dictionary from this raw value instead of the stripped frame_id "
            "would silently produce wrong/colliding dictionary indices."
        )


def test_frame_id_extended_pair_uniqueness_and_bound(dbc):
    pairs = [(m.frame_id, m.is_extended_frame) for m in dbc.messages]
    unique_pairs = set(pairs)
    assert len(unique_pairs) == len(pairs), (
        f"Expected every (frame_id, is_extended_frame) pair to be unique, but "
        f"found {len(pairs) - len(unique_pairs)} duplicate(s). A duplicate key "
        "would make a one-byte id_index dictionary ambiguous — two distinct "
        "messages would collide on the same dictionary entry."
    )
    assert len(unique_pairs) <= 256, (
        f"Expected at most 256 unique (frame_id, is_extended_frame) pairs so a "
        f"one-byte id_index dictionary (0-255) is provably sufficient, found "
        f"{len(unique_pairs)}. A one-byte id_index would no longer be able to "
        "address every message in this DBC."
    )
