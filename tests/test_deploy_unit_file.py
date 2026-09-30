"""
tests/test_deploy_unit_file.py -- structural lint for deploy/telemetry-logger.service (OPS-01).

The stdlib INI-style parser is unsafe for a real systemd unit file: with its
default strict mode it raises on a second `After=` line -- completely valid,
common systemd syntax; with strict mode off it "succeeds" while silently
keeping only the LAST value of a repeated key and dropping the rest. Both
were proven live this project's own research session (see this phase's
RESEARCH.md, "Common Pitfalls"). This file hand-rolls a small, line-based
structural checker instead: `parse_unit_file` returns a mapping from section
name to an ORDERED LIST of (key, value) pairs -- a list, not a dict, so a
key repeated within one section survives intact rather than being silently
collapsed to its last occurrence.

This checker proves the shipped unit's SHAPE only: section names, that every
non-blank/non-comment line is well-formed, and specific known-important key
placements (the restart rate limit landing in the right section being the
single systemd mistake that fails silently rather than loudly). It
deliberately does NOT attempt semantic validation -- dependency graph
resolution, directive-specific type checking, or anything requiring
knowledge of what systemd actually does with a value. That is exactly what
real systemd's own verification tool is for, and it only runs on real
systemd; this file's own PLAN and its SUMMARY record a supplementary,
non-gating check performed against that real tool during this session.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from telemetry.logger.cli import _SHUTDOWN_JOIN_TIMEOUT_S

_REPO_ROOT = Path(__file__).resolve().parents[1]
UNIT_PATH = _REPO_ROOT / "deploy" / "telemetry-logger.service"
INSTALL_PATH = _REPO_ROOT / "deploy" / "install.sh"

_SECTION_RE = re.compile(r"^\[(?P<name>[^\]]+)\]$")


class UnitFileParseError(ValueError):
    """Raised naming the offending 1-based line number -- never a silent
    skip and never a silent default."""


def parse_unit_file(text: str) -> Dict[str, List[Tuple[str, str]]]:
    """Hand-rolled, line-based structural parser for a systemd unit file.

    Returns a mapping from section name to an ORDERED LIST of (key, value)
    pairs -- a list, not a dict, so a key repeated within one section
    (valid, common systemd syntax) survives intact rather than being
    silently collapsed to its last occurrence.

    Skips blank lines and comment lines (`#` or `;` as the first non-space
    character, per systemd's own unit-file comment syntax). Every other
    non-blank line must either open a section (`[Name]`) or be a
    `Key=Value` pair; a `Key=Value` line appearing before any section
    header, or a line matching neither shape, raises UnitFileParseError
    naming the 1-based line number -- never a silent skip.

    Deliberately does not attempt semantic validation of any kind (no
    dependency-graph resolution, no directive-specific type checking) --
    see the module docstring.
    """
    sections: Dict[str, List[Tuple[str, str]]] = {}
    current_section = None
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line[0] in "#;":
            continue
        section_match = _SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group("name")
            sections.setdefault(current_section, [])
            continue
        if "=" not in line:
            raise UnitFileParseError(
                f"line {lineno}: not a section header or Key=Value pair: "
                f"{raw_line!r}"
            )
        if current_section is None:
            raise UnitFileParseError(
                f"line {lineno}: Key=Value line before any [Section] "
                f"header: {raw_line!r}"
            )
        key, _, value = line.partition("=")
        sections[current_section].append((key.strip(), value.strip()))
    return sections


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def unit_text() -> str:
    return UNIT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def install_text() -> str:
    return INSTALL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed_unit(unit_text) -> Dict[str, List[Tuple[str, str]]]:
    return parse_unit_file(unit_text)


# ---------------------------------------------------------------------------
# The duplicate-key regression -- the entire reason this checker is
# hand-rolled rather than borrowed from the stdlib. Runs against a synthetic
# snippet defined here, not the shipped unit -- the shipped unit has exactly
# one `After=` line, so asserting duplicate preservation against it would
# pass vacuously and prove nothing.
# ---------------------------------------------------------------------------


def test_duplicate_key_within_one_section_survives_as_both_values():
    snippet = "[Unit]\nAfter=network.target\nAfter=local-fs.target\n"
    parsed = parse_unit_file(snippet)
    assert parsed["Unit"] == [
        ("After", "network.target"),
        ("After", "local-fs.target"),
    ]


# ---------------------------------------------------------------------------
# Structural well-formedness
# ---------------------------------------------------------------------------


def test_shipped_unit_file_parses_without_error(unit_text):
    parse_unit_file(unit_text)  # must not raise


def test_malformed_line_raises_naming_line_number():
    snippet = "[Unit]\nthis line is not a key value pair\n"
    with pytest.raises(UnitFileParseError, match="line 2"):
        parse_unit_file(snippet)


def test_key_value_line_before_any_section_header_raises():
    snippet = "Key=Value\n[Unit]\n"
    with pytest.raises(UnitFileParseError, match="line 1"):
        parse_unit_file(snippet)


def test_comment_and_blank_lines_are_skipped():
    snippet = "# a comment\n\n[Unit]\n; another comment style\nDescription=x\n"
    parsed = parse_unit_file(snippet)
    assert parsed["Unit"] == [("Description", "x")]


def test_shipped_unit_declares_exactly_three_sections_each_once(unit_text):
    section_headers = [
        line.strip()
        for line in unit_text.splitlines()
        if _SECTION_RE.match(line.strip())
    ]
    assert section_headers == ["[Unit]", "[Service]", "[Install]"]


# ---------------------------------------------------------------------------
# The restart rate limit's section placement -- the one systemd mistake
# that loads fine and fails silently rather than loudly.
# ---------------------------------------------------------------------------


def test_unit_section_contains_both_rate_limit_keys(parsed_unit):
    keys = [k for k, _ in parsed_unit["Unit"]]
    assert "StartLimitIntervalSec" in keys
    assert "StartLimitBurst" in keys


def test_service_section_key_set_excludes_rate_limit_keys(parsed_unit):
    keys = {k for k, _ in parsed_unit["Service"]}
    assert "StartLimitIntervalSec" not in keys
    assert "StartLimitBurst" not in keys


# ---------------------------------------------------------------------------
# [Service] shape
# ---------------------------------------------------------------------------


def test_service_declares_restart_always(parsed_unit):
    assert ("Restart", "always") in parsed_unit["Service"]


def test_service_declares_non_root_user(parsed_unit):
    users = [v for k, v in parsed_unit["Service"] if k == "User"]
    assert len(users) == 1
    assert users[0] not in ("root", "0")


def test_service_execstart_names_logger_cli_module(parsed_unit):
    exec_starts = [v for k, v in parsed_unit["Service"] if k == "ExecStart"]
    assert len(exec_starts) == 1
    assert "-m telemetry.logger.cli" in exec_starts[0]


def test_service_environment_sets_pythonpath_to_src(parsed_unit):
    environments = [v for k, v in parsed_unit["Service"] if k == "Environment"]
    assert any(v.strip() == "PYTHONPATH=src" for v in environments)


def test_stop_timeout_if_declared_is_at_least_twice_the_shutdown_join_timeout(
    parsed_unit,
):
    """Guards a FUTURE edit, not today's shipped file -- the shipped unit
    declares no TimeoutStopSec at all, so this assertion passes vacuously
    against the current text. It only becomes meaningful if a stop timeout
    is ever added: that value, in seconds, must be at least twice
    `_SHUTDOWN_JOIN_TIMEOUT_S` (imported from telemetry.logger.cli), or a
    systemd-issued SIGKILL could land before the logger's own shutdown
    joins finish, truncating the archive close."""
    timeouts = [v for k, v in parsed_unit["Service"] if k == "TimeoutStopSec"]
    if not timeouts:
        return
    assert len(timeouts) == 1
    declared_s = float(timeouts[0])
    assert declared_s >= 2 * _SHUTDOWN_JOIN_TIMEOUT_S


# ---------------------------------------------------------------------------
# [Install] shape
# ---------------------------------------------------------------------------


def test_install_declares_wantedby_multi_user_target(parsed_unit):
    assert ("WantedBy", "multi-user.target") in parsed_unit["Install"]


# ---------------------------------------------------------------------------
# No device-unit dependency -- the whole point of waiting-for-hardware is
# that the application, not systemd, owns that race.
# ---------------------------------------------------------------------------


def test_no_after_value_names_a_device_unit(parsed_unit):
    for pairs in parsed_unit.values():
        for key, value in pairs:
            if key != "After":
                continue
            for target in value.split():
                assert not target.endswith(
                    ".device"
                ), f"After= names a device unit: {target}"


# ---------------------------------------------------------------------------
# The unit and the installer must agree on the account name -- a mismatch
# fails only at first boot on the car.
# ---------------------------------------------------------------------------


def test_unit_user_account_name_appears_literally_in_install_script(
    parsed_unit, install_text
):
    user_value = next(v for k, v in parsed_unit["Service"] if k == "User")
    assert user_value in install_text


# ---------------------------------------------------------------------------
# install.sh shape
# ---------------------------------------------------------------------------


def test_install_script_sets_strict_mode(install_text):
    assert "set -euo pipefail" in install_text


def test_install_script_uses_mode_setting_install_invocation(install_text):
    assert re.search(r"install\s+-m\s+644", install_text)


def test_install_script_daemon_reload_precedes_enable(install_text):
    reload_offset = install_text.index("daemon-reload")
    enable_offset = install_text.index("enable --now")
    assert reload_offset < enable_offset
