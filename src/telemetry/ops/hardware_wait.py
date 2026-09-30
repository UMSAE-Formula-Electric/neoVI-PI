"""
telemetry.ops.hardware_wait -- the boot-time hardware-presence probe (OPS-01)
that turns the neoVI PI's normal boot-vs-bus-power race into a visible,
retried wait instead of an exit or a crash-loop.

The CM4 frequently finishes booting before the CAN bus is powered. This
module's single public function, `wait_for_hardware`, polls
`sdk.find_devices()` with exponential backoff until a device appears or the
caller's `stop_event` fires -- there is no timeout and no maximum attempt
count, because on the car waiting indefinitely IS the correct behaviour
(03-CONTEXT.md's locked decision D: the logger stays alive and retries).
`stop_event` is the only exit.

**This module reuses `telemetry.capture.hardware_source.HardwareFrameSource`'s
already-established SDK exception surface rather than reinventing it.**
`ics.RuntimeError` is NOT a subclass of the builtin `RuntimeError`
(`issubclass(ics.RuntimeError, RuntimeError)` is `False`, verified live
against the installed SDK -- see `hardware_source.py`'s own docstring and
`03-RESEARCH.md` Pattern 4/Pitfall 4, which re-confirmed this independently
this session). A bare `except RuntimeError:` around `find_devices()` would
therefore catch nothing on real hardware. Every SDK exception here is caught
via the injected SDK object's own `RuntimeError` attribute (`sdk.RuntimeError`),
never the bare builtin -- and the fake SDK used in this module's own test
suite defines its exception the same way (inheriting `Exception` directly),
so code that reaches for the builtin fails in the test suite rather than in
the field.

**Two distinct conditions both surface through `sdk.find_devices()`, and
only one is fully verified** (03-RESEARCH.md Pattern 4):

- `[VERIFIED: live against installed python-ics 1!26.3.9]` -- with the
  native driver library entirely absent (this Windows dev box has no
  `icsneo40.dll`), `find_devices()` raises `sdk.RuntimeError`.
- `[ASSUMED -- inferred from HardwareFrameSource.open()'s already-merged
  code, not independently re-verified on Linux this session]` -- with the
  driver present but zero devices physically attached (the expected
  CM4/Linux condition during the boot race this module exists for),
  `find_devices()` is expected to return an empty tuple, not raise.

This module treats both outcomes identically ("not present yet, retry"),
which is what makes the open question above harmless regardless of which is
actually true on the CM4 -- confirm this on first real Pi bring-up.

Like `hardware_source.py`'s `_default_sdk`, the real `ics` module is
imported lazily, only inside `_default_sdk`, only when no SDK object is
injected -- importing this module never touches the SDK, and constructing
`wait_for_hardware` with an injected fake never does either. This is what
keeps this unit-testable on this Windows dev box, where no native driver
exists at all, and is also why a bare `import vspyx` must never be added
here even as a fallback: it was measured to hang for a full 30s with no
native driver present on this project (`hardware_source.py`'s own module
docstring).
"""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_DEFAULT_INITIAL_BACKOFF_S = 0.5
_DEFAULT_MAX_BACKOFF_S = 5.0


def _default_sdk():
    """Lazily imports and returns the real `ics` module. Imported only here,
    only when no SDK object is injected -- so calling `wait_for_hardware`
    with an injected fake never touches the SDK, and merely importing this
    module never does either. Mirrors
    `telemetry.capture.hardware_source._default_sdk` exactly."""
    import ics

    return ics


def wait_for_hardware(
    *,
    stop_event: threading.Event,
    on_waiting: Optional[Callable[[int, float], None]] = None,
    sdk: Optional[object] = None,
    initial_backoff_s: float = _DEFAULT_INITIAL_BACKOFF_S,
    max_backoff_s: float = _DEFAULT_MAX_BACKOFF_S,
) -> bool:
    """Polls `sdk.find_devices()` with exponential backoff until a device is
    found or `stop_event` fires. Returns True once devices are found, False
    if `stop_event` fires first.

    There is deliberately no timeout parameter and no maximum attempt count:
    on the car, waiting indefinitely for the bus to power up is correct
    behaviour, not a fault -- `stop_event` is the only exit.

    Treats BOTH a caught `sdk.RuntimeError` and an empty devices tuple as
    "not present yet" (see module docstring for why both must be handled
    identically). An exception the SDK does not own (not `sdk.RuntimeError`)
    propagates -- this function never swallows an error it cannot name.

    Calls `on_waiting(attempt, backoff_s)` before each wait, then
    `stop_event.wait(timeout=backoff_s)` -- never a bare `time.sleep`, so a
    stop signal interrupts immediately instead of waiting out a full
    backoff, exactly like `HardwareFrameSource.captured_frames()`'s poll
    loop. Backoff doubles from `initial_backoff_s` and is clamped at
    `max_backoff_s`.

    The first wait is logged at WARNING (naming the state); every
    subsequent wait is logged at DEBUG -- a bus that stays unpowered for
    minutes must not fill the journal with a repeated WARNING line.
    """
    sdk = sdk if sdk is not None else _default_sdk()
    attempt = 0
    backoff_s = initial_backoff_s

    while not stop_event.is_set():
        try:
            devices = sdk.find_devices()
        except sdk.RuntimeError as exc:
            # Reuses hardware_source.py's own explanatory reasoning: the SDK
            # raises its OWN RuntimeError (not a subclass of the builtin)
            # when the native driver is entirely absent. Treated identically
            # to an empty devices tuple -- see module docstring.
            logger.debug(
                "find_devices() raised %s while waiting for hardware "
                "(attempt %d) -- treated as not-present-yet",
                exc,
                attempt + 1,
            )
            devices = ()

        if devices:
            return True

        attempt += 1
        if attempt == 1:
            logger.warning(
                "no neoVI hardware found -- entering waiting-for-hardware "
                "(attempt %d, retrying every %.1fs, backoff clamped at "
                "%.1fs)",
                attempt,
                backoff_s,
                max_backoff_s,
            )
        else:
            logger.debug(
                "still waiting for hardware (attempt %d, backoff %.1fs)",
                attempt,
                backoff_s,
            )

        if on_waiting is not None:
            on_waiting(attempt, backoff_s)

        if stop_event.wait(timeout=backoff_s):
            break

        backoff_s = min(backoff_s * 2, max_backoff_s)

    return False
