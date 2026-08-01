"""
telemetry.measure.report — stream measurement, per-ID/per-category/worst-N
aggregation, ablation comparison, peak-window bit rate, and the D-16
tool-generated JSON/CSV report.

`measure_stream` is the prohibition-clause enforcement point (GATE-01's
"MUST NOT report a bytes/frame number for any encoding path that has not
been proven reversible"): every frame is encoded, then immediately decoded,
and only counted toward the aggregate/per-ID totals if the decoded frame is
byte-identical to the source frame. A round-trip mismatch raises rather than
silently excluding the frame from the count, since a silently-dropped
mismatch would produce a bytes/frame number for frames nobody actually
proved reversible.

`build_report` never emits a pass/fail/go/no-go verdict anywhere in the
document (D-16): `meta.threshold_comparison` states the measured value, the
pre-registered threshold, the headroom percentage, and a boolean per
criterion — the go/no-go decision stays a human document.
"""

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from telemetry.measure.classify import CATEGORIES, _CATEGORY_DETECTION_METHODS, category_members
from telemetry.wire.encoder import MAX_DELTA_T_US, EncoderOptions
from telemetry.wire.overhead import overhead_breakdown

ABLATIONS = ("full", "no_sequence_byte", "raw_payload", "no_dictionary")

# D-10: every ablation isolates exactly one encoding mechanism's cost by
# flipping exactly one EncoderOptions field off the "full" default.
_ABLATION_OPTIONS = {
    "full": EncoderOptions(),
    "no_sequence_byte": EncoderOptions(sequence_byte=False),
    "raw_payload": EncoderOptions(payload_delta=False),
    "no_dictionary": EncoderOptions(use_dictionary=False),
}

# RESEARCH.md Assumption A2: structural detection on this DBC has surfaced
# candidates in categories a name-only heuristic would have reported as
# empty — flagged here so a report reader sees the caveat next to the
# numbers, not buried in a different document.
_CATEGORY_CAVEATS = {
    "checksum": (
        "RESEARCH.md Assumption A2: structural detection on this DBC has "
        "surfaced candidates suspected to include false positives "
        "(heartbeats, fault codes, SOH values) -- treat every member as a "
        "manual-review candidate, not a confirmed checksum."
    ),
}


def ablation_options(name: str) -> EncoderOptions:
    """The `EncoderOptions` for one D-10 ablation name."""
    try:
        return _ABLATION_OPTIONS[name]
    except KeyError:
        raise ValueError(
            f"unknown ablation name {name!r}; must be one of {ABLATIONS}"
        ) from None


@dataclass
class PerIdStats:
    """Aggregate stats for one `(frame_id, is_extended)` pair, keyed
    externally by `id_index` in `StreamMeasurement.per_id`. Only
    `frame_id`/`is_extended`/`frame_count`/`clean_encoded_bytes`/
    `all_in_encoded_bytes` are populated by `measure_stream` itself — the
    rest (`name`, `sender`, `bus`, `rate_source`, `rate_hz`, `categories`)
    are filled in afterward by `_enrich_per_id` from the rate model and the
    structural classifier, so `measure_stream` never has to import either."""

    frame_id: int
    is_extended: bool
    name: str = ""
    sender: Optional[str] = None
    bus: Optional[str] = None
    rate_source: Optional[str] = None
    rate_hz: float = 0.0
    categories: frozenset = field(default_factory=frozenset)
    frame_count: int = 0
    clean_encoded_bytes: int = 0
    all_in_encoded_bytes: float = 0.0

    @property
    def clean_bytes_per_frame(self) -> float:
        return self.clean_encoded_bytes / self.frame_count if self.frame_count else 0.0

    @property
    def all_in_bytes_per_frame(self) -> float:
        return self.all_in_encoded_bytes / self.frame_count if self.frame_count else 0.0


@dataclass(frozen=True)
class CategoryStats:
    """One worst-case category's rollup — always present for every name in
    `CATEGORIES`, even with zero members, so "no checksums observed" and
    "the classifier never looked" are never confused."""

    category: str
    message_count: int
    frame_count: int
    clean_bytes_per_frame: float
    all_in_bytes_per_frame: float
    note: str


