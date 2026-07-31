"""
telemetry.measure.report — stream measurement, per-ID aggregation, and the
D-16 tool-generated JSON report.

`measure_stream` is the prohibition-clause enforcement point (GATE-01's
"MUST NOT report a bytes/frame number for any encoding path that has not
been proven reversible"): every frame is encoded, then immediately decoded,
and only counted toward the aggregate/per-ID totals if the decoded frame is
byte-identical to the source frame. A round-trip mismatch raises rather than
silently excluding the frame from the count, since a silently-dropped
mismatch would produce a bytes/frame number for frames nobody actually
proved reversible.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from telemetry.wire.encoder import MAX_DELTA_T_US


@dataclass
class PerIdStats:
    """Aggregate stats for one `(frame_id, is_extended)` pair, keyed
    externally by `id_index` in `StreamMeasurement.per_id`."""

    frame_id: int
    is_extended: bool
    frame_count: int = 0
    total_bytes: int = 0

    @property
    def bytes_per_frame(self) -> float:
        return self.total_bytes / self.frame_count if self.frame_count else 0.0


@dataclass
class StreamMeasurement:
    """Accumulated measurement across the whole stream. `per_id` is keyed on
    `id_index` (not `frame_id` directly) to match the wire encoding's own
    keying and to keep per-ID state lookups consistent throughout the phase."""

    per_id: Dict[int, PerIdStats] = field(default_factory=dict)
    total_frames: int = 0
    total_bytes: int = 0

    @property
    def bytes_per_frame(self) -> float:
        return self.total_bytes / self.total_frames if self.total_frames else 0.0


def measure_stream(source, encoder, decoder, batch_frames: int) -> StreamMeasurement:
    """Walk `source` in batches of up to `batch_frames`, encode + immediately
    decode + assert byte-identity for every frame, and accumulate per-ID and
    aggregate totals.

    A batch is also closed early if the next frame's timestamp would exceed
    the encoder's `MAX_DELTA_T_US` window relative to the current batch's
    base timestamp — `batch_frames` is a target size, not a promise to ever
    hand the encoder a frame outside its representable window. This is a
    batching-policy safeguard only; it never loosens `Encoder.encode`'s own
    validation, which still raises `BatchWindowExceeded` for any frame this
    safeguard fails to keep in-window.
    """
    measurement = StreamMeasurement()
    batch: List = []
    batch_base_timestamp_us = None

    for frame in source.frames():
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
        stats.total_bytes += len(cfr)
        measurement.total_frames += 1
        measurement.total_bytes += len(cfr)


def build_report(measurement: StreamMeasurement, meta: dict) -> dict:
    """Assemble the plain-dict report body. `meta` carries run provenance
    (seed, duration, dbc path, message filter, timestamp, etc.) supplied by
    the caller — `report.py` does not know CLI argument names."""
    per_id = []
    for id_index, stats in sorted(measurement.per_id.items()):
        per_id.append(
            {
                "id_index": id_index,
                "frame_id": f"0x{stats.frame_id:X}",
                "is_extended": stats.is_extended,
                "frame_count": stats.frame_count,
                "total_bytes": stats.total_bytes,
                "bytes_per_frame": stats.bytes_per_frame,
            }
        )

    return {
        "meta": meta,
        "aggregate": {
            "total_frames": measurement.total_frames,
            "total_bytes": measurement.total_bytes,
            "bytes_per_frame": measurement.bytes_per_frame,
        },
        "per_id": per_id,
    }


def write_report_json(report: dict, path) -> None:
    """Write `report` as indented JSON to `path`, creating parent directories
    as needed."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
