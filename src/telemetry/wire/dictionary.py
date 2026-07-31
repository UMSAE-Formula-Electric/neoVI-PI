"""
telemetry.wire.dictionary — the D-05/D-07 static, DBC-derived ID dictionary.

Builds a versioned `(frame_id, is_extended) -> id_index` table from
`epbr2026_DBC_v1.0.dbc`, following the same "flat dict over `db.messages`"
shape as `src/new_logger.py::build_dbc_index` (lines 135-139), extended per
`.planning/research/ARCHITECTURE.md` Pattern 3 / Anti-Pattern 3: the
dictionary is static and DBC-derived, never adaptively learned from the live
stream, and keyed on the `(frame_id, is_extended_frame)` pair rather than the
raw DBC integer — several messages in this DBC (all four IMU messages,
`INV_Diag_Buffer`) carry the extended-frame marker bit (0x80000000) in their
raw `BO_` value, which `cantools` strips into `is_extended_frame` separately.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import cantools

MAX_DICTIONARY_ENTRIES = 256  # id_index is one byte (CFR byte 1)

IdKey = Tuple[int, bool]  # (frame_id, is_extended)


class DbcLoadError(Exception):
    """Raised when `epbr2026_DBC_v1.0.dbc` (or any DBC passed to `load_dbc`)
    cannot be loaded. Names the resolved path — this tool's whole input is the
    DBC, so a degraded "decoding disabled" fallback (as in
    `src/new_logger.py::main`) would be meaningless here."""


class UnknownFrameId(Exception):
    """Raised when a `(frame_id, is_extended)` pair is not present in the
    dictionary this instance was built from."""


def load_dbc(path):
    """Load a DBC file with `cantools`, raising `DbcLoadError` naming the
    resolved path on failure rather than cantools' own exception type."""
    resolved = Path(path).resolve()
    try:
        return cantools.database.load_file(str(path))
    except Exception as exc:
        raise DbcLoadError(
            f"Could not load DBC at resolved path {resolved!s}: {exc}"
        ) from exc


@dataclass(frozen=True)
class IdDictionary:
    """Static, versioned `(frame_id, is_extended) -> id_index` table.

    `index` and `reverse` are inverses of each other. `dict_version` is a
    single byte — the first byte of a SHA-256 hash over the sorted key list —
    used purely as a version-mismatch detector (RESEARCH.md Security Domain
    V6: this is NOT a cryptographic integrity guarantee and must never be
    documented as one). `dbc_path` records which DBC this dictionary was
    built from, for report provenance.
    """

    index: Dict[IdKey, int]
    reverse: Dict[int, IdKey]
    dict_version: int
    dbc_path: Path

    def index_of(self, frame_id: int, is_extended: bool) -> int:
        key = (frame_id, is_extended)
        try:
            return self.index[key]
        except KeyError:
            raise UnknownFrameId(
                f"frame_id=0x{frame_id:X} is_extended={is_extended} "
                f"is not present in this dictionary (built from {self.dbc_path!s})"
            ) from None

    def key_of(self, id_index: int) -> IdKey:
        try:
            return self.reverse[id_index]
        except KeyError:
            raise UnknownFrameId(
                f"id_index={id_index} is not present in this dictionary "
                f"(built from {self.dbc_path!s})"
            ) from None


def build_id_dictionary(db, dbc_path=None) -> IdDictionary:
    """Build a versioned `IdDictionary` from a loaded cantools database.

    Entries are built from `message.frame_id` + `message.is_extended_frame`
    as a pair — never from the raw DBC integer, which carries the
    0x80000000 extended-frame marker bit for several messages in this DBC
    (RESEARCH.md Anti-Patterns; ARCHITECTURE.md Anti-Pattern 3).
    """
    entries = sorted({(m.frame_id, m.is_extended_frame) for m in db.messages})

    if len(entries) > MAX_DICTIONARY_ENTRIES:
        raise ValueError(
            f"DBC has {len(entries)} unique (frame_id, is_extended) entries, "
            f"but id_index is one byte and can only address "
            f"{MAX_DICTIONARY_ENTRIES}"
        )

    index = {key: i for i, key in enumerate(entries)}
    reverse = {i: key for key, i in index.items()}
    dict_version = hashlib.sha256(repr(entries).encode()).digest()[0]

    return IdDictionary(
        index=index,
        reverse=reverse,
        dict_version=dict_version,
        dbc_path=Path(dbc_path) if dbc_path is not None else None,
    )
