"""
telemetry.logger.config -- typed loader and validator for the runtime
`config/logger.json` (OPS-05): channels, DBC path, capture cadence, archive
durability cadence, telemetry queue sizing, link settings, the
twelve-message critical-channel allowlist, and (Phase 3, OPS-02/OPS-03) the
heartbeat/disk-threshold `ops` block all come from this one checked-in
file, with no source edit needed to change any of them.

Mirrors `telemetry.measure.config`'s shape element for element -- one config
idiom for this project, not two (`01-CONTEXT.md`). This loader's whole job
is to refuse to guess: an unknown top-level key, a missing required key, a
malformed channel entry, a non-positive queue depth or flush cadence, a
`batch_max_age_s` that would overflow the CFR delta-t field, or an
unrecognised link kind each raise `LoggerConfigError` naming the offending
key and value -- never a silent default (T-01-02).

`config/logger.json` lives at the repository root, deliberately NOT beside
`.planning/phases/00-compression-ratio-gate/config/gate.json`: `gate.json`
records Phase 0's modelling assumptions as a phase artifact, while
`logger.json` is runtime configuration the car reads at every boot.
`01-CONTEXT.md` fixes `config/logger.json` as the default path -- do not
"fix" this divergence.

`resolve_allowlist` is a separate free function, not folded into
`load_logger_config`, so that loading a config never requires importing
`cantools`: config parsing stays fast, importable without hardware or the
DBC, and independently testable (T-01-02's allowlist mitigation).

`LoggerConfig.config_hash` is a short SHA-256 digest over the canonicalised
raw JSON, so a session's archive can record exactly which config produced
it.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

from telemetry.wire.encoder import MAX_DELTA_T_US

REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "dbc_path",
    "channels",
    "capture",
    "archive",
    "telemetry",
    "link",
    "ops",
}

REQUIRED_CHANNEL_KEYS = {"name", "netid", "bus"}
REQUIRED_CAPTURE_KEYS = {"poll_interval_s", "hardware_serial"}
REQUIRED_ARCHIVE_KEYS = {
    "root_dir",
    "queue_depth",
    "flush_every_records",
    "flush_every_s",
    "done_marker_filename",
}
REQUIRED_TELEMETRY_KEYS = {"queue_depth", "batch_frames", "batch_max_age_s", "allowlist"}
REQUIRED_LINK_KEYS = {"kind", "udp"}
REQUIRED_UDP_KEYS = {
    "local_host",
    "local_port",
    "remote_host",
    "remote_port",
    "recv_bufsize",
}
REQUIRED_OPS_KEYS = {
    "heartbeat_path",
    "heartbeat_interval_s",
    "heartbeat_stale_after_s",
    "disk_warn_free_bytes",
    "disk_critical_free_bytes",
}

VALID_LINK_KINDS = {"loopback", "udp"}
VALID_SCHEMA_VERSION = 1

# telemetry.batch_frames feeds the (not-yet-built) batch header's frame_count
# field, a uint16 -- no prior in-repo module defines this constant to import,
# unlike MAX_DELTA_T_US below, so it is named here once.
_MAX_BATCH_FRAMES = 0xFFFF

# batch_max_age_s must stay strictly below this many seconds --
# wire/encoder.py's CFR delta_t_us header field is a uint16 microsecond
# count (MAX_DELTA_T_US), imported rather than restated (01-CONTEXT.md's
# #1 recorded anti-pattern).
_MAX_BATCH_MAX_AGE_S = MAX_DELTA_T_US / 1_000_000

# Repository root, resolved `Path(__file__).resolve()`-relative from
# src/telemetry/logger/config.py -- never a hardcoded absolute path.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class LoggerConfigError(Exception):
    """Raised for any malformed, incomplete, or internally inconsistent
    logger.json -- this loader validates rather than defaults."""


@dataclass(frozen=True)
class ChannelConfig:
    """One CAN channel's friendly label (carried into the archive and used
    as the MCAP channel topic), symbolic `ics` net-ID constant name, and
    logical bus label."""

    name: str
    netid: str
    bus: str


@dataclass(frozen=True)
class CaptureConfig:
    """Hardware polling cadence and device selection."""

    poll_interval_s: float
    hardware_serial: Optional[str]


@dataclass(frozen=True)
class ArchiveConfig:
    """Durable-archive location, sizing, and flush cadence (ARCH-04)."""

    root_dir: Path
    queue_depth: int
    flush_every_records: int
    flush_every_s: float
    done_marker_filename: str


@dataclass(frozen=True)
class TelemetryConfig:
    """Live-link queue sizing, batching, and the critical-channel allowlist
    (message names, resolved against the DBC by `resolve_allowlist`)."""

    queue_depth: int
    batch_frames: int
    batch_max_age_s: float
    allowlist: Tuple[str, ...]


@dataclass(frozen=True)
class UdpConfig:
    """A localhost UDP pair, always present regardless of `link.kind` so
    switching kinds never requires adding a block."""

    local_host: str
    local_port: int
    remote_host: str
    remote_port: int
    recv_bufsize: int


@dataclass(frozen=True)
class LinkConfig:
    """Which link implementation to use (`loopback` or `udp`; 01-04/01-08)
    plus the UDP settings."""

    kind: str
    udp: UdpConfig


@dataclass(frozen=True)
class OpsConfig:
    """Phase 3's unattended-operation surface (OPS-02/OPS-03): where the
    heartbeat status file lives and how often it is written/considered
    stale, plus the two-stage disk-space thresholds. `disk_warn_free_bytes`
    and `disk_critical_free_bytes` are defined here even though nothing
    consumes them until 03-02 -- this block's shape is architecture, and
    reopening the checked-in config a second time to add two fields would
    be pure churn. Both byte figures in `config/logger.json` are CHOSEN
    round defaults, not measurements: no real full-rate session's archive
    growth rate has been measured on this car (Phase 1's throughput figures
    are dev-box synthetic, per `.claude/CLAUDE.md`'s "never let a prose
    figure stand in for a measurement" rule) -- this docstring says so
    plainly rather than implying otherwise."""

    heartbeat_path: Path
    heartbeat_interval_s: float
    heartbeat_stale_after_s: float
    disk_warn_free_bytes: int
    disk_critical_free_bytes: int


@dataclass(frozen=True)
class LoggerConfig:
    """Every runtime setting the logger and ground station need, parsed
    from one checked-in JSON file."""

    schema_version: int
    dbc_path: Path
    channels: Tuple[ChannelConfig, ...]
    capture: CaptureConfig
    archive: ArchiveConfig
    telemetry: TelemetryConfig
    link: LinkConfig
    ops: OpsConfig
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def default_path(cls) -> Path:
        """The checked-in config's path, resolved `Path(__file__).resolve()`-
        relative rather than hardcoded absolute (matches
        `src/new_logger.py`'s existing path-construction convention)."""
        return _REPO_ROOT / "config" / "logger.json"

    @property
    def config_hash(self) -> str:
        """Short SHA-256 digest over the canonicalised (sorted-key, no
        whitespace) raw JSON, so a session's archive can record exactly
        which config produced it."""
        canonical = json.dumps(self.raw, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _require_positive_number(value, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise LoggerConfigError(f"{name} must be a positive number, got {value!r}")


def _require_positive_int(value, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LoggerConfigError(f"{name} must be a positive integer, got {value!r}")


def _require_non_empty_str(value, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LoggerConfigError(f"{name} must be a non-empty string, got {value!r}")


def _require_port(value, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not (0 <= value <= 65535):
        raise LoggerConfigError(f"{name} must be an integer in 0..65535, got {value!r}")


def _diff_keys(value: object, required: set, block_name: str) -> None:
    """Diff `value`'s keys against `required` in both directions, so unknown
    keys and missing keys each raise separately and each name the offending
    key -- the shared shape every per-block parser starts from."""
    if not isinstance(value, dict):
        raise LoggerConfigError(f"{block_name} must be a JSON object, got {value!r}")
    keys = set(value.keys())
    unknown = keys - required
    if unknown:
        raise LoggerConfigError(f"unknown key(s) in {block_name}: {sorted(unknown)}")
    missing = required - keys
    if missing:
        raise LoggerConfigError(f"{block_name} missing required key(s): {sorted(missing)}")


def _find_duplicates(values) -> List[str]:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _parse_channel(index: int, value: object) -> ChannelConfig:
    block_name = f"channels[{index}]"
    _diff_keys(value, REQUIRED_CHANNEL_KEYS, block_name)

    name = value["name"]
    _require_non_empty_str(name, f"{block_name}.name")

    netid = value["netid"]
    if not isinstance(netid, str) or not netid.startswith("NETID_"):
        raise LoggerConfigError(
            f"{block_name}.netid must be a 'NETID_'-prefixed string, got {netid!r}"
        )

    bus = value["bus"]
    _require_non_empty_str(bus, f"{block_name}.bus")

    return ChannelConfig(name=name, netid=netid, bus=bus)


def _parse_capture(value: object) -> CaptureConfig:
    _diff_keys(value, REQUIRED_CAPTURE_KEYS, "capture")

    _require_positive_number(value["poll_interval_s"], "capture.poll_interval_s")

    hardware_serial = value["hardware_serial"]
    if hardware_serial is not None and not isinstance(hardware_serial, str):
        raise LoggerConfigError(
            f"capture.hardware_serial must be null or a string, got {hardware_serial!r}"
        )

    return CaptureConfig(
        poll_interval_s=float(value["poll_interval_s"]),
        hardware_serial=hardware_serial,
    )


def _parse_archive(value: object) -> ArchiveConfig:
    _diff_keys(value, REQUIRED_ARCHIVE_KEYS, "archive")

    root_dir = value["root_dir"]
    _require_non_empty_str(root_dir, "archive.root_dir")

    _require_positive_int(value["queue_depth"], "archive.queue_depth")
    _require_positive_int(value["flush_every_records"], "archive.flush_every_records")
    _require_positive_number(value["flush_every_s"], "archive.flush_every_s")

    done_marker_filename = value["done_marker_filename"]
    _require_non_empty_str(done_marker_filename, "archive.done_marker_filename")

    return ArchiveConfig(
        # Resolved relative to the repository root, not the process cwd, so
        # the logger behaves identically launched from the repo root or a
        # systemd unit (Phase 3). Existence is deliberately NOT checked here
        # -- the session layer creates this directory.
        root_dir=(_REPO_ROOT / root_dir).resolve(),
        queue_depth=value["queue_depth"],
        flush_every_records=value["flush_every_records"],
        flush_every_s=float(value["flush_every_s"]),
        done_marker_filename=done_marker_filename,
    )


def _parse_telemetry(value: object) -> TelemetryConfig:
    _diff_keys(value, REQUIRED_TELEMETRY_KEYS, "telemetry")

    _require_positive_int(value["queue_depth"], "telemetry.queue_depth")

    batch_frames = value["batch_frames"]
    _require_positive_int(batch_frames, "telemetry.batch_frames")
    if batch_frames > _MAX_BATCH_FRAMES:
        raise LoggerConfigError(
            f"telemetry.batch_frames={batch_frames!r} must not exceed "
            f"{_MAX_BATCH_FRAMES} (the batch header's frame_count field is uint16)"
        )

    batch_max_age_s = value["batch_max_age_s"]
    _require_positive_number(batch_max_age_s, "telemetry.batch_max_age_s")
    if batch_max_age_s >= _MAX_BATCH_MAX_AGE_S:
        raise LoggerConfigError(
            f"telemetry.batch_max_age_s={batch_max_age_s!r} must be strictly "
            f"below the CFR delta-t ceiling of {_MAX_BATCH_MAX_AGE_S!r}s "
            f"(wire/encoder.py MAX_DELTA_T_US={MAX_DELTA_T_US})"
        )

    allowlist = value["allowlist"]
    if not isinstance(allowlist, list) or not allowlist:
        raise LoggerConfigError(
            f"telemetry.allowlist must be a non-empty list, got {allowlist!r}"
        )
    for entry in allowlist:
        if not isinstance(entry, str) or not entry.strip():
            raise LoggerConfigError(
                f"telemetry.allowlist entries must be non-empty strings, got {entry!r}"
            )
    duplicates = _find_duplicates(allowlist)
    if duplicates:
        raise LoggerConfigError(
            f"telemetry.allowlist contains duplicate entry/entries: {duplicates}"
        )

    return TelemetryConfig(
        queue_depth=value["queue_depth"],
        batch_frames=batch_frames,
        batch_max_age_s=float(batch_max_age_s),
        allowlist=tuple(allowlist),
    )


def _parse_udp(value: object) -> UdpConfig:
    _diff_keys(value, REQUIRED_UDP_KEYS, "link.udp")

    _require_non_empty_str(value["local_host"], "link.udp.local_host")
    _require_port(value["local_port"], "link.udp.local_port")
    _require_non_empty_str(value["remote_host"], "link.udp.remote_host")
    _require_port(value["remote_port"], "link.udp.remote_port")
    _require_positive_int(value["recv_bufsize"], "link.udp.recv_bufsize")

    return UdpConfig(
        local_host=value["local_host"],
        local_port=value["local_port"],
        remote_host=value["remote_host"],
        remote_port=value["remote_port"],
        recv_bufsize=value["recv_bufsize"],
    )


def _parse_link(value: object) -> LinkConfig:
    _diff_keys(value, REQUIRED_LINK_KEYS, "link")

    kind = value["kind"]
    if kind not in VALID_LINK_KINDS:
        raise LoggerConfigError(
            f"link.kind must be one of {sorted(VALID_LINK_KINDS)}, got {kind!r}"
        )

    udp = _parse_udp(value["udp"])

    return LinkConfig(kind=kind, udp=udp)


def _parse_ops(value: object) -> OpsConfig:
    _diff_keys(value, REQUIRED_OPS_KEYS, "ops")

    heartbeat_path = value["heartbeat_path"]
    _require_non_empty_str(heartbeat_path, "ops.heartbeat_path")

    heartbeat_interval_s = value["heartbeat_interval_s"]
    _require_positive_number(heartbeat_interval_s, "ops.heartbeat_interval_s")

    heartbeat_stale_after_s = value["heartbeat_stale_after_s"]
    _require_positive_number(heartbeat_stale_after_s, "ops.heartbeat_stale_after_s")

    disk_warn_free_bytes = value["disk_warn_free_bytes"]
    _require_positive_int(disk_warn_free_bytes, "ops.disk_warn_free_bytes")

    disk_critical_free_bytes = value["disk_critical_free_bytes"]
    _require_positive_int(disk_critical_free_bytes, "ops.disk_critical_free_bytes")

    # A stale threshold at or below the write cadence would flag a healthy
    # logger as dead -- strictly greater, not merely different.
    if heartbeat_stale_after_s <= heartbeat_interval_s:
        raise LoggerConfigError(
            f"ops.heartbeat_stale_after_s={heartbeat_stale_after_s!r} must be "
            f"strictly greater than ops.heartbeat_interval_s="
            f"{heartbeat_interval_s!r}"
        )

    # An inverted pair would mean "critical" fires before "warn" ever does,
    # inverting the two-stage semantics OPS-03 depends on.
    if disk_critical_free_bytes >= disk_warn_free_bytes:
        raise LoggerConfigError(
            f"ops.disk_critical_free_bytes={disk_critical_free_bytes!r} must "
            f"be strictly less than ops.disk_warn_free_bytes="
            f"{disk_warn_free_bytes!r}"
        )

    return OpsConfig(
        # Resolved relative to the repository root, same convention as
        # archive.root_dir -- existence is deliberately NOT checked here,
        # the publisher creates the parent directory itself.
        heartbeat_path=(_REPO_ROOT / heartbeat_path).resolve(),
        heartbeat_interval_s=float(heartbeat_interval_s),
        heartbeat_stale_after_s=float(heartbeat_stale_after_s),
        disk_warn_free_bytes=disk_warn_free_bytes,
        disk_critical_free_bytes=disk_critical_free_bytes,
    )


def load_logger_config(path) -> LoggerConfig:
    """Parse and validate `path` into a `LoggerConfig`. Never falls back to
    a default on malformed input -- every failure raises `LoggerConfigError`
    naming the offending key and value."""
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except OSError as exc:
        raise LoggerConfigError(f"could not read logger config at {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LoggerConfigError(
            f"could not parse logger config at {path} as JSON: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise LoggerConfigError(
            f"logger config at {path} must be a JSON object, got {type(raw).__name__}"
        )

    raw_keys = set(raw.keys())
    unknown_top_level = raw_keys - REQUIRED_TOP_LEVEL_KEYS
    if unknown_top_level:
        raise LoggerConfigError(
            f"unknown top-level key(s) in logger config: {sorted(unknown_top_level)}"
        )

    missing_top_level = REQUIRED_TOP_LEVEL_KEYS - raw_keys
    if missing_top_level:
        raise LoggerConfigError(
            f"missing required top-level key(s) in logger config: {sorted(missing_top_level)}"
        )

    schema_version = raw["schema_version"]
    if schema_version != VALID_SCHEMA_VERSION:
        raise LoggerConfigError(
            f"schema_version must be {VALID_SCHEMA_VERSION}, got {schema_version!r}"
        )

    dbc_path_raw = raw["dbc_path"]
    _require_non_empty_str(dbc_path_raw, "dbc_path")
    dbc_path = (_REPO_ROOT / dbc_path_raw).resolve()
    if not dbc_path.exists():
        raise LoggerConfigError(f"dbc_path resolves to {dbc_path!s}, which does not exist")

    channels_raw = raw["channels"]
    if not isinstance(channels_raw, list) or not channels_raw:
        raise LoggerConfigError(f"channels must be a non-empty list, got {channels_raw!r}")
    channels = [_parse_channel(i, entry) for i, entry in enumerate(channels_raw)]
    duplicate_names = _find_duplicates(c.name for c in channels)
    if duplicate_names:
        raise LoggerConfigError(f"channels contains duplicate name(s): {duplicate_names}")

    capture = _parse_capture(raw["capture"])
    archive = _parse_archive(raw["archive"])
    telemetry = _parse_telemetry(raw["telemetry"])
    link = _parse_link(raw["link"])
    ops = _parse_ops(raw["ops"])

    return LoggerConfig(
        schema_version=schema_version,
        dbc_path=dbc_path,
        channels=tuple(channels),
        capture=capture,
        archive=archive,
        telemetry=telemetry,
        link=link,
        ops=ops,
        raw=raw,
    )


def resolve_allowlist(config: LoggerConfig, db) -> FrozenSet[Tuple[int, bool]]:
    """Resolve `config.telemetry.allowlist`'s message names against a loaded
    `cantools` database, returning a frozenset of `(frame_id, is_extended)`
    keys -- the same key shape `telemetry.wire.dictionary.IdKey` uses.

    Kept out of `load_logger_config` deliberately: this module must stay
    importable without `cantools`, so config parsing is fast and
    independently testable without hardware or the DBC. Every unresolvable
    name is collected and named in one error, not just the first, so a typo
    cannot silently narrow what the pit sees (T-01-02)."""
    name_to_key: Dict[str, Tuple[int, bool]] = {
        message.name: (message.frame_id, message.is_extended_frame) for message in db.messages
    }

    resolved = set()
    unresolvable = []
    for name in config.telemetry.allowlist:
        key = name_to_key.get(name)
        if key is None:
            unresolvable.append(name)
        else:
            resolved.add(key)

    if unresolvable:
        raise LoggerConfigError(
            f"telemetry.allowlist names message(s) not present in the DBC: "
            f"{sorted(unresolvable)}"
        )

    return frozenset(resolved)
