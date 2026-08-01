"""
Requirements covered: LINK-03, LINK-04.

One shared test suite, parameterised over both `Link` implementations
(`LoopbackLink`, `UdpLink`), so LINK-03's "no change to the layers above" is
demonstrated by the same assertions passing against both — not by two
separate test files that could quietly diverge. Every test in this file
uses only the loopback network interface and no vehicle hardware, no radio,
and no second machine (LINK-04).
"""

import time

import pytest

from telemetry.framing.cobs_frame import frame as cobs_frame
from telemetry.ground.deframe import Deframer
from telemetry.link.loopback import LoopbackLink
from telemetry.link.udp import UdpLink
from telemetry.wire.batcher import pack_batch
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import Encoder
from telemetry.wire.frame_source import RawFrame

SUBJECT_MESSAGE = "M195_Pedal_Press_Percent"
SUBJECT_SIGNAL_VALUES = {"Pedal_Press_Percent": 42}

LOOPBACK_HOST = "127.0.0.1"


@pytest.fixture
def dictionary(dbc, logger_config):
    return build_id_dictionary(dbc, logger_config.dbc_path)


def _new_udp_pair(recv_bufsize=8192):
    """A bound receiver on an OS-assigned ephemeral port, plus a sender
    pointed at the receiver's real bound address (discovered via
    `local_addr`, never a hardcoded port)."""
    recv_link = UdpLink(local_addr=(LOOPBACK_HOST, 0), recv_bufsize=recv_bufsize)
    send_link = UdpLink(local_addr=(LOOPBACK_HOST, 0), remote_addr=recv_link.local_addr)
    return send_link, recv_link


@pytest.fixture(params=["loopback", "udp"])
def link_pair(request):
    """Yields `(sender, receiver)` -- two ends of the same `Link`
    connection, for whichever implementation this parametrization selects.
    For `LoopbackLink` sender and receiver are the same object (one
    internal queue); for `UdpLink` they are two independently bound
    sockets. Both satisfy the same three-method `Link` Protocol, so every
    test using this fixture runs unchanged against either."""
    if request.param == "loopback":
        link = LoopbackLink()
        yield link, link
        link.close()
    else:
        send_link, recv_link = _new_udp_pair()
        yield send_link, recv_link
        send_link.close()
        recv_link.close()


def _build_one_record_batch(dictionary, db, batch_seq=0):
    message = db.get_message_by_name(SUBJECT_MESSAGE)
    payload = message.encode(SUBJECT_SIGNAL_VALUES)
    encoder = Encoder(dictionary)
    raw = RawFrame(
        timestamp_us=1000,
        frame_id=message.frame_id,
        is_extended=message.is_extended_frame,
        payload=payload,
    )
    cfr = encoder.encode(raw, batch_base_timestamp_us=1000)
    batch_payload = pack_batch(
        dict_version=dictionary.dict_version,
        base_timestamp_us=1000,
        batch_seq=batch_seq,
        records=[cfr],
    )
    return batch_payload, message, payload


# ---------------------------------------------------------------------------
# Shared behaviour: the same assertions, run against both implementations
# ---------------------------------------------------------------------------


def test_payload_sent_is_received_byte_identical(link_pair):
    sender, receiver = link_pair
    payload = b"\x01\x02\xffhello world\xfe\x00" + bytes(range(256))
    sender.send(payload)
    received = receiver.recv(timeout=2.0)
    assert received == payload


def test_recv_with_timeout_and_nothing_to_receive_returns_none_not_raise_or_block(link_pair):
    _sender, receiver = link_pair
    started = time.perf_counter()
    result = receiver.recv(timeout=0.2)
    elapsed = time.perf_counter() - started

    assert result is None
    assert elapsed < 5.0, "recv(timeout=...) must return promptly, never block indefinitely"


def test_close_is_idempotent_and_send_after_close_raises(link_pair):
    sender, _receiver = link_pair
    sender.close()
    sender.close()  # idempotent -- must not raise

    with pytest.raises(RuntimeError):
        sender.send(b"\x01")


