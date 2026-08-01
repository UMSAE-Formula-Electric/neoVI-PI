"""
Requirements covered: CAP-02.
Filled by: 01-13, marked `slow`.

Will assert sustained throughput at ~4,000 fps with zero archive drops,
driving telemetry.synth.generator.SyntheticFrameSource through the real
fan-out and writer (not the measurement CLI) and logging queue high-water
marks and discard counts.
"""

import pytest

pytest.skip(
    "Placeholder for 01-13: sustained-rate soak test not yet written",
    allow_module_level=True,
)
