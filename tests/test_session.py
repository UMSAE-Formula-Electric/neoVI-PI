"""
Requirements covered: ARCH-05, OPS-04.
Filled by: 01-05.

Will assert that each run lands in its own discrete session directory and
that a session's `.done` marker is written only after close+flush returns,
with ordering verified rather than assumed.
"""

import pytest

pytest.skip(
    "Placeholder for 01-05: session directory and done-marker ordering tests not yet written",
    allow_module_level=True,
)
