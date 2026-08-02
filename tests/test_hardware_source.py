"""
Requirements covered: CAP-01, CAP-06.
Filled by: 01-09.

Every test drives an injected fake SDK object, never the real `ics` module
(except the one test explicitly marked as depending on the real module, and
even that one never touches hardware — `ics.find_devices()` is never
called), so this suite is identical on a laptop with no neoVI driver and on
the CM4 with the real hardware attached.
"""

import ast
import threading
import time
from pathlib import Path
from typing import Optional

import pytest

from telemetry.capture.hardware_source import (
    ChannelResolutionError,
    DeviceNotFoundError,
    HardwareFrameSource,
    TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED,
)
from telemetry.logger.config import ChannelConfig

CHANNEL_A_NETID = "NETID_HSCAN"
CHANNEL_B_NETID = "NETID_HSCAN2"


# ---------------------------------------------------------------------------
# Fake SDK — the injected seam every test in this file drives instead of the
# real `ics` module.
# ---------------------------------------------------------------------------


class _FakeRuntimeError(Exception):
    """Mirrors the real `ics.RuntimeError`'s MRO: inherits from `Exception`
    directly, NOT the builtin `RuntimeError` — verified live this session
    against the installed `ics` 1!26.3.9 (`issubclass(ics.RuntimeError,
    RuntimeError)` is `False`). Code under test that reaches for a bare
    `except RuntimeError:` instead of `sdk.RuntimeError` must fail to catch
    this and let it propagate, exactly as it would against real hardware."""


class _FakeDevice:
    def __init__(self, serial: str):
        self.SerialNumber = serial

    def __repr__(self) -> str:
        return f"_FakeDevice(serial={self.SerialNumber!r})"


class _FakeSpyMessage:
    def __init__(self, network_id, arb_id, dlc, data, status_bits=0, time_system=0.0):
        self.NetworkID = network_id
        self.ArbIDOrHeader = arb_id
        self.NumberBytesData = dlc
        self.Data = data
        self.StatusBitField = status_bits
        self.TimeSystem = time_system


class _FakeSdk:
    """Fake `python-ics` module surface. `stop_event_after_get_messages`, if
    given, is set as a side effect of `get_messages` returning — used to
    make "exactly one poll iteration" deterministic in tests without
    threads: the outer loop rechecks the stop event before sleeping again,
    so setting it inside `get_messages` guarantees the generator yields
    exactly what one call produced and then exits cleanly."""

    SPY_STATUS_XTD_FRAME = 0x4
    RuntimeError = _FakeRuntimeError

    def __init__(
        self,
        netids: Optional[dict] = None,
        devices=(),
        stop_event_after_get_messages: Optional[threading.Event] = None,
    ):
        self._netids = netids or {}
        self._devices = tuple(devices)
        self.messages_to_return = ()
        self.error_count_to_return = 0
        self.raise_on_get_messages = None
        self.opened_device = None
        self.get_messages_call_count = 0
        self._stop_event_after_get_messages = stop_event_after_get_messages

    def __getattr__(self, name):
        # Only reached for names not found as class/instance attributes
        # (e.g. SPY_STATUS_XTD_FRAME and RuntimeError above are found
        # normally and never hit this).
        try:
            return self._netids[name]
        except KeyError:
            raise AttributeError(name) from None

    def find_devices(self):
        return self._devices

    def open_device(self, device):
        self.opened_device = device

    def get_messages(self, device):
        self.get_messages_call_count += 1
        if self.raise_on_get_messages is not None:
            raise self.raise_on_get_messages
        if self._stop_event_after_get_messages is not None:
            self._stop_event_after_get_messages.set()
        return tuple(self.messages_to_return), self.error_count_to_return


def _ics_importable() -> bool:
    try:
        import ics  # noqa: F401
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Task 1: SDK seam, config-driven channel resolution, fail-fast device open
# ---------------------------------------------------------------------------


