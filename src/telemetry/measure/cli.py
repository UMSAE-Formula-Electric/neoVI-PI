"""
telemetry.measure.cli — the Phase 0 tracer-slice entry point.

`python -m telemetry.measure.cli --only-message M192_Command_Message` runs
the whole spine end to end: DBC load -> ID dictionary -> synthetic frame
source -> CFR encoder -> matching decoder (round-trip proof) -> per-ID
aggregation -> `00-REPORT.json` on disk. Mirrors `src/new_logger.py::main`'s
argparse shape and its `log()`-to-stderr / data-to-file convention — this
tool's report is a file artifact, not stdout, so stdout stays empty for any
future scripting that pipes this CLI's output.
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from telemetry.wire.decoder import Decoder
from telemetry.wire.dictionary import DbcLoadError, build_id_dictionary, load_dbc
from telemetry.wire.encoder import Encoder
from telemetry.synth.generator import SyntheticFrameSource
from telemetry.measure.config import GateConfig, GateConfigError, load_gate_config
from telemetry.measure.report import build_report, measure_stream, write_report_json

DBC_FILENAME = "epbr2026_DBC_v1.0.dbc"
# Repo-root-relative default: cli.py -> measure/ -> telemetry/ -> src/ -> repo root.
DEFAULT_DBC_PATH = str(Path(__file__).resolve().parents[3] / DBC_FILENAME)

REPORT_FILENAME = "00-REPORT.json"

DEFAULT_DURATION_S = 5.0
DEFAULT_BATCH_FRAMES = 100


def log(*args, **kwargs):
    print("[LOG]", *args, **kwargs, file=sys.stderr)


def main():
    p = argparse.ArgumentParser(
        description=(
            "Phase 0 compression-ratio measurement — runs the DBC-to-report "
            "spine (dictionary, synthetic frame source, CFR encoder/decoder, "
            "per-ID aggregation) and writes 00-REPORT.json."
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
        help=f"Directory to write {REPORT_FILENAME} into.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override the seed from gate.json for the synthetic generator.",
    )
    p.add_argument(
        "--gate-config",
        default=None,
        help="Path to gate.json (default: the phase's checked-in config).",
    )
    p.add_argument(
        "--bracket",
        default=None,
        choices=["best", "typical", "worst"],
        help="Entropy bracket to generate (default: gate.json's gating_bracket).",
    )
    p.add_argument(
        "--duration-s",
        type=float,
        default=DEFAULT_DURATION_S,
        help="Synthetic stream duration in seconds.",
    )
    p.add_argument(
        "--batch-frames",
        type=int,
        default=DEFAULT_BATCH_FRAMES,
        help="Target batch size (frames) for the CFR batching window.",
    )
    p.add_argument(
        "--only-message",
        action="append",
        default=None,
        dest="only_message",
        help="Restrict the stream to this message name (repeatable).",
    )
    args = p.parse_args()

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

    # Plan 00-04 made gate.json the single source of modelling assumptions, so
    # the generator is driven from it rather than from CLI defaults. --seed
    # still overrides, because reproducing a specific run is a debugging need.
    try:
        config = load_gate_config(args.gate_config or GateConfig.default_path())
    except GateConfigError as exc:
        log(f"[ERROR] {exc}")
        raise SystemExit(1) from exc
    if args.seed is not None:
        config = replace(config, seed=args.seed)
    bracket = args.bracket or config.thresholds.gating_bracket

    source = SyntheticFrameSource(
        db=db,
        dictionary=dictionary,
        config=config,
        bracket_name=bracket,
        duration_s=args.duration_s,
        only_message_names=args.only_message,
    )

    encoder = Encoder(dictionary)
    decoder = Decoder(dictionary)

    log(
        f"Measuring: duration={args.duration_s}s seed={config.seed} "
        f"bracket={bracket} batch_frames={args.batch_frames} "
        f"only_message={args.only_message or 'ALL'}"
    )

    measurement = measure_stream(source, encoder, decoder, args.batch_frames)

    meta = {
        "dbc_path": str(args.dbc),
        "dict_version": dictionary.dict_version,
        "seed": config.seed,
        "bracket": bracket,
        "duration_s": args.duration_s,
        "batch_frames": args.batch_frames,
        "only_message": args.only_message,
    }
    report = build_report(measurement, meta)

    out_path = Path(args.out_dir) / REPORT_FILENAME
    write_report_json(report, out_path)

    log(f"Wrote report: {out_path}")
    log(
        f"Aggregate: {measurement.total_frames} frames, "
        f"{measurement.total_bytes} bytes, "
        f"{measurement.bytes_per_frame:.3f} bytes/frame"
    )


if __name__ == "__main__":
    main()
