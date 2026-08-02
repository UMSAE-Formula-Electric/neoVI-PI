"""
telemetry.capture.hardware_source — the single consolidated `python-ics`
capture implementation for CAP-01's first clause: one device handle, both
configured buses, one stream of frames tagged with the channel they arrived
on. (The second clause of CAP-01 — removing the duplicate legacy
implementations `src/new_logger.py`/`src/neoVI_logger.py`/`src/references.py`/
`src/neoVI_sender.py` — is deferred to Phase 2 by user decision; this module
does not touch or remove them.)

The SDK choice rests on directly observed hardware-free behaviour recorded in
`01-RESEARCH.md` Pattern 5: `ics.find_devices()` raises a catchable
`RuntimeError` in well under a second with no native driver present, while a
bare `import vspyx` hung for a full thirty-second test window before reaching
any initialisation call. No module under `telemetry` may import the legacy
SDK — including through a fallback path, because a "try the other SDK"
branch would reintroduce exactly the boot-time hang this choice avoids. This
module never imports `vspyx`, directly or transitively, and `ics` itself is
imported lazily (only inside `_default_sdk`, only when no SDK object is
injected) so importing this module never touches the SDK at all.

Every symbolic net-ID constant name and every device-selection setting comes
from `telemetry.logger.config` (OPS-05) — never a hardcoded map like
`src/new_logger.py`'s `CHANNEL_MAP` (lines 41-59). An unresolvable symbolic
name is fatal at construction (T-01-22): the legacy `resolve_net_ids`
(`src/new_logger.py` line 131) warns and silently captures unfiltered, which
this module deliberately does not reproduce.

Two SDK facts this module depends on were established live against the
installed `python-ics 1!26.3.9` this session (see `01-09-SUMMARY.md` for the
full record):

- The extended-identifier flag lives at `StatusBitField &
  SPY_STATUS_XTD_FRAME` (0x4), not `SPY_STATUS_EXTENDED` (0x80000000) — the
  latter sits in an overloaded high-bit tier (`SPY_STATUS_CANFD` and
  `SPY_STATUS_INIT_MESSAGE` both equal 0x20000000), and `src/new_logger.py`'s
  existing TX code already sets `SPY_STATUS_XTD_FRAME` on the same field to
  mark an outgoing frame extended.
- `ics.get_messages(device)` returns `(tuple_of_SpyMessage, error_count)`,
  confirmed verbatim from the installed module's own docstring.

A third fact — the unit and epoch of `SpyMessage.TimeSystem` — could NOT be
established with confidence from the installed module on this (Windows, no
hardware) dev machine, because the deployment target is Linux (the CM4). It
is carried forward as a single named, explicitly UNCONFIRMED constant below
rather than guessed into the code — see the constant's own comment and
`01-09-SUMMARY.md`'s hardware bring-up item.

`ics.RuntimeError` is NOT a subclass of the builtin `RuntimeError`
(`issubclass(ics.RuntimeError, RuntimeError)` is `False`, verified live this
session — its MRO is `(ics.ics.RuntimeError, Exception, BaseException,
object)`). A bare `except RuntimeError:` around a poll or device-open call
would therefore catch nothing on real hardware. Every SDK exception in this
module is caught via the injected SDK object's own `RuntimeError` attribute
(`self._sdk.RuntimeError`), never the bare builtin — and the fake SDK used in
`tests/test_hardware_source.py` defines its exception the same way
(inheriting `Exception` directly), so code that reaches for the builtin
fails in the test suite rather than in the field.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterator, Optional, Sequence

from telemetry.capture.fanout import CapturedFrame
from telemetry.logger.config import ChannelConfig
from telemetry.wire.frame_source import RawFrame

logger = logging.getLogger(__name__)


def _default_sdk():
    """Lazily imports and returns the real `ics` module. Imported only here,
    only when no SDK object is injected — so constructing a
    `HardwareFrameSource` with an injected fake never touches the SDK, and
    merely importing this module never does either."""
    import ics

    return ics


# `SpyMessage.TimeSystem`'s own docstring (captured live via
# `help(ics.SpyMessage)` against the installed python-ics 1!26.3.9) describes
# it as sourced from the Windows-only `timeGetTime()` multimedia API —
# milliseconds, from an arbitrary system-uptime-relative epoch that wraps
# roughly every 49.7 days as a DWORD. The deployment target is Linux (the
# CM4), so this Windows-specific docstring text may not describe what the
# same attribute reports on the real hardware — the compiled extension could
# report something else there entirely, and `src/new_logger.py`'s existing
# `f'{ts:.6f}'` CSV formatting is not authoritative counter-evidence (an
# integer millisecond count formatted with six decimal places just shows
# trailing zeros). THIS CONSTANT IS THEREFORE UNCONFIRMED, not a settled
# fact — settle it on the first bench session with the neoVI PI attached
# (01-VALIDATION.md lists dual-bus capture against real hardware as
# manual-only; that check is the place to record the result) before trusting
# archived timestamps for anything beyond relative ordering within a session.
TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED = 1000  # assumes milliseconds


class ChannelResolutionError(Exception):
    """Raised at construction when a configured channel's symbolic net-ID
    constant name is not exposed by the SDK object. Names the channel and
    the constant name that could not be found; no partially-constructed
    source is returned (T-01-22)."""


class DeviceNotFoundError(Exception):
    """Raised by `open()` when device enumeration finds no devices, or when
    a configured serial does not match any device found. Fails fast — no
    retry, no blocking wait."""


@dataclass
class HardwareSourceCounters:
    """CAP-06's counters. Written only by the thread calling
    `captured_frames()`/`frames()`; safe to read from other threads only
    after that thread has stopped — the same single-writer rationale as
    `telemetry.capture.fanout.FanOutCounters`."""

    poll_count: int = 0
    hardware_error_count: int = 0
    poll_exception_count: int = 0
    excluded_message_count: int = 0


class HardwareFrameSource:
    """The consolidated `python-ics` capture source. Construct with the
    configured channels and capture settings (from `LoggerConfig`), call
    `open()` to select and open the device, then iterate `captured_frames()`
    (channel-tagged) or `frames()` (the `FrameSource`-protocol-satisfying
    `RawFrame`-only view)."""

    def __init__(
        self,
        channels: Sequence[ChannelConfig],
        poll_interval_s: float,
        hardware_serial: Optional[str],
        stop_event: threading.Event,
        sdk: Optional[object] = None,
    ) -> None:
        self._sdk = sdk if sdk is not None else _default_sdk()
        self._poll_interval_s = poll_interval_s
        self._hardware_serial = hardware_serial
        self._stop_event = stop_event
        self.counters = HardwareSourceCounters()
        self.device = None

        # Resolve every configured channel against the SDK object now, so an
        # unresolvable symbolic constant name is fatal at construction — no
        # partially-constructed source is ever returned.
        net_id_to_channel: Dict[int, str] = {}
        for channel in channels:
            net_id_to_channel[self._resolve_net_id(channel)] = channel.name
        self.net_id_to_channel = net_id_to_channel

    def _resolve_net_id(self, channel: ChannelConfig) -> int:
        if not hasattr(self._sdk, channel.netid):
            raise ChannelResolutionError(
                f"channel {channel.name!r} names symbolic net-ID constant "
                f"{channel.netid!r}, which the SDK object does not expose"
            )
        return getattr(self._sdk, channel.netid)

    def open(self) -> None:
        """Select and open the device: by configured serial if one is set,
        otherwise the first device found. Fails fast — no retry, no
        blocking wait — and logs full context (configured serial, devices
        actually seen) before raising, so a bench diagnosis never requires
        re-running under a debugger (CAP-06)."""
        devices = self._sdk.find_devices()
        if not devices:
            logger.critical(
                "no neoVI devices found (configured hardware_serial=%r)",
                self._hardware_serial,
            )
            raise DeviceNotFoundError(
                "no device was found — is the neoVI hardware connected?"
            )

        seen_serials = [str(getattr(d, "SerialNumber", d)) for d in devices]

        if self._hardware_serial:
            device = None
            for candidate in devices:
                if str(getattr(candidate, "SerialNumber", candidate)) == self._hardware_serial:
                    device = candidate
                    break
            if device is None:
                logger.critical(
                    "configured hardware_serial %r matched no device; "
                    "devices seen: %s",
                    self._hardware_serial,
                    seen_serials,
                )
                raise DeviceNotFoundError(
                    f"no device matching configured serial "
                    f"{self._hardware_serial!r} found; available: {seen_serials}"
                )
        else:
            device = devices[0]

        self._sdk.open_device(device)
        self.device = device
        logger.info(
            "opened neoVI device (serial=%s)",
            getattr(device, "SerialNumber", device),
        )

    def captured_frames(self) -> Iterator[CapturedFrame]:
        """Poll at the configured interval, filter by the resolved net-ID
        set, and yield one `CapturedFrame` per surviving message. Opens the
        device first if `open()` has not already been called. Checks the
        stop event every iteration and exits promptly when it is set —
        `threading.Event.wait` is interrupted immediately when the event is
        set from another thread, so this never waits out a full poll
        interval before noticing."""
        if self.device is None:
            self.open()

        iteration = 0
        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self._poll_interval_s):
                break

            iteration += 1
            self.counters.poll_count += 1

            try:
                messages, error_count = self._sdk.get_messages(self.device)
            except self._sdk.RuntimeError as exc:
                logger.critical(
                    "get_messages failed at poll iteration %d: %s", iteration, exc
                )
                self.counters.poll_exception_count += 1
                self._stop_event.set()
                raise

            if error_count:
                self.counters.hardware_error_count += error_count
                logger.warning(
                    "hardware reported %d error(s) at poll iteration %d",
                    error_count,
                    iteration,
                )

            for message in messages:
                channel = self.net_id_to_channel.get(message.NetworkID)
                if channel is None:
                    self.counters.excluded_message_count += 1
                    continue

                dlc = message.NumberBytesData
                frame = RawFrame(
                    timestamp_us=int(
                        message.TimeSystem * TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED
                    ),
                    frame_id=message.ArbIDOrHeader & 0x1FFFFFFF,
                    is_extended=bool(
                        message.StatusBitField & self._sdk.SPY_STATUS_XTD_FRAME
                    ),
                    payload=bytes(message.Data[:dlc]),
                )
                yield CapturedFrame(channel=channel, frame=frame)

    def frames(self) -> Iterator[RawFrame]:
        """Thin delegate over `captured_frames()` that yields only the
        `RawFrame` half, satisfying `telemetry.wire.frame_source.FrameSource`
        so the Phase 0 measurement tooling can consume this source
        unchanged. Deliberately discards the channel tag."""
        for captured in self.captured_frames():
            yield captured.frame
