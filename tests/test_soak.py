"""
Requirements covered: CAP-02, CAP-03, CAP-05, CAP-06.
Filled by: 01-13, marked `slow`.

Drives `telemetry.synth.generator.SyntheticFrameSource` -- the full DBC, not
a filtered subset -- through the real `FanOut`, `ArchiveRunner`,
`ArchiveWriter`, and `TelemetryPipeline` over a `LoopbackLink`: the same
production assembly `telemetry.logger.cli` wires together, not the
measurement CLI (`telemetry.measure`). Asserts phase success criterion 3
directly: a sustained run at the combined target rate
(`config/gate.json`'s bus1+bus2 `target_fps`) drops zero frames on the
archive path, the archive read back afterwards holds exactly what was
captured, and every discard/filter/error counter is reported as a number
rather than as an absence of failure.

CAP-02's own sustained-rate figure is measured here on x86-64 dev hardware,
never on the CM4's Cortex-A72 target -- `01-VALIDATION.md` lists running
this same test on the CM4 as a manual-only verification this run does not
replace (see the achieved-fps assertion's own failure message below).

Per-stage timing (fan-out submit, archive flush/sync, telemetry encode /
framing / link send) is instrumented entirely from this test file, by
wrapping the bound methods and module-level functions the production code
already calls -- no production module is modified to add it. Every timed
distribution reports a median and a 95th-percentile figure, not a mean
alone, per `01-RESEARCH.md` Open Question 2: a mean hides exactly the kind
of intermittent stall this measurement exists to surface. The whole run is
emitted as one JSON record -- to the test's captured stdout and to a file
under `tmp_path` -- carrying its own machine/measured-on provenance, so a
timing figure pulled from this file never travels without the fact that it
was measured off-target (Phase 0 was bitten three separate times by prose
figures that outlived their own context).
"""

import json
import os
import platform
import queue
import statistics
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import pytest

from telemetry.archive.reader import recover_session
from telemetry.archive.runner import STOP, ArchiveRunner
from telemetry.archive.writer import ArchiveWriter
from telemetry.capture.fanout import CapturedFrame, FanOut
from telemetry.link.loopback import LoopbackLink
from telemetry.logger import pipeline as pipeline_module
from telemetry.logger.config import resolve_allowlist
from telemetry.logger.pipeline import TelemetryPipeline, TelemetryPipelineCounters
from telemetry.synth.generator import SyntheticFrameSource
from telemetry.wire.dictionary import build_id_dictionary
from telemetry.wire.encoder import Encoder

pytestmark = pytest.mark.slow

_DURATION_ENV_VAR = "TELEMETRY_SOAK_DURATION_S"
# Bounded default: long enough to be a genuine sustained-load run at the
# combined target rate (thousands of frames), short enough to stay well
# under a reasonable wall-clock budget on a laptop.
_DEFAULT_DURATION_S = 5.0


def _soak_duration_s() -> float:
    """`TELEMETRY_SOAK_DURATION_S` overrides the simulated bus duration this
    soak drives; unset falls back to `_DEFAULT_DURATION_S`. A malformed or
    non-positive override fails loudly naming the offending value, never
    silently falling back."""
    raw = os.environ.get(_DURATION_ENV_VAR)
    if raw is None:
        return _DEFAULT_DURATION_S
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"{_DURATION_ENV_VAR}={raw!r} is not a valid float number of seconds"
        ) from None
    if value <= 0:
        raise ValueError(f"{_DURATION_ENV_VAR}={raw!r} must be a positive number of seconds")
    return value


def _percentile(data, pct: int):
    """The `pct`-th percentile (1-99) of `data`, or `None` for an empty
    sample. `statistics.quantiles(data, n=100, method="inclusive")` returns
    99 cut points for the 1st through 99th percentile in order, so `pct`
    maps to index `pct - 1`; a single-point sample has nothing to
    interpolate between, so it is returned directly rather than raising."""
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    quantiles = statistics.quantiles(data, n=100, method="inclusive")
    index = max(1, min(99, pct)) - 1
    return quantiles[index]


