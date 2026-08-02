"""
telemetry.measure.cli — the Phase 0 full-matrix measurement entry point.

`python -m telemetry.measure.cli` runs the whole spine end to end for every
requested entropy bracket (default: all three — best/typical/worst) crossed
with every requested D-10 ablation (default: all four — full,
no_sequence_byte, raw_payload, no_dictionary): DBC load -> ID dictionary ->
D-03 rate model -> D-04 structural classification -> one materialized
synthetic frame list per bracket -> CFR encoder/decoder per ablation
(round-trip proof, every time) -> the full per-ID/per-category/worst-N/
ablation/peak-window report -> `00-REPORT.json` and `00-REPORT.csv` on disk.

Mirrors `src/new_logger.py::main`'s argparse shape and its `log()`-to-stderr
convention — this tool's reports are file artifacts, not stdout, so stdout
carries exactly one line (the gating-bracket summary) for any future
scripting that pipes this CLI's output.

`--frame-source archive` (plan 01-12) widens this CLI with a second frame
source alongside the default synthetic model: `--archive-path` names a
captured session `.mcap` archive, replayed through
`telemetry.capture.replay_source.ArchiveReplaySource`, and measured under a
single `"measured"` bracket instead of the three modelled entropy brackets.
This is the discharge of `00-DECISION.md`'s worst-case-bracket section's
named Phase 1 condition — "re-run this gate against real captured bus
traffic at Phase 1's first bench or track session" — the instrument half of
it, not the re-check itself: running this against a real bench/track
session still needs the car. The default (no `--frame-source` flag)
synthetic path is unchanged byte-for-byte; this is additive only.
"""

import argparse
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from telemetry.capture.replay_source import ArchiveReplaySource
from telemetry.wire.decoder import Decoder
from telemetry.wire.dictionary import DbcLoadError, build_id_dictionary, load_dbc
from telemetry.wire.encoder import Encoder
from telemetry.synth.entropy import BRACKET_NAMES
from telemetry.synth.generator import SyntheticFrameSource
from telemetry.synth.rates import assign_rates, bus_totals
from telemetry.measure.classify import classify_database
from telemetry.measure.config import GateConfig, GateConfigError, load_gate_config
from telemetry.measure.report import (
    ABLATIONS,
    StreamMeasurement,
    ablation_options,
    build_report,
    measure_stream,
    write_report_csv,
    write_report_json,
)

DBC_FILENAME = "epbr2026_DBC_v1.0.dbc"
# Repo-root-relative default: cli.py -> measure/ -> telemetry/ -> src/ -> repo root.
DEFAULT_DBC_PATH = str(Path(__file__).resolve().parents[3] / DBC_FILENAME)

REPORT_JSON_FILENAME = "00-REPORT.json"
REPORT_CSV_FILENAME = "00-REPORT.csv"

# The single bracket key a `--frame-source archive` run's report carries,
# in place of the three modelled entropy brackets (best/typical/worst) --
# there is no entropy model to bracket when the payload came from a real
# capture, so this name is deliberately not one of BRACKET_NAMES.
MEASURED_BRACKET_NAME = "measured"

FRAME_SOURCE_SYNTHETIC = "synthetic"
FRAME_SOURCE_ARCHIVE = "archive"
FRAME_SOURCES = (FRAME_SOURCE_SYNTHETIC, FRAME_SOURCE_ARCHIVE)


def log(*args, **kwargs):
    print("[LOG]", *args, **kwargs, file=sys.stderr)


