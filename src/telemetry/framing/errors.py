"""
telemetry.framing.errors — the exception family every framing/batching
failure raises, mirroring `telemetry.wire.encoder`'s `CfrError` /
`BatchWindowExceeded` / `PayloadTooLong` shape (01-PATTERNS.md's
"Exception-family shape" pattern): one base exception per subsystem, a
specific subclass per distinct failure mode, each with a one-line docstring
saying exactly when it is raised.

`telemetry.ground.deframe.Deframer` catches the base `FramingError` to
count-and-continue per corrupted segment (LINK-02); tests catch the specific
subclass to discriminate which failure mode fired.
"""


class FramingError(Exception):
    """Base exception for every framing/batching failure in this package."""


class CobsDecodeFailed(FramingError):
    """Raised when `cobs.cobs.DecodeError` is caught while unframing a
    segment — the COBS-encoded bytes are malformed and cannot be decoded
    back into a payload+CRC trailer."""


class CrcMismatch(FramingError):
    """Raised when a frame's computed CRC-16 does not match its trailer —
    the bytes decoded cleanly through COBS but were corrupted in transit
    (or the trailer itself was corrupted)."""


class BatchFormatError(FramingError):
    """Raised when a batch payload is truncated, overruns its own declared
    record length, disagrees between its declared `frame_count` and the
    number of records actually recovered, or a record fed to `pack_batch`
    exceeds the one-byte length-prefix's 255-byte limit."""
