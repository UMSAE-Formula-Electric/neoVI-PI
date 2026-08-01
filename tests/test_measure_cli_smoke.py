"""End-to-end smoke test for the measurement CLI.

This suite exists because plan 00-05 changed `SyntheticFrameSource.__init__`
and `cli.py` kept calling it with the old `seed=` keyword. Every unit test
still passed — nothing exercised `cli.py` — so a committed 00-02 acceptance
criterion ("the CLI exits 0 and writes 00-REPORT.json") silently regressed.

The point of these tests is coverage of the wiring itself, not of any layer's
behaviour: they run `main()` the way a person runs it and assert the spine
still holds together across plan boundaries.

Plan 00-06 widened `cli.py` from a single-bracket, single-ID tracer entry
point to the full three-bracket, four-ablation matrix (`--brackets`/
`--ablations` replace the old single-value `--bracket`, and the report body
is now `{"meta": ..., "brackets": {best/typical/worst: {...}}}` rather than
the old flat `{"meta", "aggregate", "per_id"}` shape) — every assertion
below was updated to match that new report shape, preserving each test's
original intent (end-to-end wiring, gate.json defaulting, `--seed`
override, determinism, stdout cleanliness, and bracket coverage).
"""

import json

import pytest

from telemetry.measure import cli
from telemetry.measure.config import GateConfig, load_gate_config
from telemetry.measure.report import ABLATIONS
from telemetry.synth.entropy import BRACKET_NAMES


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
    return out_dir / cli.REPORT_JSON_FILENAME


def test_cli_runs_end_to_end_and_writes_report(monkeypatch, tmp_path):
    """The 00-02 acceptance criterion, pinned so it cannot regress unseen —
    widened for 00-06's full-matrix report shape."""
    report_path = _run_cli(monkeypatch, tmp_path)

    assert report_path.exists()
    assert (tmp_path / cli.REPORT_CSV_FILENAME).exists()
    report = json.loads(report_path.read_text())

    assert set(report["brackets"]) == set(BRACKET_NAMES)
    typical = report["brackets"]["typical"]
    assert set(typical["ablations"]) == set(ABLATIONS)
    assert len(typical["per_id"]) == 1
    stats = typical["per_id"][0]
    assert stats["frame_count"] > 0
    assert stats["clean_bytes_per_frame"] > 0


def test_cli_defaults_seed_and_duration_from_gate_config(monkeypatch, tmp_path):
    """gate.json is the single source of modelling assumptions (plan 00-04),
    so an un-flagged run must report the config's values, not CLI defaults."""
    config = load_gate_config(GateConfig.default_path())
    argv = [
        "telemetry.measure.cli",
        "--only-message",
        "M192_Command_Message",
        "--out-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr("sys.argv", argv)
    cli.main()
    report = json.loads((tmp_path / cli.REPORT_JSON_FILENAME).read_text())

    assert report["meta"]["seed"] == config.seed
    assert report["meta"]["seed_source"] == "gate_config"
    assert report["meta"]["duration_s"] == config.duration_s
    assert report["meta"]["duration_s_source"] == "gate_config"


@pytest.mark.parametrize("bad_duration", ["0", "-5"])
def test_cli_rejects_non_positive_duration_s(monkeypatch, tmp_path, bad_duration):
    """WR-05: config.py enforces duration_s > 0 for the file-based config
    (`_require_positive_number`); --duration-s must not be able to bypass
    that check and silently produce an empty-frame, all-zeros report."""
    argv = [
        "telemetry.measure.cli",
        "--only-message",
        "M192_Command_Message",
        "--duration-s",
        bad_duration,
        "--out-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert not (tmp_path / cli.REPORT_JSON_FILENAME).exists()


def test_cli_seed_flag_overrides_gate_config(monkeypatch, tmp_path):
    """--seed still overrides, because reproducing a specific run is a
    debugging need that outlives any one config revision. The override is
    recorded in meta so it cannot be mistaken for the committed config."""
    report = json.loads(
        _run_cli(monkeypatch, tmp_path, "--seed", "1234").read_text()
    )

    assert report["meta"]["seed"] == 1234
    assert report["meta"]["seed_source"] == "cli_override"


def test_cli_is_deterministic_for_a_fixed_seed(monkeypatch, tmp_path):
    """Determinism is a hard contract from plan 00-02 that every later
    measurement depends on."""
    first = json.loads(_run_cli(monkeypatch, tmp_path / "a", "--seed", "42").read_text())
    second = json.loads(_run_cli(monkeypatch, tmp_path / "b", "--seed", "42").read_text())

    assert first["brackets"] == second["brackets"]


def test_cli_writes_nothing_but_the_single_summary_line_to_stdout(monkeypatch, tmp_path, capsys):
    """Progress goes to stderr; the reports are file artifacts. Plan 00-06
    widens the contract to "exactly one summary line" (the gating bracket's
    all-in kbit/s against its ceiling) rather than a fully empty stdout."""
    _run_cli(monkeypatch, tmp_path)

    out_lines = capsys.readouterr().out.splitlines()
    assert len(out_lines) == 1
    assert "kbit/s" in out_lines[0]


@pytest.mark.parametrize("bracket", ["best", "typical", "worst"])
def test_cli_accepts_every_entropy_bracket(monkeypatch, tmp_path, bracket):
    """All three plan 00-05 brackets are reachable from the command line via
    the repeatable --brackets flag."""
    report = json.loads(
        _run_cli(monkeypatch, tmp_path / bracket, "--brackets", bracket).read_text()
    )

    assert set(report["brackets"]) == {bracket}
    assert report["brackets"][bracket]["aggregate"]["frame_count"] > 0