def main():
    p = argparse.ArgumentParser(
        description=(
            "Phase 0 compression-ratio measurement — runs the DBC-to-report "
            "spine (dictionary, rate model, synthetic frame source, CFR "
            "encoder/decoder round-trip proof, per-ID/category/worst-N/"
            "ablation/peak aggregation) across every requested entropy "
            "bracket and D-10 ablation, and writes 00-REPORT.json/.csv."
        )
    )
    p.add_argument(
        "--dbc",
        default=DEFAULT_DBC_PATH,
        help="Path to the .dbc file (default: repo-root epbr2026_DBC_v1.0.dbc).",
    )
    p.add_argument(
        "--out-dir",
        default=".",
        help=f"Directory to write {REPORT_JSON_FILENAME}/{REPORT_CSV_FILENAME} into.",
    )
    p.add_argument(
        "--gate-config",
        default=None,
        help="Path to gate.json (default: the phase's checked-in config).",
    )
    p.add_argument(
        "--brackets",
        action="append",
        default=None,
        dest="brackets",
        choices=list(BRACKET_NAMES),
        help="Entropy bracket(s) to run (repeatable; default: all three).",
    )
    p.add_argument(
        "--ablations",
        action="append",
        default=None,
        dest="ablations",
        choices=list(ABLATIONS),
        help="D-10 ablation(s) to run (repeatable; default: all four).",
    )
    p.add_argument(
        "--duration-s",
        type=float,
        default=None,
        help="Override gate.json's duration_s (recorded in meta as an override).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override gate.json's seed (recorded in meta as an override).",
    )
    p.add_argument(
        "--only-message",
        action="append",
        default=None,
        dest="only_message",
        help="Restrict the stream to this message name (repeatable).",
    )
    p.add_argument(
        "--frame-source",
        default=FRAME_SOURCE_SYNTHETIC,
        dest="frame_source",
        choices=list(FRAME_SOURCES),
        help=(
            "Which FrameSource to measure: 'synthetic' (default, D-01 "
            "modelled stream) or 'archive' (a captured session .mcap "
            "replayed via ArchiveReplaySource -- requires --archive-path)."
        ),
    )
    p.add_argument(
        "--archive-path",
        default=None,
        dest="archive_path",
        help="Path to a captured session .mcap archive (required when --frame-source archive).",
    )
    p.add_argument(
        "--fail-on-roundtrip-mismatch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Abort and write no report on any round-trip mismatch (default: "
            "on). GATE-01 prohibits reporting a bytes/frame number for an "
            "encoding not proven reversible (T-00-23) -- round-trip "
            "verification stays mandatory regardless of this flag."
        ),
    )
    args = p.parse_args()

    if args.frame_source == FRAME_SOURCE_ARCHIVE and not args.archive_path:
        log(
            "[ERROR] --frame-source archive requires --archive-path naming "
            "a captured session .mcap file"
        )
        raise SystemExit(1)

    if args.duration_s is not None and args.duration_s <= 0:
        # WR-05: config.py's loader enforces duration_s > 0 for the
        # checked-in config (_require_positive_number), but argparse's bare
        # `type=float` lets --duration-s bypass that check entirely and
        # silently produce an empty-frame run. Fail the same way the
        # DbcLoadError/GateConfigError handling below does, rather than
        # letting a non-positive override reach the frame source.
        log(f"[ERROR] --duration-s must be a positive number, got {args.duration_s!r}")
        raise SystemExit(1)

    if not args.fail_on_roundtrip_mismatch:
        log(
            "[WARN] --no-fail-on-roundtrip-mismatch was requested, but "
            "GATE-01/T-00-23 prohibit reporting a bytes/frame number for any "
            "encoding not proven reversible in the same pass that counts it "
            "-- round-trip verification stays mandatory regardless of this "
            "flag."
        )

    try:
        db = load_dbc(args.dbc)
    except DbcLoadError as exc:
        log(f"[ERROR] {exc}")
        raise SystemExit(1) from exc
    log(f"Loaded DBC: {args.dbc}  ({len(db.messages)} messages)")

    dictionary = build_id_dictionary(db, dbc_path=args.dbc)
    log(
        f"Built ID dictionary: {len(dictionary.index)} entries, "
        f"dict_version={dictionary.dict_version}"
    )

    try:
        config = load_gate_config(args.gate_config or GateConfig.default_path())
    except GateConfigError as exc:
        log(f"[ERROR] {exc}")
        raise SystemExit(1) from exc

    seed_overridden = args.seed is not None
    if seed_overridden:
        config = replace(config, seed=args.seed)

    duration_overridden = args.duration_s is not None
    duration_s = args.duration_s if duration_overridden else config.duration_s

    ablations_to_run = args.ablations or list(ABLATIONS)

    classifications = classify_database(db)
    rates = assign_rates(db, config)

    start = time.monotonic()
    ablation_measurements: Dict[str, Dict[str, StreamMeasurement]] = {}

    archive_provenance = None  # set below only when --frame-source archive

    if args.frame_source == FRAME_SOURCE_ARCHIVE:
        # A real captured session replaces the per-bracket synthetic
        # materialization entirely: there is no entropy bracket to sweep
        # when the payload came from a real capture, so this is a single
        # bracket keyed MEASURED_BRACKET_NAME, run through every requested
        # ablation exactly as the synthetic path does.
        brackets_to_run = [MEASURED_BRACKET_NAME]
        archive_path = Path(args.archive_path).resolve()
        replay_source = ArchiveReplaySource(archive_path, channel_filter=None)
        frames = list(replay_source.frames())
        if not frames:
            log(f"[ERROR] archive at {archive_path} produced zero frames")
            raise SystemExit(1)
        log(
            f"Archive {archive_path}: replayed {len(frames)} frames "
            f"(elapsed={time.monotonic() - start:.2f}s)"
        )

        # duration_s/achieved_bus_fps come from the archive's own recorded
        # timestamps, never the modelled config -- a real capture's
        # duration and rate are facts of the log, not an assumption to
        # override from the command line.
        timestamps_us = [frame.timestamp_us for frame in frames]
        duration_s = (max(timestamps_us) - min(timestamps_us)) / 1_000_000.0
        if duration_s <= 0:
            log(
                f"[ERROR] archive at {archive_path} spans <= 0 seconds "
                f"({len(frames)} frame(s)) -- cannot compute a bit rate"
            )
            raise SystemExit(1)
        achieved_bus_fps = replay_source.measured_frame_rates_hz()

        archive_session_name = archive_path.parent.name
        archive_provenance = {
            "archive_path": str(archive_path),
            "archive_session_name": archive_session_name,
            "archive_truncated": replay_source.truncated,
            "archive_record_count": replay_source.record_count,
        }

        per_ablation: Dict[str, StreamMeasurement] = {}
        for ablation_name in ablations_to_run:
            options = ablation_options(ablation_name)
            encoder = Encoder(dictionary, options)
            decoder = Decoder(dictionary, options)
            measurement = measure_stream(frames, encoder, decoder, config.batch_frames)
            per_ablation[ablation_name] = measurement
            log(
                f"Bracket {MEASURED_BRACKET_NAME} ablation {ablation_name}: "
                f"{measurement.bytes_per_frame:.3f} clean bytes/frame "
                f"(elapsed={time.monotonic() - start:.2f}s)"
            )
        ablation_measurements[MEASURED_BRACKET_NAME] = per_ablation
    else:
        brackets_to_run = args.brackets or list(BRACKET_NAMES)
        achieved_bus_fps = bus_totals(rates)

        for bracket_name in brackets_to_run:
            # Materialized exactly once per bracket and reused across every
            # ablation below: the ablations are only comparable if they
            # encode identical frames, and regenerating the stream once per
            # ablation would multiply the dominant cost of the run.
            source = SyntheticFrameSource(
                db=db,
                dictionary=dictionary,
                config=config,
                bracket_name=bracket_name,
                duration_s=duration_s,
                only_message_names=args.only_message,
            )
            frames = list(source.frames())
            log(
                f"Bracket {bracket_name}: materialized {len(frames)} frames "
                f"(elapsed={time.monotonic() - start:.2f}s)"
            )

            per_ablation: Dict[str, StreamMeasurement] = {}
            for ablation_name in ablations_to_run:
                options = ablation_options(ablation_name)
                encoder = Encoder(dictionary, options)
                decoder = Decoder(dictionary, options)
                measurement = measure_stream(frames, encoder, decoder, config.batch_frames)
                per_ablation[ablation_name] = measurement
                log(
                    f"Bracket {bracket_name} ablation {ablation_name}: "
                    f"{measurement.bytes_per_frame:.3f} clean bytes/frame "
                    f"(elapsed={time.monotonic() - start:.2f}s)"
                )
            ablation_measurements[bracket_name] = per_ablation

    if args.frame_source == FRAME_SOURCE_ARCHIVE:
        duration_s_source = "archive_measured"
        input_provenance = (
            f"Every frame in this report was replayed from a captured "
            f"session archive at {archive_provenance['archive_path']} "
            f"(session {archive_provenance['archive_session_name']!r}) via "
            f"telemetry.capture.replay_source.ArchiveReplaySource -- this "
            f"is real captured vehicle traffic, not a modelled stream."
        )
        known_limitation = (
            "This report measures one recorded session's traffic, from one "
            "car, in one operating condition -- it is not a statistical "
            "claim about every possible drive. It discharges the "
            "instrument half of 00-DECISION.md's worst-case-bracket "
            "condition; whether this session's real entropy profile "
            "materially differs from the three-bracket synthetic model is "
            "for a human to read off the numbers below, against the "
            "unchanged pre-registered threshold."
        )
    else:
        duration_s_source = "cli_override" if duration_overridden else "gate_config"
        input_provenance = (
            f"Every frame in this report is synthesized from {DBC_FILENAME} "
            "(D-01) via telemetry.synth.generator.SyntheticFrameSource -- "
            "this is a modelled stream, not a captured vehicle log."
        )
        known_limitation = (
            "Payload entropy is exactly the quantity this gate exists to "
            "measure, and synthetic data has only the entropy the model in "
            "config/gate.json's entropy_brackets gives it. The compensating "
            "controls are the three-bracket (best/typical/worst) band "
            "reported below and the D-14 worst-case re-check against real "
            "captured traffic in Phase 1."
        )

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dbc_path": str(args.dbc),
        "dbc_message_count": len(db.messages),
        "dict_version": dictionary.dict_version,
        "config_hash": config.config_hash,
        "seed": config.seed,
        "seed_source": "cli_override" if seed_overridden else "gate_config",
        "duration_s": duration_s,
        "duration_s_source": duration_s_source,
        "frame_source": args.frame_source,
        "archive": archive_provenance,
        "batch_frames": config.batch_frames,
        "worst_n": config.worst_n,
        "peak_windows_s": config.peak_windows_s,
        "bus_assignment_confirmed": bool(config.bus_assignment.get("confirmed", False)),
        "bus_targets": {
            name: {"load_pct": bt.load_pct, "target_fps": bt.target_fps}
            for name, bt in config.bus_targets.items()
        },
        "achieved_bus_fps": achieved_bus_fps,
        "thresholds": {
            "baseline_budget_kbps": config.thresholds.baseline_budget_kbps,
            "gating_bracket": config.thresholds.gating_bracket,
            "max_average_kbps": config.thresholds.max_average_kbps,
            "max_peak_kbps": config.thresholds.max_peak_kbps,
            "peak_window_s": config.thresholds.peak_window_s,
            "required_average_headroom_pct": config.thresholds.required_average_headroom_pct,
            "required_peak_headroom_pct": config.thresholds.required_peak_headroom_pct,
        },
        "only_message": args.only_message,
        "fail_on_roundtrip_mismatch": args.fail_on_roundtrip_mismatch,
        "input_provenance": input_provenance,
        "known_limitation": known_limitation,
        "bus_assignment_caveat": (
            "bus_assignment.confirmed is False: epbr2026_DBC_v1.0.dbc names "
            "no per-message bus, so which of these messages rides bus1 vs "
            "bus2 is a human-authored ECU-sender proxy, not a DBC-derived "
            "fact (see config/gate.json bus_assignment._note)."
        ),
        "bus_targets_caveat": (
            "bus_targets.confirmed is False: the combined bus frame rate "
            "this run's rate model targets is prose-sourced "
            "(telemetry_conversation.md/CLAUDE.md), not derivable from "
            "epbr2026_DBC_v1.0.dbc -- see config/gate.json bus_targets._note "
            "and 00-THRESHOLD.md's pre-registered header-overhead risk."
        ),
        "default_period_confirmed": bool(
            config.default_period_ms_by_ecu.get("confirmed", False)
        ),
    }

    report = build_report(
        ablation_measurements=ablation_measurements,
        duration_s=duration_s,
        rates=rates,
        classifications=classifications,
        worst_n=config.worst_n,
        peak_windows_s=config.peak_windows_s,
        thresholds=config.thresholds,
        meta=meta,
    )

    out_dir = Path(args.out_dir)
    json_path = out_dir / REPORT_JSON_FILENAME
    csv_path = out_dir / REPORT_CSV_FILENAME
    write_report_json(report, json_path)
    write_report_csv(report, csv_path)

    log(f"Wrote reports: {json_path}, {csv_path}")

    gating_bracket = config.thresholds.gating_bracket
    if gating_bracket in report["brackets"]:
        summary_bracket = gating_bracket
    else:
        # A narrowed --brackets run (e.g. only "worst") never ran the
        # official gating bracket -- summarize whichever bracket did run
        # rather than KeyError, and say so explicitly so the one stdout
        # line is never mistaken for the gate's real go/no-go bracket.
        summary_bracket = next(iter(report["brackets"]))
        log(
            f"[WARN] gating_bracket={gating_bracket!r} was not run "
            f"(--brackets={brackets_to_run}) -- summarizing {summary_bracket!r} "
            f"instead; this is NOT the bracket 00-THRESHOLD.md gates on"
        )
    summary_kbps = report["brackets"][summary_bracket]["aggregate"]["kbps_all_in"]
    print(
        f"{summary_bracket} bracket all-in average: {summary_kbps:.2f} kbit/s "
        f"(ceiling: {config.thresholds.max_average_kbps:.2f} kbit/s)"
    )


if __name__ == "__main__":
    main()
