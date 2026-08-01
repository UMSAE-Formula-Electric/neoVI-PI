"""
telemetry.measure.config -- typed loader and validator for the D-12 checked-in
modelling assumptions config (`.planning/phases/00-compression-ratio-gate/config/gate.json`).

For a gate built on modelled rather than captured data, the assumptions *are*
the result (D-12). This loader's whole job is to refuse to guess: an unknown
top-level key, a missing required key, an entropy bracket name outside
best/typical/worst, an out-of-range probability, a non-positive batch/window
value, or a bus_assignment.by_ecu value that does not resolve to a real bus
each raise `GateConfigError` naming the offending key and value -- never a
silent default (T-00-14).

`GateConfig.config_hash` is a short SHA-256 digest over the canonicalised
raw JSON, so every report a later plan produces can record exactly which
assumptions produced it (T-00-15).
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

VALID_BRACKET_NAMES = {"best", "typical", "worst"}

REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "seed",
    "duration_s",
    "batch_frames",
    "worst_n",
    "peak_windows_s",
    "entropy_brackets",
    "bus_targets",
    "bus_assignment",
    "default_period_ms_by_ecu",
    "thresholds",
}

REQUIRED_ENTROPY_BRACKET_KEYS = {
    "analog_dither_bits",
    "analog_dither_prob",
    "discrete_change_prob",
    "counter_increments",
}

REQUIRED_BUS_TARGET_KEYS = {"load_pct", "target_fps"}

REQUIRED_THRESHOLD_KEYS = {
    "baseline_budget_kbps",
    "gating_bracket",
    "max_average_kbps",
    "max_peak_kbps",
    "peak_window_s",
    "required_average_headroom_pct",
    "required_peak_headroom_pct",
}

# Sibling metadata keys tolerated (but not required) inside a config block
# whose remaining keys are meaningful data (bracket names, bus names, etc).
_BLOCK_METADATA_KEYS = {"_note", "confirmed", "method", "default_bus", "by_ecu"}


class GateConfigError(Exception):
    """Raised for any malformed, incomplete, or internally inconsistent
    gate.json -- this loader validates rather than defaults."""


@dataclass(frozen=True)
class EntropyBracket:
    """One D-02 entropy bracket's generator knobs."""

    analog_dither_bits: int
    analog_dither_prob: float
    discrete_change_prob: float
    counter_increments: bool


@dataclass(frozen=True)
class BusTarget:
    """One physical bus's assumed share of combined bus load."""

    load_pct: float
    target_fps: float


@dataclass(frozen=True)
class Thresholds:
    """The D-13 pre-registered pass condition, quoted verbatim in
    00-THRESHOLD.md so the prose and this machine-readable value cannot
    drift."""

    baseline_budget_kbps: float
    gating_bracket: str
    max_average_kbps: float
    max_peak_kbps: float
    peak_window_s: float
    required_average_headroom_pct: float
    required_peak_headroom_pct: float


