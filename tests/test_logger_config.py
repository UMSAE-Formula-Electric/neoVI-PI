"""
Assertions that the checked-in `config/logger.json` parses, is internally
consistent, and that the loader (`telemetry.logger.config`) rejects
malformed input rather than silently defaulting (T-01-02).

The checked-in file is the canonical source; malformed-input cases build a
mutated copy of it (never a hand-written literal) so these tests fail loudly
if the real file's shape ever drifts out from under them. Mirrors
`tests/test_gate_config.py`'s structure exactly, per `01-PATTERNS.md`.
"""

import copy
import dataclasses
import json

import pytest

from telemetry.logger.config import (
    LoggerConfig,
    LoggerConfigError,
    load_logger_config,
    resolve_allowlist,
)
from telemetry.wire.encoder import MAX_DELTA_T_US

EXPECTED_ALLOWLIST_SIZE = 12


@pytest.fixture()
def base_config_dict():
    """A mutable copy of the checked-in logger.json, for malformed-input
    tests that need to start from a known-good document and break exactly
    one thing."""
    with open(LoggerConfig.default_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def _write_config(tmp_path, data):
    path = tmp_path / "logger.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# The checked-in config loads clean and is internally consistent
# ---------------------------------------------------------------------------


def test_default_config_loads_clean():
    config = load_logger_config(LoggerConfig.default_path())
    assert isinstance(config, LoggerConfig)


def test_config_hash_is_stable_twelve_char_hex():
    first = load_logger_config(LoggerConfig.default_path())
    second = load_logger_config(LoggerConfig.default_path())
    assert first.config_hash == second.config_hash
    assert len(first.config_hash) == 12
    int(first.config_hash, 16)  # raises ValueError if not hex


def test_config_hash_changes_after_modification(tmp_path, base_config_dict):
    original_path = _write_config(tmp_path, base_config_dict)
    original = load_logger_config(original_path)

    mutated = copy.deepcopy(base_config_dict)
    mutated["capture"]["poll_interval_s"] = base_config_dict["capture"]["poll_interval_s"] * 2
    mutated_path = _write_config(tmp_path, mutated)
    changed = load_logger_config(mutated_path)

    assert original.config_hash != changed.config_hash


def test_dbc_path_is_absolute_and_exists():
    config = load_logger_config(LoggerConfig.default_path())
    assert config.dbc_path.is_absolute()
    assert config.dbc_path.exists()


def test_channel_netids_resolve_to_ics_module_attributes(logger_config):
    ics = pytest.importorskip("ics")
    for channel in logger_config.channels:
        assert hasattr(ics, channel.netid), (
            f"channel {channel.name!r} netid {channel.netid!r} has no "
            f"matching attribute on the ics module"
        )


def test_resolve_allowlist_returns_twelve_pairs_all_present_in_dbc(logger_config, dbc):
    resolved = resolve_allowlist(logger_config, dbc)
    assert len(resolved) == EXPECTED_ALLOWLIST_SIZE

    dbc_keys = {(m.frame_id, m.is_extended_frame) for m in dbc.messages}
    assert resolved <= dbc_keys


def test_resolve_allowlist_raises_for_unresolvable_name(logger_config, dbc):
    bad_telemetry = dataclasses.replace(
        logger_config.telemetry,
        allowlist=logger_config.telemetry.allowlist + ("Not_A_Real_Message",),
    )
    bad_config = dataclasses.replace(logger_config, telemetry=bad_telemetry)

    with pytest.raises(LoggerConfigError, match="Not_A_Real_Message"):
        resolve_allowlist(bad_config, dbc)


# ---------------------------------------------------------------------------
# Malformed input raises LoggerConfigError naming the offending key/value
# ---------------------------------------------------------------------------


def test_unknown_top_level_key_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["not_a_real_key"] = 1
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="not_a_real_key"):
        load_logger_config(path)


def test_missing_required_top_level_key_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    del mutated["archive"]
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="archive"):
        load_logger_config(path)


