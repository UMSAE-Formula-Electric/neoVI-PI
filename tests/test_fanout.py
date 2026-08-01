"""
Requirements covered: CAP-01, CAP-03, CAP-04, CAP-05, CAP-06.
Filled by: 01-07.

Will assert that a single fan-out implementation delivers every captured
frame to the archive path and the telemetry path independently, sustains
the target rate without ever letting a slow telemetry consumer block or
drop archive delivery, and counts every discard/error with frame context
instead of swallowing it.
"""

import pytest

pytest.skip(
    "Placeholder for 01-07: fan-out capture/discard-counting tests not yet written",
    allow_module_level=True,
)