@dataclass
class StreamMeasurement:
    """Accumulated measurement across the whole stream. `per_id` is keyed on
    `id_index` (not `frame_id` directly) to match the wire encoding's own
    keying. `batch_timeline` carries one `(last_frame_timestamp_us,
    all_in_bits_for_batch)` entry per processed batch — the D-11 batch-
    granularity peak-window input."""

    per_id: Dict[int, PerIdStats] = field(default_factory=dict)
    total_frames: int = 0
    total_bytes: int = 0  # clean payload bytes
    total_all_in_bytes: float = 0.0
    batch_timeline: List[Tuple[int, float]] = field(default_factory=list)

    @property
    def bytes_per_frame(self) -> float:
        return self.total_bytes / self.total_frames if self.total_frames else 0.0


def measure_stream(frames, encoder, decoder, batch_frames: int) -> StreamMeasurement:
    """Walk `frames` (any iterable of `RawFrame`) in batches of up to
    `batch_frames`, encode + immediately decode + assert byte-identity for
    every frame, and accumulate per-ID, aggregate, and batch-level totals.

    A batch is also closed early if the next frame's timestamp would exceed
    the encoder's `MAX_DELTA_T_US` window relative to the current batch's
    base timestamp — `batch_frames` is a target size, not a promise to ever
    hand the encoder a frame outside its representable window. This is a
    batching-policy safeguard only; it never loosens `Encoder.encode`'s own
    validation, which still raises `BatchWindowExceeded` for any frame this
    safeguard fails to keep in-window.

    Accepts a plain iterable (not a `FrameSource`) so a caller can
    materialize `list(source.frames())` once and pass the same list to
    `measure_stream` four times — once per D-10 ablation — with each call
    re-iterating the identical frames under a different `Encoder`/`Decoder`
    pair.
    """
    measurement = StreamMeasurement()
    batch: List = []
    batch_base_timestamp_us = None

    for frame in frames:
        if batch and (
            len(batch) >= batch_frames
            or frame.timestamp_us - batch_base_timestamp_us > MAX_DELTA_T_US
        ):
            _process_batch(batch, batch_base_timestamp_us, encoder, decoder, measurement)
            batch = []
            batch_base_timestamp_us = None

        if batch_base_timestamp_us is None:
            batch_base_timestamp_us = frame.timestamp_us
        batch.append(frame)

    if batch:
        _process_batch(batch, batch_base_timestamp_us, encoder, decoder, measurement)

    return measurement


def _process_batch(batch, batch_base_timestamp_us, encoder, decoder, measurement) -> None:
    batch_clean_bytes_by_id: Dict[int, int] = {}
    batch_clean_bytes_total = 0

    for frame in batch:
        cfr = encoder.encode(frame, batch_base_timestamp_us)
        recovered = decoder.decode(cfr, batch_base_timestamp_us)

        if recovered != frame:
            raise RuntimeError(
                f"round-trip mismatch for frame_id=0x{frame.frame_id:X}: "
                f"encoded {frame!r} but decoded {recovered!r} — refusing to "
                f"count an encoding that was not proven reversible"
            )

        id_index = encoder.dictionary.index_of(frame.frame_id, frame.is_extended)
        stats = measurement.per_id.setdefault(
            id_index,
            PerIdStats(frame_id=frame.frame_id, is_extended=frame.is_extended),
        )
        stats.frame_count += 1
        stats.clean_encoded_bytes += len(cfr)
        measurement.total_frames += 1
        measurement.total_bytes += len(cfr)

        batch_clean_bytes_by_id[id_index] = batch_clean_bytes_by_id.get(id_index, 0) + len(cfr)
        batch_clean_bytes_total += len(cfr)

    # D-06: the batch's all-in byte count is a shared, batch-level quantity
    # (one header, one CRC, one COBS worst-case expansion for the whole
    # batch) — apportioned back to each ID here in proportion to that ID's
    # share of the batch's clean bytes, since framing overhead is paid by
    # the batch as a whole, not by any one ID within it.
    breakdown = overhead_breakdown(batch_clean_bytes_total, len(batch))
    measurement.total_all_in_bytes += breakdown.all_in_bytes

    for id_index, id_clean_bytes in batch_clean_bytes_by_id.items():
        share = id_clean_bytes / batch_clean_bytes_total if batch_clean_bytes_total else 0.0
        measurement.per_id[id_index].all_in_encoded_bytes += share * breakdown.all_in_bytes

    last_timestamp_us = batch[-1].timestamp_us
    measurement.batch_timeline.append((last_timestamp_us, breakdown.all_in_bytes * 8))