def test_schema_version_other_than_one_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["schema_version"] = 2
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="schema_version"):
        load_logger_config(path)


def test_dbc_path_not_found_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["dbc_path"] = "does_not_exist.dbc"
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="dbc_path"):
        load_logger_config(path)


def test_empty_channels_list_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["channels"] = []
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="channels"):
        load_logger_config(path)


def test_duplicate_channel_names_raise(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["channels"][1]["name"] = mutated["channels"][0]["name"]
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="duplicate"):
        load_logger_config(path)


def test_channel_netid_not_netid_prefixed_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["channels"][0]["netid"] = "HSCAN"
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="netid"):
        load_logger_config(path)


def test_archive_queue_depth_zero_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["archive"]["queue_depth"] = 0
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="queue_depth"):
        load_logger_config(path)


def test_archive_queue_depth_negative_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["archive"]["queue_depth"] = -1
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="queue_depth"):
        load_logger_config(path)


def test_archive_flush_every_records_zero_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["archive"]["flush_every_records"] = 0
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="flush_every_records"):
        load_logger_config(path)


def test_archive_flush_every_s_zero_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["archive"]["flush_every_s"] = 0
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="flush_every_s"):
        load_logger_config(path)


def test_telemetry_queue_depth_zero_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["telemetry"]["queue_depth"] = 0
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="queue_depth"):
        load_logger_config(path)


def test_telemetry_batch_frames_above_uint16_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["telemetry"]["batch_frames"] = 65536
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="batch_frames"):
        load_logger_config(path)


def test_telemetry_batch_max_age_at_cfr_ceiling_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    # At the ceiling exactly -- must be strictly below it, so this must raise.
    mutated["telemetry"]["batch_max_age_s"] = MAX_DELTA_T_US / 1_000_000
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="batch_max_age_s"):
        load_logger_config(path)


def test_telemetry_allowlist_empty_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["telemetry"]["allowlist"] = []
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="allowlist"):
        load_logger_config(path)


def test_telemetry_allowlist_duplicate_entry_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["telemetry"]["allowlist"].append(mutated["telemetry"]["allowlist"][0])
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="duplicate"):
        load_logger_config(path)


def test_link_kind_invalid_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["link"]["kind"] = "serial"
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="kind"):
        load_logger_config(path)


def test_link_udp_remote_port_out_of_range_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["link"]["udp"]["remote_port"] = 70000
    path = _write_config(tmp_path, mutated)
    with pytest.raises(LoggerConfigError, match="remote_port"):
        load_logger_config(path)


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "logger.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(LoggerConfigError):
        load_logger_config(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(LoggerConfigError):
        load_logger_config(tmp_path / "does_not_exist.json")


# ---------------------------------------------------------------------------
# Manifest cross-check (OPS-06): requirements.txt and requirements-dev.txt
# cannot drift apart on any package pinned in both.
# ---------------------------------------------------------------------------


def _parse_pinned_requirements(path):
    """Parse a requirements file into {package_name: version}, asserting
    every non-comment, non-blank line is an exact `==` pin."""
    pins = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line, f"{path.name}: line {line!r} is not an exact '==' pin"
        name, _, version = line.partition("==")
        name = name.strip()
        version = version.strip()
        assert name and version, f"{path.name}: line {line!r} is not an exact '==' pin"
        pins[name] = version
    return pins


def test_requirements_pinned(repo_root):
    runtime_pins = _parse_pinned_requirements(repo_root / "requirements.txt")
    dev_pins = _parse_pinned_requirements(repo_root / "requirements-dev.txt")

    assert runtime_pins, "requirements.txt must not be empty"
    assert dev_pins, "requirements-dev.txt must not be empty"

    shared = set(runtime_pins) & set(dev_pins)
    assert shared, "expected at least one package pinned in both manifests"

    for name in shared:
        assert runtime_pins[name] == dev_pins[name], (
            f"{name} is pinned to {runtime_pins[name]!r} in requirements.txt "
            f"but {dev_pins[name]!r} in requirements-dev.txt"
        )
