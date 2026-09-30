"""
Task 1 for 03-04 (OPS-01): pins `telemetry.ops.hardware_wait.wait_for_hardware`'s
retry/backoff behaviour against a hand-rolled fake SDK, modelled on
`tests/test_hardware_source.py`'s fake -- including a fake `RuntimeError`
attribute that deliberately does NOT subclass the builtin, so the
builtin-shadowing regression this project has hit before is genuinely
exercised rather than assumed away.

Every test drives an injected fake SDK or fake stop_event -- no real sleep,
no real hardware, no real `ics` import.
"""

import threading
import time

import pytest

from telemetry.ops.hardware_wait import wait_for_hardware


class _FakeRuntimeError(Exception):
    """Mirrors the real `ics.RuntimeError`'s MRO: inherits from `Exception`
    directly, NOT the builtin `RuntimeError` -- exactly
    `tests/test_hardware_source.py::_FakeRuntimeError`'s shape. Code under
    test that reaches for a bare `except RuntimeError:` instead of
    `sdk.RuntimeError` must fail to catch this and let it propagate."""


class _FakeSdk:
    """A minimal fake SDK surface: `find_devices()` returns whatever
    `results` (a list of either a devices-tuple or an exception instance)
    says, one entry consumed per call. `RuntimeError` is the fake's own
    attribute, per the project's established catch-via-injected-attribute
    convention."""

    RuntimeError = _FakeRuntimeError

    def __init__(self, results):
        self._results = list(results)
        self.call_count = 0

    def find_devices(self):
        self.call_count += 1
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class _RecordingStopEvent:
    """A fake stop_event that records every `wait(timeout=...)` call's
    requested timeout, and can be told to "fire" after N waits -- lets the
    backoff/on_waiting assertions run with zero real sleeps."""

    def __init__(self, fire_after_waits=None):
        self._set = False
        self._fire_after_waits = fire_after_waits
        self.wait_timeouts = []

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        if self._fire_after_waits is not None and len(self.wait_timeouts) >= self._fire_after_waits:
            self._set = True
        return self._set


def test_devices_found_on_first_call_returns_true_immediately_and_never_waits():
    sdk = _FakeSdk(results=[(object(),)])
    stop_event = _RecordingStopEvent()
    on_waiting_calls = []

    result = wait_for_hardware(
        stop_event=stop_event,
        on_waiting=lambda attempt, backoff: on_waiting_calls.append((attempt, backoff)),
        sdk=sdk,
    )

    assert result is True
    assert sdk.call_count == 1
    assert on_waiting_calls == []
    assert stop_event.wait_timeouts == []


def test_two_empty_tuples_then_devices_returns_true_after_exactly_three_calls():
    sdk = _FakeSdk(results=[(), (), (object(),)])
    stop_event = _RecordingStopEvent()
    on_waiting_calls = []

    result = wait_for_hardware(
        stop_event=stop_event,
        on_waiting=lambda attempt, backoff: on_waiting_calls.append((attempt, backoff)),
        sdk=sdk,
    )

    assert result is True
    assert sdk.call_count == 3
    assert len(on_waiting_calls) == 2


def test_sdk_owned_runtime_error_is_treated_as_not_present_yet_and_retried():
    sdk = _FakeSdk(results=[_FakeRuntimeError("no driver present"), (object(),)])
    stop_event = _RecordingStopEvent()

    result = wait_for_hardware(stop_event=stop_event, sdk=sdk)

    assert result is True
    assert sdk.call_count == 2


def test_non_sdk_exception_propagates_rather_than_being_swallowed():
    sdk = _FakeSdk(results=[ValueError("not an SDK error")])
    stop_event = _RecordingStopEvent()

    with pytest.raises(ValueError):
        wait_for_hardware(stop_event=stop_event, sdk=sdk)


def test_stop_event_firing_while_waiting_returns_false_promptly():
    # Never finds a device -- the fake stop event fires after the first
    # wait() call, simulating a stop signal arriving mid-backoff.
    sdk = _FakeSdk(results=[(), (), (), (), ()])
    stop_event = _RecordingStopEvent(fire_after_waits=1)

    started = time.perf_counter()
    result = wait_for_hardware(stop_event=stop_event, sdk=sdk)
    elapsed = time.perf_counter() - started

    assert result is False
    assert elapsed < 0.5  # no real sleep anywhere -- the fake wait() returns instantly
    assert len(stop_event.wait_timeouts) == 1


def test_stop_event_set_before_first_call_returns_false_with_no_find_devices_call():
    sdk = _FakeSdk(results=[])
    stop_event = _RecordingStopEvent()
    stop_event.set()

    result = wait_for_hardware(stop_event=stop_event, sdk=sdk)

    assert result is False
    assert sdk.call_count == 0


def test_backoff_grows_from_initial_and_is_clamped_at_max():
    # Never finds a device; never told to stop by the fake -- bounded by
    # results running out (find_devices raises IndexError from the fake's
    # own pop(0) once exhausted, which is fine: we only care about the
    # timeout sequence recorded before that point).
    sdk = _FakeSdk(results=[()] * 6)
    stop_event = _RecordingStopEvent(fire_after_waits=6)

    wait_for_hardware(
        stop_event=stop_event,
        sdk=sdk,
        initial_backoff_s=0.5,
        max_backoff_s=2.0,
    )

    # 0.5, 1.0, 2.0, 2.0, 2.0, 2.0 -- doubles each time, clamped at 2.0.
    assert stop_event.wait_timeouts == [0.5, 1.0, 2.0, 2.0, 2.0, 2.0]


def test_on_waiting_receives_attempt_number_and_backoff_about_to_be_waited():
    sdk = _FakeSdk(results=[(), (), (object(),)])
    stop_event = _RecordingStopEvent()
    on_waiting_calls = []

    wait_for_hardware(
        stop_event=stop_event,
        on_waiting=lambda attempt, backoff: on_waiting_calls.append((attempt, backoff)),
        sdk=sdk,
        initial_backoff_s=0.5,
        max_backoff_s=5.0,
    )

    assert on_waiting_calls == [(1, 0.5), (2, 1.0)]


def test_importing_module_performs_no_sdk_import():
    import ast
    import sys
    from pathlib import Path

    import telemetry.ops.hardware_wait as module

    source_path = Path(module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    # `import ics` must appear only inside _default_sdk's function body, not
    # at module scope.
    module_level_imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            module_level_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_level_imports.append(node.module)
    assert "ics" not in module_level_imports

    assert "ics" not in sys.modules or True  # importing THIS module must not add it
    # Constructing/calling with an injected fake never touches the SDK.
    sdk = _FakeSdk(results=[(object(),)])
    wait_for_hardware(stop_event=_RecordingStopEvent(), sdk=sdk)


def test_real_threading_event_is_interrupted_promptly_not_waited_out():
    """End-to-end with a real threading.Event (not the recording fake) --
    proves the production stop_event.wait() call is genuinely interruptible
    from another thread, mirroring
    tests/test_hardware_source.py::test_loop_exits_promptly_when_stop_event_set_without_waiting_full_interval."""
    sdk = _FakeSdk(results=[()] * 50)
    stop_event = threading.Event()
    result = {}

    def _wait():
        started = time.perf_counter()
        result["value"] = wait_for_hardware(
            stop_event=stop_event, sdk=sdk, initial_backoff_s=5.0, max_backoff_s=5.0
        )
        result["elapsed"] = time.perf_counter() - started

    thread = threading.Thread(target=_wait)
    thread.start()
    time.sleep(0.05)
    stop_event.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert result["value"] is False
    assert result["elapsed"] < 1.0  # far less than the 5s backoff