def _window_label(window_s: float) -> str:
    """`0.1` -> `"0.1s"`, `1.0` -> `"1s"`, `10.0` -> `"10s"` — used both for
    `peak_windows`' return keys and for looking a specific threshold window
    back up out of that same dict, so the two can never drift apart."""
    if float(window_s).is_integer():
        return f"{int(window_s)}s"
    return f"{window_s}s"


def peak_windows(timeline: Sequence[Tuple[int, float]], windows_s: Sequence[float]) -> Dict[str, dict]:
    """For each window length in `windows_s`, the maximum bits/s observed
    over any sliding window of that length across `timeline` — a sequence
    of `(timestamp_us, bits)` pairs, one entry per batch, ordered
    ascending by timestamp (D-11: peaks are resolved at batch granularity).

    Returns `{label: {"peak_bits_per_s": float, "is_whole_run_average":
    bool}}`. A window whose length is at or beyond the run's total
    duration cannot be swept — it is reported as the whole-run average
    bit rate with `is_whole_run_average=True`, never silently reported as
    a peak (D-11).
    """
    result: Dict[str, dict] = {}

    if not timeline:
        for window_s in windows_s:
            result[_window_label(window_s)] = {
                "peak_bits_per_s": 0.0,
                "is_whole_run_average": False,
            }
        return result

    timestamps = [t for t, _ in timeline]
    total_bits = sum(bits for _, bits in timeline)
    run_duration_us = timestamps[-1] - timestamps[0]
    run_duration_s = run_duration_us / 1_000_000.0

    for window_s in windows_s:
        label = _window_label(window_s)
        window_us = window_s * 1_000_000.0

        if run_duration_us <= 0 or window_us >= run_duration_us:
            avg = total_bits / run_duration_s if run_duration_s > 0 else (total_bits / window_s)
            result[label] = {"peak_bits_per_s": avg, "is_whole_run_average": True}
            continue

        left = 0
        window_bits = 0.0
        peak_rate = 0.0
        for right in range(len(timeline)):
            window_bits += timeline[right][1]
            while timeline[right][0] - timeline[left][0] > window_us:
                window_bits -= timeline[left][1]
                left += 1
            rate = window_bits / window_s
            if rate > peak_rate:
                peak_rate = rate
        result[label] = {"peak_bits_per_s": peak_rate, "is_whole_run_average": False}

    return result


def bitrate_summary(total_bytes: float, duration_s: float) -> float:
    """`total_bytes` over `duration_s` as kbit/s — used for both the clean
    and all-in aggregate figures, and for every ablation's average rate."""
    if duration_s <= 0:
        return 0.0
    return (total_bytes * 8.0) / duration_s / 1000.0


def _enrich_per_id(measurement: StreamMeasurement, rates, classifications: dict) -> None:
    """Fill in `PerIdStats.name/sender/bus/rate_source/rate_hz` from the
    D-03 rate model and `.categories` from the D-04 structural classifier —
    joined on `(frame_id, is_extended)`, never re-derived here."""
    rate_by_key = {(r.frame_id, r.is_extended): r for r in rates}
    for stats in measurement.per_id.values():
        key = (stats.frame_id, stats.is_extended)
        rate = rate_by_key.get(key)
        if rate is not None:
            stats.name = rate.name
            stats.sender = rate.sender
            stats.bus = rate.bus
            stats.rate_source = rate.rate_source
            stats.rate_hz = rate.rate_hz
        msg_class = classifications.get(key)
        if msg_class is not None:
            stats.categories = msg_class.categories


def _serialize_per_id(stats: PerIdStats) -> dict:
    return {
        "frame_id": f"0x{stats.frame_id:X}",
        "is_extended": stats.is_extended,
        "name": stats.name,
        "sender": stats.sender,
        "bus": stats.bus,
        "rate_source": stats.rate_source,
        "rate_hz": stats.rate_hz,
        "categories": sorted(stats.categories),
        "frame_count": stats.frame_count,
        "clean_encoded_bytes": stats.clean_encoded_bytes,
        "clean_bytes_per_frame": stats.clean_bytes_per_frame,
        "all_in_bytes_per_frame": stats.all_in_bytes_per_frame,
    }


