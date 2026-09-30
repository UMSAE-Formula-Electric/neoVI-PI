"""
tests/test_runbook_coverage.py -- drift-proof coverage test for
`docs/runbook.md` (OPS-07).

**The discipline this test exists to enforce: every expected string is
derived from source at test-run time, never copied into this file as a
literal.** `HEARTBEAT_STATES` is imported from `telemetry.ops.heartbeat`;
`OpsConfig`'s field names are enumerated via `dataclasses.fields`, never
hand-listed; the archive completion-marker filename is read through
`load_logger_config` against the real checked-in `config/logger.json`; the
systemd unit name is derived from whichever single `*.service` file is
actually present in `deploy/`. A rename on any of those four sources fails
this test instead of silently letting the runbook drift out of date.

**What this test deliberately does NOT prove.** This is a content-presence
scan, not behavioural coverage (per this project's own recorded anti-pattern
of a fully green suite of file-content assertions standing in for something
that actually works). Passing means the runbook *mentions* the right state
names, config keys, table rows, and headings -- it does not mean a stranger
can actually follow the document end to end, and it does not run a single
command the document describes. That gap is exactly Task 1's
`<human-check>`; this test cannot stand in for it, and does not try to.
No prose grading, no word counts, no section-ordering assertions beyond the
one required heading.
"""

import dataclasses
import re
from pathlib import Path

import pytest

from telemetry.logger.config import LoggerConfig, OpsConfig, load_logger_config
from telemetry.ops.heartbeat import HEARTBEAT_STATES

# Repo-relative, resolved from this file -- never a hardcoded absolute path,
# following tests/conftest.py's existing `repo_root` convention.
_REPO_ROOT = Path(__file__).parent.parent
RUNBOOK_PATH = _REPO_ROOT / "docs" / "runbook.md"
DEPLOY_DIR = _REPO_ROOT / "deploy"

PI_BRING_UP_HEADING = "## Pi bring-up: the one hardware-only verification (OPS-01)"


def _read_runbook() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def _shipped_unit_filename() -> str:
    """The one `*.service` file actually present in `deploy/` -- derived,
    never restated. Fails loudly (not silently picks one) if zero or more
    than one exist, since either would mean this derivation is no longer
    unambiguous."""
    service_files = sorted(DEPLOY_DIR.glob("*.service"))
    assert len(service_files) == 1, (
        f"expected exactly one *.service file in {DEPLOY_DIR}, found "
        f"{[f.name for f in service_files]}"
    )
    return service_files[0].name


def test_runbook_file_exists():
    assert RUNBOOK_PATH.is_file(), f"{RUNBOOK_PATH} does not exist"


@pytest.mark.parametrize("state", HEARTBEAT_STATES)
def test_every_heartbeat_state_is_named_in_the_runbook(state):
    """Parameterised over the imported tuple: a sixth state landing in
    HEARTBEAT_STATES fails this test until the runbook covers it too."""
    assert state in _read_runbook(), (
        f"heartbeat state {state!r} (from telemetry.ops.heartbeat."
        f"HEARTBEAT_STATES) is not named anywhere in {RUNBOOK_PATH}"
    )


@pytest.mark.parametrize("field_name", [f.name for f in dataclasses.fields(OpsConfig)])
def test_every_opsconfig_field_name_is_named_in_the_runbook(field_name):
    """Enumerated via dataclasses.fields, never hand-listed -- a renamed or
    added OpsConfig field fails this test until the runbook is updated."""
    assert field_name in _read_runbook(), (
        f"OpsConfig field {field_name!r} is not named anywhere in "
        f"{RUNBOOK_PATH}"
    )


def test_archive_completion_marker_filename_is_named_in_the_runbook():
    config = load_logger_config(LoggerConfig.default_path())
    marker = config.archive.done_marker_filename
    assert marker in _read_runbook(), (
        f"the archive completion-marker filename {marker!r} (read via "
        f"load_logger_config from the checked-in config/logger.json) is "
        f"not named anywhere in {RUNBOOK_PATH}"
    )


@pytest.mark.parametrize("exit_code", [0, 1, 2, 3, 4])
def test_each_exit_code_appears_as_a_backticked_table_row(exit_code):
    """A bare digit search would match almost any prose (byte counts,
    thresholds, section numbers) and prove nothing -- require the code to be
    the first cell of a markdown table row, in backticks."""
    pattern = rf"^\|\s*`{exit_code}`\s*\|"
    assert re.search(pattern, _read_runbook(), re.MULTILINE), (
        f"exit code {exit_code} does not appear as a `{exit_code}` "
        f"markdown table row in {RUNBOOK_PATH}"
    )


def test_pi_bring_up_heading_appears_exactly_once():
    text = _read_runbook()
    assert text.count(PI_BRING_UP_HEADING) == 1, (
        f"expected the heading {PI_BRING_UP_HEADING!r} to appear exactly "
        f"once in {RUNBOOK_PATH}, found {text.count(PI_BRING_UP_HEADING)}"
    )


@pytest.mark.parametrize("requirement_id", ["OPS-01", "OPS-02", "OPS-03", "OPS-07"])
def test_each_requirement_id_is_cited(requirement_id):
    assert requirement_id in _read_runbook(), (
        f"{requirement_id} is not cited anywhere in {RUNBOOK_PATH}"
    )


def test_status_command_is_named_as_a_copyable_literal():
    """The real, copyable invocation -- there is no installed
    `telemetry-status` console script anywhere in this repository (no
    build pipeline, no entry_points), so the literal a reader can actually
    paste is `python -m telemetry.ops.cli`, not the informal docstring
    alias."""
    assert "python -m telemetry.ops.cli" in _read_runbook()


def test_install_script_path_is_named_as_a_copyable_literal():
    assert "deploy/install.sh" in _read_runbook()


def test_journal_invocation_names_the_actual_shipped_unit_filename():
    """The unit name in the runbook's `journalctl` invocation is derived
    from the filename of whichever unit is actually shipped in `deploy/`,
    never restated -- a renamed unit file fails this test until the
    runbook's journal commands are updated to match."""
    unit_filename = _shipped_unit_filename()
    text = _read_runbook()
    assert f"journalctl -u {unit_filename}" in text, (
        f"expected a 'journalctl -u {unit_filename}' invocation (derived "
        f"from the shipped unit filename) somewhere in {RUNBOOK_PATH}"
    )