def test_sustained_combined_bus_load_zero_archive_drops(
    dbc, gate_config, logger_config, tmp_path, monkeypatch
):
    """CAP-02/CAP-03/CAP-05/CAP-06, driven through the real production
    assembly at the combined bus target rate. See module docstring for the
    full contract; see `01-VALIDATION.md`'s Manual-Only Verifications table
    for what this run does NOT replace (the CM4 hardware run)."""
    duration_s = _soak_duration_s()
    combined_target_fps = sum(bt.target_fps for bt in gate_config.bus_targets.values())

    dictionary = build_id_dictionary(dbc, logger_config.dbc_path)
    allowlist = resolve_allowlist(logger_config, dbc)

    bus_to_channel = {c.bus: c.name for c in logger_config.channels}
    assert len(bus_to_channel) >= 2, "test assumes at least two configured buses"

    # Full DBC (no only_message_names filter) -- the combined bus load, not a
    # subset -- per 01-VALIDATION.md's explicit instruction that the load
    # must go through the production fan-out and writer.
    source = SyntheticFrameSource(dbc, dictionary, gate_config, "typical", duration_s=duration_s)
    # Each message's real assigned bus (from the D-03 rate model, not an
    # artificial alternation) maps onto its configured channel name, so the
    # split across MAIN/SENSOR is the same split the rate model itself used
    # to hit config/gate.json's per-bus target_fps.
    frame_key_to_channel = {
        (r.frame_id, r.is_extended): bus_to_channel[r.bus] for r in source.rates
    }

    stop_event = threading.Event()
    fan_out = FanOut(
        archive_maxsize=logger_config.archive.queue_depth,
        telemetry_maxsize=logger_config.telemetry.queue_depth,
        telemetry_allowlist=allowlist,
        stop_event=stop_event,
        dictionary=dictionary,
    )

    archive_path = tmp_path / "soak.mcap"
    channel_names = [c.name for c in logger_config.channels]
    writer = ArchiveWriter(
        archive_path,
        channel_names=channel_names,
        flush_every_records=logger_config.archive.flush_every_records,
        flush_every_s=logger_config.archive.flush_every_s,
    )
    # Archive writer flush/sync timing (ArchiveWriter._flush_and_sync is
    # ArchiveRunner's private, its cadence's own bookkeeping helper --
    # wrapped here rather than in production code; matches the existing
    # tests/test_archive_writer.py convention of assigning directly to
    # `writer._fsync` for the same purpose).
    flush_durations_s = []
    _original_flush_and_sync = writer._flush_and_sync

    def _timed_flush_and_sync():
        t0 = time.perf_counter()
        try:
            _original_flush_and_sync()
        finally:
            flush_durations_s.append(time.perf_counter() - t0)

    writer._flush_and_sync = _timed_flush_and_sync

    archive_runner = ArchiveRunner(fan_out.archive_queue, writer, fan_out.counters, stop_event)
    archive_runner.start()

    link = LoopbackLink()

    # Telemetry pipeline per-stage timing: encode (Encoder.encode), framing
    # (wire.batcher.pack_batch + framing.cobs_frame.frame, both imported as
    # bare names into telemetry.logger.pipeline's own module namespace, so
    # they must be patched there rather than on any instance), and send
    # (Link.send). All three wrap the exact bound method / module function
    # the production TelemetryPipeline already calls -- no production
    # module is modified to add this.
    encode_durations_s = []
    framing_durations_s = []
    send_durations_s = []

    encoder = Encoder(dictionary)
    _original_encode = encoder.encode

    def _timed_encode(frame, batch_base_timestamp_us):
        t0 = time.perf_counter()
        try:
            return _original_encode(frame, batch_base_timestamp_us)
        finally:
            encode_durations_s.append(time.perf_counter() - t0)

    encoder.encode = _timed_encode

    _original_pack_batch = pipeline_module.pack_batch
    _original_cobs_frame = pipeline_module.cobs_frame

    def _timed_pack_batch(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return _original_pack_batch(*args, **kwargs)
        finally:
            framing_durations_s.append(time.perf_counter() - t0)

    def _timed_cobs_frame(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return _original_cobs_frame(*args, **kwargs)
        finally:
            framing_durations_s.append(time.perf_counter() - t0)

    monkeypatch.setattr(pipeline_module, "pack_batch", _timed_pack_batch)
    monkeypatch.setattr(pipeline_module, "cobs_frame", _timed_cobs_frame)

    _original_send = link.send

    def _timed_send(data):
        t0 = time.perf_counter()
        try:
            return _original_send(data)
        finally:
            send_durations_s.append(time.perf_counter() - t0)

    link.send = _timed_send

    pipeline_counters = TelemetryPipelineCounters()
    pipeline = TelemetryPipeline(
        telemetry_queue=fan_out.telemetry_queue,
        encoder=encoder,
        link=link,
        dict_version=dictionary.dict_version,
        batch_frames=logger_config.telemetry.batch_frames,
        batch_max_age_s=logger_config.telemetry.batch_max_age_s,
        stop_event=stop_event,
        counters=pipeline_counters,
    )
    pipeline.start()

    expected_archive_records = []
    submit_durations_s = []

    wall_start = time.perf_counter()
    for raw_frame in source.frames():
        channel = frame_key_to_channel[(raw_frame.frame_id, raw_frame.is_extended)]
        captured = CapturedFrame(channel=channel, frame=raw_frame)
        t0 = time.perf_counter()
        fan_out.submit(captured)
        submit_durations_s.append(time.perf_counter() - t0)
        expected_archive_records.append((f"/can/{channel}", raw_frame))
    wall_submission_done = time.perf_counter()

    assert expected_archive_records, "expected at least one synthetic frame over duration_s"

    # Shutdown mirrors telemetry.logger.cli's own order (01-10-SUMMARY.md
    # Decisions Made): stop -> best-effort archive sentinel -> join both
    # consumer threads -> close the writer.
    stop_event.set()
    try:
        fan_out.archive_queue.put_nowait(STOP)
    except queue.Full:
        pass
    archive_runner.join(timeout=max(60.0, duration_s * 5))
    wall_archive_drained = time.perf_counter()
    pipeline.join(timeout=10.0)
    writer.close()

    assert not archive_runner.is_alive(), "archive runner did not stop within its join timeout"
    assert not pipeline.is_alive(), "telemetry pipeline did not stop within its join timeout"

    # --- CAP-03 / phase success criterion 3: zero archive-path drops -------
    assert fan_out.counters.archive_overflow is False, (
        "archive queue overflowed during the soak -- CAP-03's never-drop "
        "guarantee was violated at sustained load"
    )
    assert fan_out.counters.archive_write_failure is False, (
        "the archive writer failed mid-session -- see the critical log "
        "record ArchiveRunner emits with the failing frame's "
        "channel/id/timestamp"
    )
    # CAP-03's structural guarantee: the archive queue either accepts every
    # submission or the session stops (archive_overflow) -- there is no
    # separate quantity to count that isn't already covered by the two
    # flags asserted above (mirrors telemetry.logger.cli's own
    # _build_summary convention: "archive_drops is reported as a literal 0").
    archive_drops = 0

    # --- the archive read back holds exactly what was captured -------------
    recovered = recover_session(archive_path)
    assert not recovered.truncated
    assert recovered.record_count == len(expected_archive_records)
    assert Counter(recovered.records) == Counter(expected_archive_records), (
        "the archive's recovered (topic, frame) multiset does not exactly "
        "match what was submitted -- a reordering or a duplicated write "
        "would surface here even though the counts alone might still agree"
    )

    # --- every frame is accounted for on the telemetry side too ------------
    # FanOut.submit() puts every submitted frame into exactly one of these
    # buckets (telemetry/capture/fanout.py's own submit()): filtered by the
    # allowlist, rejected by the CAP-06 precheck (unknown id / too-long
    # payload / an unexpected error), or appended to the telemetry deque
    # (telemetry_enqueued -- incremented once per append regardless of
    # whether that append evicts an older, already-counted entry via
    # drop-oldest). telemetry_discard_count flags a *subset* of those
    # already-counted appends (which ones evicted something), not a fourth,
    # disjoint bucket, so it is reported separately below rather than
    # summed into this identity, which would otherwise double-count.
    assert (
        fan_out.counters.telemetry_filtered_count
        + fan_out.counters.telemetry_unknown_id_count
        + fan_out.counters.telemetry_payload_too_long_count
        + fan_out.counters.telemetry_unexpected_error_count
        + fan_out.counters.telemetry_enqueued
    ) == fan_out.counters.frames_submitted

    # --- every error counter is zero for a clean run ------------------------
    assert fan_out.counters.telemetry_unknown_id_count == 0
    assert fan_out.counters.telemetry_payload_too_long_count == 0
    assert fan_out.counters.telemetry_unexpected_error_count == 0
    assert pipeline_counters.unknown_id_count == 0
    assert pipeline_counters.payload_too_long_count == 0
    assert pipeline_counters.unexpected_cfr_error_count == 0
    assert pipeline_counters.framing_error_count == 0
    assert pipeline_counters.link_send_failure_count == 0
    assert pipeline_counters.frames_sent > 0, (
        "the telemetry path never sent a single frame -- the allowlisted "
        "messages never reached the pipeline, which would make this soak's "
        "CAP-05/CAP-06 telemetry-side numbers meaningless"
    )
    # telemetry_discard_count is deliberately NOT asserted to zero: the
    # telemetry path is drop-oldest by design (01-CONTEXT.md), so a nonzero
    # count here is expected behaviour, not a failure (critical constraint
    # 5) -- it is only ever reported, alongside both high-water marks.

    # --- achieved sustained rate meets the combined target ------------------
    wall_clock_s = wall_archive_drained - wall_start
    achieved_fps = fan_out.counters.frames_submitted / wall_clock_s
    assert achieved_fps >= combined_target_fps, (
        f"achieved {achieved_fps:.1f} fps over {wall_clock_s:.3f}s wall "
        f"clock ({fan_out.counters.frames_submitted} frames through "
        f"FanOut+ArchiveRunner), below the combined target of "
        f"{combined_target_fps:.1f} fps (config/gate.json bus1+bus2 "
        f"target_fps). This suite ran on {platform.platform()!r}, x86-64 "
        f"dev hardware -- NOT the CM4's Cortex-A72 target; no figure in "
        f"01-RESEARCH.md was measured on that core. A failure here means "
        f"this code is too slow to be worth carrying to hardware. "
        f"01-VALIDATION.md still lists running this same test on the CM4 "
        f"itself, recording the achieved fps/high-water marks/drop count "
        f"there, as a manual-only verification this run does not replace "
        f"-- a PASS here does not mean it is fast enough on hardware either."
    )

    print(
        json.dumps(
            {
                "frames_submitted": fan_out.counters.frames_submitted,
                "wall_clock_s": wall_clock_s,
                "achieved_fps": achieved_fps,
                "combined_target_fps": combined_target_fps,
                "archive_drops": archive_drops,
                "archive_high_water_mark": fan_out.counters.archive_high_water_mark,
                "telemetry_high_water_mark": fan_out.counters.telemetry_high_water_mark,
                "telemetry_discard_count": fan_out.counters.telemetry_discard_count,
                "telemetry_filtered_count": fan_out.counters.telemetry_filtered_count,
                "telemetry_enqueued": fan_out.counters.telemetry_enqueued,
                "pipeline_frames_sent": pipeline_counters.frames_sent,
                "pipeline_batches_sent": pipeline_counters.batches_sent,
                "pipeline_bytes_sent": pipeline_counters.bytes_sent,
            },
            indent=2,
        )
    )