@dataclass(frozen=True)
class GateConfig:
    """Every modelling assumption the gate's numbers depend on, parsed from
    one checked-in JSON file. `bus_assignment` and `default_period_ms_by_ecu`
    are exposed as plain dicts (not further-typed dataclasses) since their
    shape is a free-form audit record (method, confirmed flag, `_note`,
    measured-vs-modelled provenance) rather than a fixed field set."""

    schema_version: int
    seed: int
    duration_s: float
    batch_frames: int
    worst_n: int
    peak_windows_s: List[float]
    entropy_brackets: Dict[str, EntropyBracket]
    bus_targets: Dict[str, BusTarget]
    bus_assignment: dict
    default_period_ms_by_ecu: dict
    thresholds: Thresholds
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def default_path(cls) -> Path:
        """The checked-in config's path, resolved `Path(__file__).parent`-relative
        rather than hardcoded absolute (matches the codebase's existing
        `src/new_logger.py` path-construction convention)."""
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        return (
            repo_root
            / ".planning"
            / "phases"
            / "00-compression-ratio-gate"
            / "config"
            / "gate.json"
        )

    @property
    def config_hash(self) -> str:
        """Short SHA-256 digest over the canonicalised (sorted-key, no
        whitespace) raw JSON, so a report and the assumptions that produced
        it always travel together (T-00-15)."""
        canonical = json.dumps(self.raw, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _require_positive_number(value, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise GateConfigError(f"{name} must be a positive number, got {value!r}")


def _require_probability(value, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not (0.0 <= value <= 1.0):
        raise GateConfigError(f"{name} must be within 0.0-1.0, got {value!r}")


def _parse_entropy_bracket(name: str, value: object) -> EntropyBracket:
    if not isinstance(value, dict):
        raise GateConfigError(f"entropy_brackets.{name} must be a JSON object, got {value!r}")

    missing = REQUIRED_ENTROPY_BRACKET_KEYS - value.keys()
    if missing:
        raise GateConfigError(
            f"entropy_brackets.{name} missing required key(s): {sorted(missing)}"
        )

    bits = value["analog_dither_bits"]
    if not isinstance(bits, int) or isinstance(bits, bool) or bits < 0:
        raise GateConfigError(
            f"entropy_brackets.{name}.analog_dither_bits must be a non-negative "
            f"int, got {bits!r}"
        )

    _require_probability(
        value["analog_dither_prob"], f"entropy_brackets.{name}.analog_dither_prob"
    )
    _require_probability(
        value["discrete_change_prob"], f"entropy_brackets.{name}.discrete_change_prob"
    )

    counter_increments = value["counter_increments"]
    if not isinstance(counter_increments, bool):
        raise GateConfigError(
            f"entropy_brackets.{name}.counter_increments must be a boolean, "
            f"got {counter_increments!r}"
        )

    return EntropyBracket(
        analog_dither_bits=bits,
        analog_dither_prob=float(value["analog_dither_prob"]),
        discrete_change_prob=float(value["discrete_change_prob"]),
        counter_increments=counter_increments,
    )


def _parse_bus_target(name: str, value: object) -> BusTarget:
    if not isinstance(value, dict):
        raise GateConfigError(f"bus_targets.{name} must be a JSON object, got {value!r}")

    missing = REQUIRED_BUS_TARGET_KEYS - value.keys()
    if missing:
        raise GateConfigError(f"bus_targets.{name} missing required key(s): {sorted(missing)}")

    load_pct = value["load_pct"]
    if not isinstance(load_pct, (int, float)) or isinstance(load_pct, bool) or load_pct < 0:
        raise GateConfigError(
            f"bus_targets.{name}.load_pct must be a non-negative number, got {load_pct!r}"
        )
    _require_positive_number(value["target_fps"], f"bus_targets.{name}.target_fps")

    return BusTarget(load_pct=float(load_pct), target_fps=float(value["target_fps"]))


def _parse_thresholds(value: object) -> Thresholds:
    if not isinstance(value, dict):
        raise GateConfigError(f"thresholds must be a JSON object, got {value!r}")

    unknown = set(value.keys()) - REQUIRED_THRESHOLD_KEYS
    if unknown:
        raise GateConfigError(f"unknown key(s) in thresholds: {sorted(unknown)}")

    missing = REQUIRED_THRESHOLD_KEYS - value.keys()
    if missing:
        raise GateConfigError(f"thresholds missing required key(s): {sorted(missing)}")

    gating_bracket = value["gating_bracket"]
    if gating_bracket not in VALID_BRACKET_NAMES:
        raise GateConfigError(
            f"thresholds.gating_bracket must be one of {sorted(VALID_BRACKET_NAMES)}, "
            f"got {gating_bracket!r}"
        )

    for key in (
        "baseline_budget_kbps",
        "max_average_kbps",
        "max_peak_kbps",
        "peak_window_s",
        "required_average_headroom_pct",
        "required_peak_headroom_pct",
    ):
        _require_positive_number(value[key], f"thresholds.{key}")

    return Thresholds(
        baseline_budget_kbps=float(value["baseline_budget_kbps"]),
        gating_bracket=gating_bracket,
        max_average_kbps=float(value["max_average_kbps"]),
        max_peak_kbps=float(value["max_peak_kbps"]),
        peak_window_s=float(value["peak_window_s"]),
        required_average_headroom_pct=float(value["required_average_headroom_pct"]),
        required_peak_headroom_pct=float(value["required_peak_headroom_pct"]),
    )


def load_gate_config(path) -> GateConfig:
    """Parse and validate `path` into a `GateConfig`. Never falls back to a
    default on malformed input -- every failure raises `GateConfigError`
    naming the offending key and value."""
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except OSError as exc:
        raise GateConfigError(f"could not read gate config at {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GateConfigError(f"could not parse gate config at {path} as JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise GateConfigError(
            f"gate config at {path} must be a JSON object, got {type(raw).__name__}"
        )

    raw_keys = set(raw.keys())
    unknown_top_level = raw_keys - REQUIRED_TOP_LEVEL_KEYS
    if unknown_top_level:
        raise GateConfigError(f"unknown top-level key(s) in gate config: {sorted(unknown_top_level)}")

    missing_top_level = REQUIRED_TOP_LEVEL_KEYS - raw_keys
    if missing_top_level:
        raise GateConfigError(
            f"missing required top-level key(s) in gate config: {sorted(missing_top_level)}"
        )

    schema_version = raw["schema_version"]
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise GateConfigError(f"schema_version must be an int, got {schema_version!r}")

    seed = raw["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise GateConfigError(f"seed must be an int, got {seed!r}")

    _require_positive_number(raw["duration_s"], "duration_s")

    batch_frames = raw["batch_frames"]
    if not isinstance(batch_frames, int) or isinstance(batch_frames, bool) or batch_frames <= 0:
        raise GateConfigError(f"batch_frames must be a positive integer, got {batch_frames!r}")

    worst_n = raw["worst_n"]
    if not isinstance(worst_n, int) or isinstance(worst_n, bool) or worst_n <= 0:
        raise GateConfigError(f"worst_n must be a positive integer, got {worst_n!r}")

    peak_windows_s = raw["peak_windows_s"]
    if not isinstance(peak_windows_s, list) or not peak_windows_s:
        raise GateConfigError(f"peak_windows_s must be a non-empty list, got {peak_windows_s!r}")
    for window in peak_windows_s:
        _require_positive_number(window, "peak_windows_s entry")

    entropy_brackets_raw = raw["entropy_brackets"]
    if not isinstance(entropy_brackets_raw, dict):
        raise GateConfigError(f"entropy_brackets must be a JSON object, got {entropy_brackets_raw!r}")
    entropy_brackets: Dict[str, EntropyBracket] = {}
    for key, value in entropy_brackets_raw.items():
        if key == "_note":
            continue
        if key not in VALID_BRACKET_NAMES:
            raise GateConfigError(
                f"unknown entropy bracket name {key!r} in entropy_brackets; "
                f"must be one of {sorted(VALID_BRACKET_NAMES)}"
            )
        entropy_brackets[key] = _parse_entropy_bracket(key, value)
    missing_brackets = VALID_BRACKET_NAMES - entropy_brackets.keys()
    if missing_brackets:
        raise GateConfigError(f"missing entropy bracket(s): {sorted(missing_brackets)}")

    bus_targets_raw = raw["bus_targets"]
    if not isinstance(bus_targets_raw, dict):
        raise GateConfigError(f"bus_targets must be a JSON object, got {bus_targets_raw!r}")
    bus_targets: Dict[str, BusTarget] = {}
    for key, value in bus_targets_raw.items():
        if key in _BLOCK_METADATA_KEYS:
            continue
        bus_targets[key] = _parse_bus_target(key, value)
    if not bus_targets:
        raise GateConfigError("bus_targets must define at least one bus")

    bus_assignment = raw["bus_assignment"]
    if not isinstance(bus_assignment, dict):
        raise GateConfigError(f"bus_assignment must be a JSON object, got {bus_assignment!r}")

    by_ecu = bus_assignment.get("by_ecu")
    if not isinstance(by_ecu, dict):
        raise GateConfigError("bus_assignment.by_ecu must be a JSON object")
    for ecu, bus in by_ecu.items():
        if bus not in bus_targets:
            raise GateConfigError(
                f"bus_assignment.by_ecu[{ecu!r}] = {bus!r} is not a key of "
                f"bus_targets ({sorted(bus_targets)})"
            )

    default_bus = bus_assignment.get("default_bus")
    if default_bus is not None and default_bus not in bus_targets:
        raise GateConfigError(
            f"bus_assignment.default_bus = {default_bus!r} is not a key of "
            f"bus_targets ({sorted(bus_targets)})"
        )

    default_period_ms_by_ecu = raw["default_period_ms_by_ecu"]
    if not isinstance(default_period_ms_by_ecu, dict):
        raise GateConfigError(
            f"default_period_ms_by_ecu must be a JSON object, got {default_period_ms_by_ecu!r}"
        )

    thresholds = _parse_thresholds(raw["thresholds"])

    return GateConfig(
        schema_version=schema_version,
        seed=seed,
        duration_s=float(raw["duration_s"]),
        batch_frames=batch_frames,
        worst_n=worst_n,
        peak_windows_s=[float(w) for w in peak_windows_s],
        entropy_brackets=entropy_brackets,
        bus_targets=bus_targets,
        bus_assignment=bus_assignment,
        default_period_ms_by_ecu=default_period_ms_by_ecu,
        thresholds=thresholds,
        raw=raw,
    )
