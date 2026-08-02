"""
telemetry.capture.replay_source — `ArchiveReplaySource`, the third
`FrameSource` implementation (D-08), and the real-log reader
`00-DECISION.md`'s worst-case bracket names as the deferred Phase 1
instrument for re-checking the compression gate against captured vehicle
traffic (`telemetry.wire.frame_source`'s own module docstring names this
reader as the deferred implementation the protocol was formalised for —
this is that).

Reads through `telemetry.archive.reader.recover_session` rather than
opening the `.mcap` file directly, for two load-bearing reasons: the
on-disk record layout is defined exactly once in `telemetry.archive.record`
and must not be re-derived here, and a session recorded on the car may well
be one that lost power mid-write — `recover_session` handles a footer-less
archive by construction, not by exception, so this module gets that for
free rather than having to special-case it.

Mirrors `telemetry.synth.generator.SyntheticFrameSource`'s shape:
`captured_frames()` is the primary generator, yielding frames tagged with
the channel they were archived under (recovered from the archive channel's
`/can/{name}` topic — the exact naming `telemetry.archive.writer.ArchiveWriter`
registers each channel under); `frames()` is a thin delegate yielding only
the `RawFrame` half, satisfying `telemetry.wire.frame_source.FrameSource` so
the encoder and the measurement tool need no change to consume this source.
An optional channel filter narrows what either generator yields without
altering anything that is yielded.
"""

from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional, Set

from telemetry.archive.reader import recover_session
from telemetry.capture.fanout import CapturedFrame
from telemetry.wire.frame_source import RawFrame

# `telemetry.archive.writer.ArchiveWriter` registers every channel under
# topic `/can/{channel_name}` (its own `_SCHEMA_NAME`/`register_channel`
# call) — this is the single place that convention is reversed back into a
# channel name, so a future change to the writer's topic naming has exactly
# one call site here to update, not a re-derived string format scattered
# across this module.
_TOPIC_PREFIX = "/can/"


def _channel_name_from_topic(topic: str) -> str:
    if not topic.startswith(_TOPIC_PREFIX):
        raise ValueError(
            f"archive topic {topic!r} does not start with the expected "
            f"{_TOPIC_PREFIX!r} prefix — this archive was not written by "
            f"telemetry.archive.writer.ArchiveWriter"
        )
    return topic[len(_TOPIC_PREFIX) :]


class ArchiveReplaySource:
    """Replays one captured session archive as a `FrameSource`.

    Reads the whole archive once, at construction time, through
    `recover_session` — a crashed (footer-less) session replays every
    record that was completely written before the crash, in the order it
    was written, and `truncated` reports whether the read stopped early
    rather than reaching a real end of stream.
    """

    def __init__(self, mcap_path, channel_filter: Optional[Iterable[str]] = None) -> None:
        self._mcap_path = Path(mcap_path)
        self._channel_filter: Optional[Set[str]] = (
            set(channel_filter) if channel_filter is not None else None
        )
        self._recovered = recover_session(self._mcap_path)

    @property
    def mcap_path(self) -> Path:
        return self._mcap_path

    @property
    def truncated(self) -> bool:
        """True if the underlying archive was recovered from a crashed
        (footer-less) session rather than a cleanly closed one — see
        `telemetry.archive.reader.RecoveredSession.truncated`."""
        return self._recovered.truncated

    @property
    def record_count(self) -> int:
        """Total records recovered from the archive, before any channel
        filter is applied — matches `RecoveredSession.record_count`."""
        return self._recovered.record_count

    def captured_frames(self) -> Iterator[CapturedFrame]:
        """Yield every recovered record as a `CapturedFrame`, tagged with
        the channel it was archived under, in the order it was written.
        Narrowed to `channel_filter`'s members when one was given at
        construction — this changes which frames are yielded, never any
        yielded frame's own fields."""
        for topic, frame in self._recovered.records:
            channel = _channel_name_from_topic(topic)
            if self._channel_filter is not None and channel not in self._channel_filter:
                continue
            yield CapturedFrame(channel=channel, frame=frame)

    def frames(self) -> Iterator[RawFrame]:
        """Thin delegate over `captured_frames()` that yields only the
        `RawFrame` half, satisfying
        `telemetry.wire.frame_source.FrameSource` so the CFR encoder and
        the measurement tool can consume a replayed archive with no change.
        Deliberately discards the channel tag, mirroring
        `telemetry.capture.hardware_source.HardwareFrameSource.frames()`."""
        for captured in self.captured_frames():
            yield captured.frame

    def measured_frame_rates_hz(self) -> Dict[str, float]:
        """Per-channel frames/s, computed from this archive's own recorded
        timestamps rather than any modelled rate.

        Every channel's rate is computed over the *same* denominator — the
        archive's own overall time span (its earliest to its latest
        recorded timestamp, across every channel this source yields) — so
        the per-channel rates sum exactly to the total frame count divided
        by that span; a per-channel-only span would not have that property.
        An archive with fewer than two frames has no measurable span and
        every rate reports 0.0.
        """
        counts_by_channel: Dict[str, int] = {}
        timestamps_us = []

        for captured in self.captured_frames():
            counts_by_channel[captured.channel] = (
                counts_by_channel.get(captured.channel, 0) + 1
            )
            timestamps_us.append(captured.frame.timestamp_us)

        if len(timestamps_us) < 2:
            return {channel: 0.0 for channel in counts_by_channel}

        span_s = (max(timestamps_us) - min(timestamps_us)) / 1_000_000.0
        if span_s <= 0:
            return {channel: 0.0 for channel in counts_by_channel}

        return {
            channel: count / span_s for channel, count in counts_by_channel.items()
        }
