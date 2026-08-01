"""
Requirements covered: ARCH-01, and the Phase 0 D-14 real-traffic re-check.
Filled by: 01-12.

Will assert that a captured archive can be replayed as a frame source, and
will re-run Phase 0's compression-ratio gate against real captured traffic
rather than the modelled stream, closing the D-14 condition carried forward
from Phase 0's no-go.
"""

import pytest

pytest.skip(
    "Placeholder for 01-12: replay frame source and D-14 real-traffic re-check tests not yet written",
    allow_module_level=True,
)
