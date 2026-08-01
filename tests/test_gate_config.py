"""
Assertions that the checked-in `config/gate.json` parses, is internally
consistent, and that the loader (`telemetry.measure.config`) rejects
malformed input rather than silently defaulting (T-00-14).

The checked-in file is the canonical source; malformed-input cases build a
mutated copy of it (never a hand-written literal) so these tests fail loudly
if the real file's shape ever drifts out from under them.
"""

import copy
import json

import pytest

from telemetry.measure.config import (
    GateConfig,
    GateConfigError,
    load_gate_config,
)


@pytest.fixture()
def base_config_dict():
    """A mutable copy of the checked-in gate.json, for malformed-input tests
    that need to start from a known-good document and break exactly one
    thing."""
    with open(GateConfig.default_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def _write_config(tmp_path, data):
    path = tmp_path / "gate.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# The checked-in config loads clean and is internally consistent
# ---------------------------------------------------------------------------


def test_default_config_loads_clean():
    config = load_gate_config(GateConfig.default_path())
    assert isinstance(config, GateConfig)


def test_bus_targets_keys_match_bus_assignment_values():
    config = load_gate_config(GateConfig.default_path())
    referenced_buses = set(config.bus_assignment["by_ecu"].values())
    default_bus = config.bus_assignment.get("default_bus")
    if default_bus is not None:
        referenced_buses.add(default_bus)
    assert referenced_buses <= set(config.bus_targets.keys()), (
        f"bus_assignment references bus(es) not present in bus_targets: "
        f"{referenced_buses - set(config.bus_targets.keys())}"
    )


def test_every_dbc_ecu_node_appears_in_by_ecu(dbc):
    # Read the node list from the `dbc` fixture rather than a literal list,
    # so this test fails loudly if epbr2026_DBC_v1.0.dbc's node set ever
    # changes shape.
    config = load_gate_config(GateConfig.default_path())
    ecu_names = {node.name for node in dbc.nodes}
    missing = ecu_names - set(config.bus_assignment["by_ecu"].keys())
    assert not missing, (
        f"bus_assignment.by_ecu is missing ECU node(s) present in the DBC: {missing}"
    )


def test_peak_windows_contains_required_scales():
    config = load_gate_config(GateConfig.default_path())
    for required in (0.1, 1.0, 10.0):
        assert required in config.peak_windows_s, (
            f"peak_windows_s is missing required scale {required}: {config.peak_windows_s}"
        )


def test_entropy_brackets_has_exactly_three_names():
    config = load_gate_config(GateConfig.default_path())
    assert set(config.entropy_brackets.keys()) == {"best", "typical", "worst"}


def test_thresholds_gating_bracket_is_typical():
    config = load_gate_config(GateConfig.default_path())
    assert config.thresholds.gating_bracket == "typical"


def test_bus_assignment_confirmed_flag_is_boolean_and_note_is_nonempty():
    config = load_gate_config(GateConfig.default_path())
    assert isinstance(config.bus_assignment["confirmed"], bool)
    assert config.bus_assignment["_note"].strip() != ""


def test_default_period_ms_by_ecu_note_is_nonempty():
    config = load_gate_config(GateConfig.default_path())
    assert config.default_period_ms_by_ecu["_note"].strip() != ""


def test_config_hash_stable_across_two_loads():
    first = load_gate_config(GateConfig.default_path())
    second = load_gate_config(GateConfig.default_path())
    assert first.config_hash == second.config_hash


def test_config_hash_changes_after_modification(tmp_path, base_config_dict):
    original_path = _write_config(tmp_path, base_config_dict)
    original = load_gate_config(original_path)

    mutated = copy.deepcopy(base_config_dict)
    mutated["seed"] = base_config_dict["seed"] + 1
    mutated_path = _write_config(tmp_path, mutated)
    changed = load_gate_config(mutated_path)

    assert original.config_hash != changed.config_hash


# ---------------------------------------------------------------------------
# Malformed input raises GateConfigError naming the offending key/value
# ---------------------------------------------------------------------------


def test_unknown_top_level_key_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["not_a_real_key"] = 1
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="not_a_real_key"):
        load_gate_config(path)


def test_missing_required_top_level_key_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    del mutated["thresholds"]
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="thresholds"):
        load_gate_config(path)


def test_unknown_entropy_bracket_name_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["entropy_brackets"]["extreme"] = mutated["entropy_brackets"]["worst"]
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="extreme"):
        load_gate_config(path)


def test_out_of_range_probability_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["entropy_brackets"]["typical"]["analog_dither_prob"] = 1.5
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="analog_dither_prob"):
        load_gate_config(path)


def test_non_positive_batch_frames_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["batch_frames"] = 0
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="batch_frames"):
        load_gate_config(path)


def test_non_positive_duration_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["duration_s"] = -1.0
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="duration_s"):
        load_gate_config(path)


def test_non_positive_peak_window_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["peak_windows_s"] = [0.1, 0.0, 10.0]
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="peak_windows_s"):
        load_gate_config(path)


def test_by_ecu_value_not_in_bus_targets_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["bus_assignment"]["by_ecu"]["VEHICLE_CONTROL_UNIT"] = "bus99"
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="bus99"):
        load_gate_config(path)


def test_unknown_threshold_gating_bracket_raises(tmp_path, base_config_dict):
    mutated = copy.deepcopy(base_config_dict)
    mutated["thresholds"]["gating_bracket"] = "worst_worst"
    path = _write_config(tmp_path, mutated)
    with pytest.raises(GateConfigError, match="gating_bracket"):
        load_gate_config(path)


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "gate.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(GateConfigError):
        load_gate_config(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(GateConfigError):
        load_gate_config(tmp_path / "does_not_exist.json")
