"""
Requirements covered: CAP-01, CAP-06.
Filled by: 01-09.

Every test drives an injected fake SDK object, never the real `ics` module
(except the one test explicitly marked as depending on the real module, and
even that one never touches hardware — `ics.find_devices()` is never
called), so this suite is identical on a laptop with no neoVI driver and on
the CM4 with the real hardware attached.

Task 1: SDK seam, config-driven channel resolution, and fail-fast device
open. Task 2 (poll loop, frame construction, hardware error accounting)
lands in a later commit on this same file.
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


class _FakeSdk:
    """Fake `python-ics` module surface."""

    SPY_STATUS_XTD_FRAME = 0x4
    RuntimeError = _FakeRuntimeError

    def __init__(self, netids: Optional[dict] = None, devices=()):
        self._netids = netids or {}
        self._devices = tuple(devices)
        self.opened_device = None

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
