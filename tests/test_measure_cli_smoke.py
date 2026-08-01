"""End-to-end smoke test for the measurement CLI.

This suite exists because plan 00-05 changed `SyntheticFrameSource.__init__`
and `cli.py` kept calling it with the old `seed=` keyword. Every unit test
still passed — nothing exercised `cli.py` — so a committed 00-02 acceptance
criterion ("the CLI exits 0 and writes 00-REPORT.json") silently regressed.

The point of these tests is coverage of the wiring itself, not of any layer's
behaviour: they run `main()` the way a person runs it and assert the spine
still holds together across plan boundaries.
"""

import json

import pytest

from telemetry.measure import cli


def _run_cli(monkeypatch, out_dir, *extra_args):
    argv = [
        "telemetry.measure.cli",
        "--only-message",
        "M192_Command_Message",
        "--duration-s",
        "1",
        "--out-dir",
        str(out_dir),
        *extra_args,
    ]
    monkeypatch.setattr("sys.argv", argv)
    cli.main()
    return out_dir / cli.REPORT_FILENAME


def test_cli_runs_end_to_end_and_writes_report(monkeypatch, tmp_path):
    """The 00-02 acceptance criterion, pinned so it cannot regress unseen."""
    report_path = _run_cli(monkeypatch, tmp_path)

    assert report_path.exists()
    report = json.loads(report_path.read_text())

    assert len(report["per_id"]) == 1
    stats = report["per_id"][0]
    assert stats["frame_count"] > 0
    assert stats["bytes_per_frame"] > 0


def test_cli_defaults_seed_and_bracket_from_gate_config(monkeypatch, tmp_path):
    """gate.json is the single source of modelling assumptions (plan 00-04),
    so an un-flagged run must report the config's values, not CLI defaults."""
    from telemetry.measure.config import GateConfig, load_gate_config

    config = load_gate_config(GateConfig.default_path())
    report = json.loads(_run_cli(monkeypatch, tmp_path).read_text())

    assert report["meta"]["seed"] == config.seed
    assert report["meta"]["bracket"] == config.thresholds.gating_bracket


def test_cli_seed_flag_overrides_gate_config(monkeypatch, tmp_path):
    """--seed still overrides, because reproducing a specific run is a
    debugging need that outlives any one config revision."""
    report = json.loads(
        _run_cli(monkeypatch, tmp_path, "--seed", "1234").read_text()
    )

    assert report["meta"]["seed"] == 1234


def test_cli_is_deterministic_for_a_fixed_seed(monkeypatch, tmp_path):
    """Determinism is a hard contract from plan 00-02 that every later
    measurement depends on."""
    first = json.loads(_run_cli(monkeypatch, tmp_path / "a", "--seed", "42").read_text())
    second = json.loads(_run_cli(monkeypatch, tmp_path / "b", "--seed", "42").read_text())

    assert first["aggregate"] == second["aggregate"]
    assert first["per_id"] == second["per_id"]


def test_cli_writes_nothing_to_stdout(monkeypatch, tmp_path, capsys):
    """Progress goes to stderr; the report is a file artifact. Keeps the CLI
    piping-safe, per its own module docstring."""
    _run_cli(monkeypatch, tmp_path)

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("bracket", ["best", "typical", "worst"])
def test_cli_accepts_every_entropy_bracket(monkeypatch, tmp_path, bracket):
    """All three plan 00-05 brackets are reachable from the command line."""
    report = json.loads(
        _run_cli(monkeypatch, tmp_path / bracket, "--bracket", bracket).read_text()
    )

    assert report["meta"]["bracket"] == bracket
    assert report["aggregate"]["total_frames"] > 0
