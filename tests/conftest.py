"""
Session-scoped fixtures shared across the Phase 0 test suite.

Loads epbr2026_DBC_v1.0.dbc exactly once per test session (cantools parsing
a 1,241-line DBC per test would be wasteful) and resolves it relative to
this file, following the `Path(__file__).parent` convention already used in
`src/new_logger.py` rather than a hardcoded absolute path.

An unreadable/malformed DBC is a hard failure here — per RESEARCH.md's
Security Domain section, this is a measurement tool for which the DBC *is*
the input, so this fixture intentionally does not reproduce
`new_logger.py`'s "decoding disabled" degraded-mode fallback.
"""

import cantools
import pytest
from pathlib import Path

DBC_FILENAME = "epbr2026_DBC_v1.0.dbc"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Repository root, resolved relative to this file (never hardcoded)."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def dbc_path(repo_root: Path) -> Path:
    """Path to the project's single DBC, resolved at the repository root."""
    return repo_root / DBC_FILENAME


@pytest.fixture(scope="session")
def dbc(dbc_path: Path):
    """The loaded cantools database, parsed exactly once per test session."""
    try:
        return cantools.database.load_file(str(dbc_path))
    except Exception as exc:
        raise RuntimeError(
            f"Could not load DBC at resolved path {dbc_path!s}: {exc}"
        ) from exc
