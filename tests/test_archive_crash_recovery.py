"""
Requirements covered: ARCH-02, ARCH-03.
Filled by: 01-05.

Will assert that a crash mid-write (via a SIGKILL proxy) still leaves every
pre-crash complete record recoverable from the archive. Scope limit: a
SIGKILL proxy does not prove fsync correctness by itself — the OS page
cache can survive a process kill even when fsync is broken — so this file's
automated cases are a necessary but not sufficient check; the physical
power-pull verification (01-VALIDATION.md Manual-Only) is what closes the
gap this file cannot.
"""

import pytest

pytest.skip(
    "Placeholder for 01-05: archive crash-recovery tests not yet written",
    allow_module_level=True,
)
