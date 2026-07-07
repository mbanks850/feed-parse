"""A small big endian / little endian cursor over a bytes buffer.

Used by :mod:`feed_parse.sng` to walk the decrypted SNG body. Kept here so the
SNG parser reads like the binary format reference instead of mixing raw
``struct.unpack_from`` calls with manual offset bookkeeping.
"""

import struct
from typing import Any


class Bin:
    """Little endian byte cursor with positional read helpers.

    Each method advances ``pos`` by the size of the value read. Use
    :meth:`take` for fixed length byte slices and :meth:`skip` to advance
    without reading. The cursor does no bounds checking beyond what
    ``struct.unpack_from`` provides; the SNG body is assumed well formed.
    """

    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes, pos: int = 0) -> None:
        self.buf = buf
        self.pos = pos

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.buf, self.pos)[0]
        self.pos += 2
        return v

    def i16(self) -> int:
        v = struct.unpack_from("<h", self.buf, self.pos)[0]
        self.pos += 2
        return v

    def u8(self) -> int:
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def i8(self) -> int:
        v = struct.unpack_from("<b", self.buf, self.pos)[0]
        self.pos += 1
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def f64(self) -> float:
        v = struct.unpack_from("<d", self.buf, self.pos)[0]
        self.pos += 8
        return v

    def take(self, n: int) -> bytes:
        v = self.buf[self.pos : self.pos + n]
        self.pos += n
        return v

    def skip(self, n: int) -> None:
        self.pos += n

    def at_end(self) -> bool:
        return self.pos >= len(self.buf)


def utf8_z(blob: bytes) -> str:
    """Decode a NUL terminated UTF-8 field (the RS2014 string convention)."""
    return blob.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def round6(v: Any) -> float:
    """Round timestamps to 6 decimal places. Stable across JSON rewrites."""
    return round(float(v), 6)
