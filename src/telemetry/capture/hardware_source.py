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

`ics.RuntimeError` is NOT a subclass of the builtin `RuntimeError`
(`issubclass(ics.RuntimeError, RuntimeError)` is `False`, verified live this
session — its MRO is `(ics.ics.RuntimeError, Exception, BaseException,
object)`). Every SDK exception in this module is caught via the injected SDK
object's own `RuntimeError` attribute (`self._sdk.RuntimeError`), never the
bare builtin — and the fake SDK used in `tests/test_hardware_source.py`
defines its exception the same way (inheriting `Exception` directly), so
code that reaches for the builtin fails in the test suite rather than in the
field. (This module's Task 1 surface below has no SDK-exception catch of its
own yet — device selection here fails on locally-detected conditions, not on
an SDK-raised exception; the poll loop that does need this lands in Task 2.)
"""

import logging
from typing import Dict, Optional, Sequence

from telemetry.logger.config import ChannelConfig

logger = logging.getLogger(__name__)


def _default_sdk():
    """Lazily imports and returns the real `ics` module. Imported only here,
    only when no SDK object is injected — so constructing a
    `HardwareFrameSource` with an injected fake never touches the SDK, and
    merely importing this module never does either."""
    import ics

    return ics


class ChannelResolutionError(Exception):
    """Raised at construction when a configured channel's symbolic net-ID
    constant name is not exposed by the SDK object. Names the channel and
    the constant name that could not be found; no partially-constructed
    source is returned (T-01-22)."""


class DeviceNotFoundError(Exception):
    """Raised by `open()` when device enumeration finds no devices, or when
    a configured serial does not match any device found. Fails fast — no
    retry, no blocking wait."""


class HardwareFrameSource:
    """The consolidated `python-ics` capture source. Construct with the
    configured channels and capture settings (from `LoggerConfig`), then
    call `open()` to select and open the device."""

    def __init__(
        self,
        channels: Sequence[ChannelConfig],
        poll_interval_s: float,
        hardware_serial: Optional[str],
        stop_event,
        sdk: Optional[object] = None,
    ) -> None:
        self._sdk = sdk if sdk is not None else _default_sdk()
        self._poll_interval_s = poll_interval_s
        self._hardware_serial = hardware_serial
        self._stop_event = stop_event
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