def _category_rollup(measurement: StreamMeasurement, classifications: dict) -> Dict[str, dict]:
    """Roll `measurement.per_id` up into the D-04 category buckets, keyed
    exactly by `CATEGORIES` — every key present, empty buckets included,
    each carrying a `note` naming the detection method (and, for
    `checksum`, the RESEARCH.md A2 manual-review caveat)."""
    members = category_members(classifications)
    stats_by_key = {(s.frame_id, s.is_extended): s for s in measurement.per_id.values()}

    result: Dict[str, dict] = {}
    for category in CATEGORIES:
        msg_classes = members[category]

        frame_count = 0
        clean_bytes = 0.0
        all_in_bytes = 0.0
        for msg_class in msg_classes:
            stats = stats_by_key.get((msg_class.frame_id, msg_class.is_extended))
            if stats is None:
                continue
            frame_count += stats.frame_count
            clean_bytes += stats.clean_encoded_bytes
            all_in_bytes += stats.all_in_encoded_bytes

        note = _CATEGORY_DETECTION_METHODS[category]
        caveat = _CATEGORY_CAVEATS.get(category)
        if caveat:
            note = f"{note} {caveat}"

        result[category] = asdict(
            CategoryStats(
                category=category,
                message_count=len(msg_classes),
                frame_count=frame_count,
                clean_bytes_per_frame=(clean_bytes / frame_count) if frame_count else 0.0,
                all_in_bytes_per_frame=(all_in_bytes / frame_count) if frame_count else 0.0,
                note=note,
            )
        )

    return result


def _threshold_comparison(brackets: Dict[str, dict], thresholds) -> List[dict]:
    """D-16: numbers and a boolean per pre-registered criterion, never a
    verdict string. Computed only for `thresholds.gating_bracket` — the
    bracket 00-THRESHOLD.md states decides the gate."""
    gating = brackets.get(thresholds.gating_bracket)
    if gating is None:
        return []

    average_measured = gating["aggregate"]["kbps_all_in"]
    average_entry = {
        "criterion": "average_kbps",
        "measured": average_measured,
        "threshold": thresholds.max_average_kbps,
        "headroom_pct": (
            (thresholds.max_average_kbps - average_measured) / thresholds.max_average_kbps * 100
        ),
        "within_threshold": average_measured <= thresholds.max_average_kbps,
    }

    peak_label = _window_label(thresholds.peak_window_s)
    peak_window = gating["peaks"]["windows"].get(peak_label, {"peak_bits_per_s": 0.0})
    peak_measured_kbps = peak_window["peak_bits_per_s"] / 1000.0
    peak_entry = {
        "criterion": "peak_kbps",
        "measured": peak_measured_kbps,
        "threshold": thresholds.max_peak_kbps,
        "headroom_pct": (
            (thresholds.max_peak_kbps - peak_measured_kbps) / thresholds.max_peak_kbps * 100
        ),
        "within_threshold": peak_measured_kbps <= thresholds.max_peak_kbps,
    }

    return [average_entry, peak_entry]