def _run_full_chain(dictionary, db, sender, receiver):
    """The 01-04 tracer's own chain -- encode, batch, frame, send, receive,
    deframe, decode -- run against whichever `sender`/`receiver` pair is
    passed in."""
    batch_payload, message, payload = _build_one_record_batch(dictionary, db)
    framed = cobs_frame(batch_payload)

    sender.send(framed)
    received = receiver.recv(timeout=2.0)
    assert received is not None, "the link must deliver what was sent on an idle, uncontested loopback interface"

    deframer = Deframer(dictionary)
    recovered_batches = list(deframer.feed(received))
    assert len(recovered_batches) == 1
    return recovered_batches[0], message, payload


def test_full_chain_produces_identical_decoded_frames_over_both_links(dictionary, dbc):
    """LINK-03's actual claim: the identical encode-to-decode chain run over
    `LoopbackLink` and over `UdpLink` produces the same result, compared to
    each other -- not just each compared to a literal."""
    loopback = LoopbackLink()
    try:
        loopback_frames, message, payload = _run_full_chain(dictionary, dbc, loopback, loopback)
    finally:
        loopback.close()

    send_link, recv_link = _new_udp_pair()
    try:
        udp_frames, udp_message, udp_payload = _run_full_chain(dictionary, dbc, send_link, recv_link)
    finally:
        send_link.close()
        recv_link.close()

    assert message is udp_message
    assert payload == udp_payload
    assert len(loopback_frames) == 1
    assert loopback_frames == udp_frames


# ---------------------------------------------------------------------------
# UDP-specific
# ---------------------------------------------------------------------------


def test_udp_bound_address_is_discoverable_without_hardcoding_a_port():
    link = UdpLink(local_addr=(LOOPBACK_HOST, 0))
    try:
        host, port = link.local_addr
        assert host in (LOOPBACK_HOST, "0.0.0.0")  # platform-dependent loopback representation
        assert port != 0, "an ephemeral bind (port 0) must resolve to a real, discoverable port"
    finally:
        link.close()


def test_oversized_datagram_is_truncated_counted_corrupt_never_reaches_the_decoder(dictionary, dbc):
    """`recv_bufsize` is deliberately generous in the shipped config, never
    tight. `socket.recvfrom(bufsize)`'s behavior on an oversized datagram is
    platform-dependent, verified directly this session (01-08) rather than
    assumed from `01-RESEARCH.md`'s POSIX-only citation:

    - **POSIX (the deployment target, Linux/CM4):** silently truncates,
      raising nothing. The truncated bytes fail CRC once fed to the
      `Deframer` and are discarded and counted like any other corruption.
    - **Winsock (the dev box, per `01-CONTEXT.md`'s Windows dev-interpreter
      decision):** raises `WSAEMSGSIZE` instead of truncating, and
      `UdpLink.recv` catches it and returns `None` — the oversized
      datagram is dropped by the OS before any bytes ever reach this
      process, so nothing is buffered and nothing needs discarding.

    Either branch is a legitimate, contained outcome — this test proves the
    failure mode is *contained* on whichever platform it actually runs on,
    not that one specific platform's exact byte-for-byte truncation
    behavior is universal."""
    small_bufsize = 40  # smaller than the oversized batch below, larger than the follow-up
    send_link, recv_link = _new_udp_pair(recv_bufsize=small_bufsize)
    try:
        message = dbc.get_message_by_name(SUBJECT_MESSAGE)
        payload = message.encode(SUBJECT_SIGNAL_VALUES)
        encoder = Encoder(dictionary)

        oversized_records = [
            encoder.encode(
                RawFrame(timestamp_us=i, frame_id=message.frame_id, is_extended=message.is_extended_frame, payload=payload),
                batch_base_timestamp_us=0,
            )
            for i in range(20)
        ]
        oversized_payload = pack_batch(
            dict_version=dictionary.dict_version, base_timestamp_us=0, batch_seq=0, records=oversized_records
        )
        oversized_framed = cobs_frame(oversized_payload)
        assert len(oversized_framed) > small_bufsize, (
            "fixture assumption: this batch must exceed the deliberately "
            "small test receive buffer"
        )

        follow_up_payload, _msg, _payload = _build_one_record_batch(dictionary, dbc, batch_seq=99)
        follow_up_framed = cobs_frame(follow_up_payload)
        assert len(follow_up_framed) <= small_bufsize, (
            "fixture assumption: the follow-up batch must fit whole in the "
            "small test buffer, so its own trailing delimiter survives "
            "truncation intact"
        )

        deframer = Deframer(dictionary)

        send_link.send(oversized_framed)
        first_result = recv_link.recv(timeout=2.0)

        if first_result is not None and len(first_result) == small_bufsize:
            # POSIX-style silent truncation: the truncated bytes arrive but
            # contain no delimiter yet -- still buffered, not yet processed.
            recovered_from_truncated = list(deframer.feed(first_result))
            assert recovered_from_truncated == []

            send_link.send(follow_up_framed)
            follow_up_received = recv_link.recv(timeout=2.0)
            assert follow_up_received == follow_up_framed  # arrived whole, well under the buffer

            recovered = list(deframer.feed(follow_up_received))

            # The truncated bytes and the follow-up datagram's bytes are
            # one contiguous buffered segment until the follow-up's own
            # trailing delimiter is found, so the merged segment fails as
            # corrupt -- nothing from either batch reaches the decoder.
            assert recovered == []
            total_corruption = (
                deframer.counters.cobs_failures
                + deframer.counters.crc_failures
                + deframer.counters.batch_format_failures
            )
            assert total_corruption == 1
            assert deframer.counters.records_decoded == 0
        elif first_result is None:
            # Winsock-style: the oversized datagram was dropped by the OS
            # before reaching this process -- nothing was ever buffered, so
            # a follow-up batch decodes cleanly on its own, unpolluted.
            send_link.send(follow_up_framed)
            follow_up_received = recv_link.recv(timeout=2.0)
            assert follow_up_received == follow_up_framed

            recovered = list(deframer.feed(follow_up_received))
            assert len(recovered) == 1
            assert deframer.counters.records_decoded == 1
            total_corruption = (
                deframer.counters.cobs_failures
                + deframer.counters.crc_failures
                + deframer.counters.batch_format_failures
            )
            assert total_corruption == 0
        else:
            pytest.fail(
                f"unexpected recv() result for an oversized datagram on "
                f"this platform: {first_result!r}"
            )
    finally:
        send_link.close()
        recv_link.close()