def test_channel_resolves_to_sdk_integer():
    sdk = _FakeSdk(netids={CHANNEL_A_NETID: 1})
    channels = [ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1")]
    source = HardwareFrameSource(
        channels=channels,
        poll_interval_s=0.01,
        hardware_serial=None,
        stop_event=threading.Event(),
        sdk=sdk,
    )
    assert source.net_id_to_channel == {1: "MAIN"}


def test_unresolvable_channel_name_raises_named_error_at_construction():
    sdk = _FakeSdk(netids={})  # exposes nothing
    channels = [ChannelConfig(name="MAIN", netid="NETID_NOT_REAL", bus="bus1")]

    with pytest.raises(ChannelResolutionError) as exc_info:
        HardwareFrameSource(
            channels=channels,
            poll_interval_s=0.01,
            hardware_serial=None,
            stop_event=threading.Event(),
            sdk=sdk,
        )

    message = str(exc_info.value)
    assert "MAIN" in message
    assert "NETID_NOT_REAL" in message


def test_net_id_to_channel_map_covers_exactly_configured_channels():
    sdk = _FakeSdk(netids={CHANNEL_A_NETID: 1, CHANNEL_B_NETID: 42, "NETID_HSCAN3": 3})
    channels = [
        ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1"),
        ChannelConfig(name="SENSOR", netid=CHANNEL_B_NETID, bus="bus2"),
    ]
    source = HardwareFrameSource(
        channels=channels,
        poll_interval_s=0.01,
        hardware_serial=None,
        stop_event=threading.Event(),
        sdk=sdk,
    )
    # Exactly the configured channels -- NETID_HSCAN3, though the fake SDK
    # exposes it, is not configured and must not appear.
    assert source.net_id_to_channel == {1: "MAIN", 42: "SENSOR"}


@pytest.mark.skipif(not _ics_importable(), reason="real ics module not importable")
def test_shipped_config_channels_resolve_against_real_ics(logger_config):
    """A config naming a constant that does not exist in the installed SDK
    is caught by the suite rather than at first boot on the car. This never
    calls `ics.find_devices()` -- it only exercises attribute resolution,
    so it needs no hardware or driver."""
    import ics

    source = HardwareFrameSource(
        channels=logger_config.channels,
        poll_interval_s=logger_config.capture.poll_interval_s,
        hardware_serial=logger_config.capture.hardware_serial,
        stop_event=threading.Event(),
        sdk=ics,
    )
    assert set(source.net_id_to_channel.values()) == {c.name for c in logger_config.channels}


def test_open_with_no_devices_raises_named_error_no_retry_or_block():
    sdk = _FakeSdk(devices=())
    source = HardwareFrameSource(
        channels=[],
        poll_interval_s=0.01,
        hardware_serial=None,
        stop_event=threading.Event(),
        sdk=sdk,
    )

    started = time.perf_counter()
    with pytest.raises(DeviceNotFoundError) as exc_info:
        source.open()
    elapsed = time.perf_counter() - started

    assert "no device" in str(exc_info.value).lower()
    assert "found" in str(exc_info.value).lower()
    assert elapsed < 0.5  # no retry loop, no blocking wait


def test_open_selects_matching_serial_among_several_devices():
    device_a = _FakeDevice("AAA")
    device_b = _FakeDevice("BBB")
    sdk = _FakeSdk(devices=[device_a, device_b])
    source = HardwareFrameSource(
        channels=[],
        poll_interval_s=0.01,
        hardware_serial="BBB",
        stop_event=threading.Event(),
        sdk=sdk,
    )
    source.open()
    assert source.device is device_b
    assert sdk.opened_device is device_b


def test_open_with_configured_serial_matching_none_names_serial_and_lists_available():
    device_a = _FakeDevice("AAA")
    device_b = _FakeDevice("BBB")
    sdk = _FakeSdk(devices=[device_a, device_b])
    source = HardwareFrameSource(
        channels=[],
        poll_interval_s=0.01,
        hardware_serial="ZZZ",
        stop_event=threading.Event(),
        sdk=sdk,
    )

    with pytest.raises(DeviceNotFoundError) as exc_info:
        source.open()

    message = str(exc_info.value)
    assert "ZZZ" in message
    assert "AAA" in message
    assert "BBB" in message


def test_open_with_no_configured_serial_selects_first_of_several():
    device_a = _FakeDevice("AAA")
    device_b = _FakeDevice("BBB")
    sdk = _FakeSdk(devices=[device_a, device_b])
    source = HardwareFrameSource(
        channels=[],
        poll_interval_s=0.01,
        hardware_serial=None,
        stop_event=threading.Event(),
        sdk=sdk,
    )
    source.open()
    assert source.device is device_a


def test_hardware_source_module_does_not_import_vspyx():
    """Static check (this file's own source) plus a runtime check that
    importing this module never pulls `vspyx` into `sys.modules` -- covers
    both a direct and a transitive import."""
    import sys

    import telemetry.capture.hardware_source as module

    source_path = Path(module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(name.split(".")[0] == "vspyx" for name in imported)

    assert "vspyx" not in sys.modules


def test_no_module_under_telemetry_imports_vspyx():
    """Static scan over every source file under `src/telemetry` -- a bare
    `import vspyx` reached from any startup path hung for the full
    thirty-second research-session test window with no hardware present
    (`01-RESEARCH.md` Pattern 5); an unattended logger that hangs at boot
    never recovers on its own (T-01-23)."""
    telemetry_root = Path(__file__).parent.parent / "src" / "telemetry"
    offenders = []
    for py_file in telemetry_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name.split(".")[0] == "vspyx" for name in names):
                offenders.append(str(py_file))
    assert offenders == [], f"vspyx imported by: {offenders}"


# ---------------------------------------------------------------------------
# Task 2: the poll loop, frame construction, and hardware error accounting
# ---------------------------------------------------------------------------


def _make_source(sdk, channels, poll_interval_s=0.01, hardware_serial=None, stop_event=None):
    source = HardwareFrameSource(
        channels=channels,
        poll_interval_s=poll_interval_s,
        hardware_serial=hardware_serial,
        stop_event=stop_event if stop_event is not None else threading.Event(),
        sdk=sdk,
    )
    source.open()
    return source


def test_captured_frames_yields_frame_with_masked_id_extended_flag_payload_and_timestamp():
    stop_event = threading.Event()
    sdk = _FakeSdk(
        netids={CHANNEL_A_NETID: 1},
        devices=[_FakeDevice("SN1")],
        stop_event_after_get_messages=stop_event,
    )
    # ArbIDOrHeader carries extra bits above the 29-bit range to prove
    # masking actually happens rather than being a no-op on well-formed ids.
    sdk.messages_to_return = [
        _FakeSpyMessage(
            network_id=1,
            arb_id=0xE0000123,
            dlc=3,
            data=(0xAA, 0xBB, 0xCC, 0xDD, 0xEE),  # only first 3 bytes count
            status_bits=_FakeSdk.SPY_STATUS_XTD_FRAME,
            time_system=123.0,
        )
    ]
    channels = [ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1")]
    source = _make_source(sdk, channels, stop_event=stop_event)

    captured = list(source.captured_frames())

    assert len(captured) == 1
    frame = captured[0]
    assert frame.channel == "MAIN"
    assert frame.frame.frame_id == 0x00000123  # masked to 29 bits
    assert frame.frame.is_extended is True
    assert frame.frame.payload == b"\xaa\xbb\xcc"
    assert frame.frame.timestamp_us == int(123.0 * TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED)


def test_captured_frames_extended_flag_clear_when_bit_not_set():
    stop_event = threading.Event()
    sdk = _FakeSdk(
        netids={CHANNEL_A_NETID: 1},
        devices=[_FakeDevice("SN1")],
        stop_event_after_get_messages=stop_event,
    )
    sdk.messages_to_return = [
        _FakeSpyMessage(network_id=1, arb_id=0x100, dlc=1, data=(0x01,), status_bits=0)
    ]
    channels = [ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1")]
    source = _make_source(sdk, channels, stop_event=stop_event)

    captured = list(source.captured_frames())
    assert captured[0].frame.is_extended is False


def test_excluded_messages_are_counted_not_yielded():
    stop_event = threading.Event()
    sdk = _FakeSdk(
        netids={CHANNEL_A_NETID: 1},
        devices=[_FakeDevice("SN1")],
        stop_event_after_get_messages=stop_event,
    )
    sdk.messages_to_return = [
        _FakeSpyMessage(network_id=1, arb_id=0x100, dlc=1, data=(0x01,)),
        _FakeSpyMessage(network_id=999, arb_id=0x200, dlc=1, data=(0x02,)),  # not configured
    ]
    channels = [ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1")]
    source = _make_source(sdk, channels, stop_event=stop_event)

    captured = list(source.captured_frames())

    assert len(captured) == 1
    assert captured[0].frame.frame_id == 0x100
    assert source.counters.excluded_message_count == 1


def test_frames_yields_raw_frames_matching_captured_frames():
    stop_event = threading.Event()
    sdk = _FakeSdk(
        netids={CHANNEL_A_NETID: 1},
        devices=[_FakeDevice("SN1")],
        stop_event_after_get_messages=stop_event,
    )
    sdk.messages_to_return = [
        _FakeSpyMessage(network_id=1, arb_id=0x100, dlc=1, data=(0x01,), time_system=1.0),
        _FakeSpyMessage(network_id=1, arb_id=0x101, dlc=1, data=(0x02,), time_system=2.0),
    ]
    channels = [ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1")]
    source = _make_source(sdk, channels, stop_event=stop_event)

    raw_frames = list(source.frames())

    assert len(raw_frames) == 2
    assert [f.frame_id for f in raw_frames] == [0x100, 0x101]


def test_hardware_error_count_increments_and_logs_iteration_and_count(caplog):
    import logging

    stop_event = threading.Event()
    sdk = _FakeSdk(
        netids={CHANNEL_A_NETID: 1},
        devices=[_FakeDevice("SN1")],
        stop_event_after_get_messages=stop_event,
    )
    sdk.messages_to_return = []
    sdk.error_count_to_return = 7
    channels = [ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1")]
    source = _make_source(sdk, channels, stop_event=stop_event)

    with caplog.at_level(logging.WARNING):
        frames = list(source.captured_frames())

    assert frames == []
    assert source.counters.hardware_error_count == 7
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_records
    joined = " ".join(r.getMessage() for r in warning_records)
    assert "7" in joined
    assert "1" in joined  # poll iteration


def test_poll_exception_caught_by_sdk_type_logged_critical_counted_reraised_and_stop_event_set(
    caplog,
):
    import logging

    stop_event = threading.Event()
    sdk = _FakeSdk(netids={CHANNEL_A_NETID: 1}, devices=[_FakeDevice("SN1")])
    sdk.raise_on_get_messages = _FakeRuntimeError("simulated hardware poll failure")
    channels = [ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1")]
    source = _make_source(sdk, channels, poll_interval_s=0.001, stop_event=stop_event)

    with caplog.at_level(logging.CRITICAL):
        with pytest.raises(_FakeRuntimeError):
            next(source.captured_frames())

    assert source.counters.poll_exception_count == 1
    assert stop_event.is_set()
    critical_records = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert critical_records
    joined = " ".join(r.getMessage() for r in critical_records)
    assert "simulated hardware poll failure" in joined
    assert "1" in joined  # poll iteration


def test_loop_exits_promptly_when_stop_event_set_without_waiting_full_interval():
    sdk = _FakeSdk(netids={CHANNEL_A_NETID: 1}, devices=[_FakeDevice("SN1")])
    channels = [ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1")]
    stop_event = threading.Event()
    source = _make_source(sdk, channels, poll_interval_s=5.0, stop_event=stop_event)

    result = {}

    def _drain():
        started = time.perf_counter()
        result["frames"] = list(source.captured_frames())
        result["elapsed"] = time.perf_counter() - started

    thread = threading.Thread(target=_drain)
    thread.start()
    time.sleep(0.05)
    stop_event.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert result["elapsed"] < 1.0  # far less than the 5s poll interval
    assert result["frames"] == []


def test_dual_bus_interleaved_messages_both_channels_in_one_stream():
    """CAP-01's first clause at the source layer: both configured channels
    stream from one `HardwareFrameSource` instance, interleaved."""
    stop_event = threading.Event()
    sdk = _FakeSdk(
        netids={CHANNEL_A_NETID: 1, CHANNEL_B_NETID: 42},
        devices=[_FakeDevice("SN1")],
        stop_event_after_get_messages=stop_event,
    )
    sdk.messages_to_return = [
        _FakeSpyMessage(network_id=1, arb_id=0x100, dlc=1, data=(0x01,)),
        _FakeSpyMessage(network_id=42, arb_id=0x200, dlc=1, data=(0x02,)),
        _FakeSpyMessage(network_id=1, arb_id=0x101, dlc=1, data=(0x03,)),
        _FakeSpyMessage(network_id=42, arb_id=0x201, dlc=1, data=(0x04,)),
    ]
    channels = [
        ChannelConfig(name="MAIN", netid=CHANNEL_A_NETID, bus="bus1"),
        ChannelConfig(name="SENSOR", netid=CHANNEL_B_NETID, bus="bus2"),
    ]
    source = _make_source(sdk, channels, stop_event=stop_event)

    captured = list(source.captured_frames())

    assert [c.channel for c in captured] == ["MAIN", "SENSOR", "MAIN", "SENSOR"]
    assert {c.channel for c in captured} == {"MAIN", "SENSOR"}