def build_report(
    ablation_measurements: Dict[str, Dict[str, StreamMeasurement]],
    duration_s: float,
    rates,
    classifications: dict,
    worst_n: int,
    peak_windows_s: Sequence[float],
    thresholds,
    meta: dict,
) -> dict:
    """Assemble the plain-dict report body from every bracket's four
    per-ablation `StreamMeasurement`s.

    `ablation_measurements` maps each bracket name to a dict keyed by
    `ABLATIONS`, each value the `StreamMeasurement` for that
    bracket/ablation combination over the *same* materialized frame list
    (only the encoder/decoder's `EncoderOptions` differs between
    ablations) — the `"full"` entry is what per-ID/category/worst-N/peaks
    are computed from; the other three contribute only to the `ablations`
    comparison table.

    `meta` is the caller-supplied run provenance (seed, dbc path, config
    hash, dict version, provenance/limitation statements, etc.) — this
    function only adds `threshold_comparison` to it, never removes or
    overwrites an existing key.
    """
    brackets: Dict[str, dict] = {}

    for bracket_name, per_ablation in ablation_measurements.items():
        full = per_ablation["full"]
        _enrich_per_id(full, rates, classifications)

        per_id_sorted = sorted(full.per_id.values(), key=lambda s: (s.frame_id, s.is_extended))
        per_id_json = [_serialize_per_id(s) for s in per_id_sorted]

        worst_entries = sorted(full.per_id.values(), key=lambda s: s.clean_bytes_per_frame, reverse=True)
        worst_n_json = [_serialize_per_id(s) for s in worst_entries[:worst_n]]

        categories_json = _category_rollup(full, classifications)

        batch_timestamps = [t for t, _ in full.batch_timeline]
        if len(batch_timestamps) >= 2:
            batch_period_us = (batch_timestamps[-1] - batch_timestamps[0]) / (len(batch_timestamps) - 1)
        elif batch_timestamps:
            batch_period_us = duration_s * 1_000_000.0
        else:
            batch_period_us = 0.0

        aggregate = {
            "frame_count": full.total_frames,
            "clean_bytes": full.total_bytes,
            "clean_bytes_per_frame": full.bytes_per_frame,
            "all_in_bytes_per_frame": (
                full.total_all_in_bytes / full.total_frames if full.total_frames else 0.0
            ),
            "kbps_clean": bitrate_summary(full.total_bytes, duration_s),
            "kbps_all_in": bitrate_summary(full.total_all_in_bytes, duration_s),
        }

        full_bytes_per_frame = full.bytes_per_frame
        ablations_json = {}
        for ablation_name in ABLATIONS:
            measurement = per_ablation[ablation_name]
            bpf = measurement.bytes_per_frame
            delta_pct = (
                (bpf - full_bytes_per_frame) / full_bytes_per_frame * 100
                if full_bytes_per_frame
                else 0.0
            )
            ablations_json[ablation_name] = {
                "bytes_per_frame": bpf,
                "kbps": bitrate_summary(measurement.total_bytes, duration_s),
                "delta_pct_vs_full": delta_pct,
                # measure_stream raises immediately on any round-trip
                # mismatch — reaching this point at all means every frame
                # in this ablation's measurement was already proven
                # reversible.
                "roundtrip_verified": True,
            }

        brackets[bracket_name] = {
            "aggregate": aggregate,
            "per_id": per_id_json,
            "categories": categories_json,
            "worst_n": worst_n_json,
            "ablations": ablations_json,
            "peaks": {
                "windows": peak_windows(full.batch_timeline, peak_windows_s),
                "peak_window_granularity": "batch",
                "batch_period_us": batch_period_us,
            },
        }

    merged_meta = dict(meta)
    merged_meta["threshold_comparison"] = _threshold_comparison(brackets, thresholds)

    return {"meta": merged_meta, "brackets": brackets}


CSV_FIELDNAMES = [
    "bracket",
    "frame_id_hex",
    "is_extended",
    "message_name",
    "sender",
    "bus",
    "rate_source",
    "rate_hz",
    "categories",
    "frame_count",
    "clean_bytes_per_frame",
    "all_in_bytes_per_frame",
    "kbps_all_in",
]


def write_report_csv(report: dict, path) -> None:
    """Emit one row per `(bracket, frame_id, is_extended)` — the CSV
    convention this codebase already uses (`src/new_logger.py`'s
    `csv.writer` with `newline=""`)."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(CSV_FIELDNAMES)
        for bracket_name, bracket in report["brackets"].items():
            for entry in bracket["per_id"]:
                rate_hz = entry["rate_hz"] or 0.0
                kbps_all_in = entry["all_in_bytes_per_frame"] * rate_hz * 8 / 1000.0
                writer.writerow(
                    [
                        bracket_name,
                        entry["frame_id"],
                        entry["is_extended"],
                        entry["name"],
                        entry["sender"],
                        entry["bus"],
                        entry["rate_source"],
                        rate_hz,
                        "|".join(entry["categories"]),
                        entry["frame_count"],
                        entry["clean_bytes_per_frame"],
                        entry["all_in_bytes_per_frame"],
                        kbps_all_in,
                    ]
                )


def write_report_json(report: dict, path) -> None:
    """Write `report` as indented JSON to `path`, creating parent
    directories as needed."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