def test_several_batches_sent_every_arrival_is_intact_loss_not_asserted(dictionary, dbc):
    """UDP's own unacknowledged loss is a modelled feature of the real radio
    link (`.planning/research/ARCHITECTURE.md` Pattern 4), not a defect --
    this test asserts every datagram that *does* arrive is byte-identical to
    what was sent, and deliberately does not assert that none is lost
    (which would make the suite flaky for the wrong reason on a loopback
    interface)."""
    send_link, recv_link = _new_udp_pair()
    try:
        sent = []
        for batch_seq in range(10):
            payload, _message, _payload = _build_one_record_batch(dictionary, dbc, batch_seq=batch_seq)
            framed = cobs_frame(payload)
            sent.append(framed)
            send_link.send(framed)

        received = []
        while True:
            chunk = recv_link.recv(timeout=0.5)
            if chunk is None:
                break
            received.append(chunk)

        assert set(received).issubset(set(sent)), "every arriving datagram must be byte-identical to something that was actually sent"
        assert len(received) > 0, "loopback UDP should not lose an entire small burst -- if this ever flakes, the loopback path itself is broken, not modelling real loss"
    finally:
        send_link.close()
        recv_link.close()


# ---------------------------------------------------------------------------
# LINK-04: no radio, no vehicle hardware, no second machine
# ---------------------------------------------------------------------------


def test_no_radio_or_serial_driver_imported_by_either_link_implementation():
    import ast
    import inspect
    from pathlib import Path

    from telemetry.link import loopback as loopback_module
    from telemetry.link import udp as udp_module

    for module in (loopback_module, udp_module):
        source_path = inspect.getsourcefile(module)
        tree = ast.parse(Path(source_path).read_text(encoding="utf-8"))

        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        forbidden = [m for m in imported if m == "serial" or m.startswith("serial.")]
        assert forbidden == [], f"{module.__name__} imports a radio/serial driver: {forbidden}"


def test_udp_link_uses_only_the_loopback_interface_in_this_suite():
    """A structural reminder, not a new mechanism: every `UdpLink` this
    file constructs binds `127.0.0.1` explicitly (`LOOPBACK_HOST`) -- no
    test in this file ever binds `0.0.0.0` or a real interface address, so
    the whole suite is provably hardware- and network-free by construction
    (LINK-04)."""
    link = UdpLink(local_addr=(LOOPBACK_HOST, 0))
    try:
        host, _port = link.local_addr
        assert host in (LOOPBACK_HOST, "0.0.0.0")
    finally:
        link.close()
