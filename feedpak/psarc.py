"""Read the PSARC container: decrypt the table of contents, then reassemble
each entry's zlib compressed blocks into the original file bytes.

RS2014 CDLC files are PSARC archives whose TOC is AES CFB encrypted with
``ARC_KEY`` / ``ARC_IV``. Each entry's payload is split into 64 KiB blocks
that are either stored verbatim (zlength entry 0) or zlib compressed (any
non zero zlength). The first entry is always the manifest, a newline
separated list of file paths that gives every other entry its name.
"""

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from Crypto.Cipher import AES

from .constants import (
    ARC_IV,
    ARC_KEY,
    PSARC_BLOCK_SIZE,
    PSARC_ENTRY_SIZE,
    PSARC_HEADER_FMT,
    PSARC_HEADER_SIZE,
)

__all__ = ["Entry", "extract_psarc"]


def _pad(data: bytes, blocksize: int = 16) -> bytes:
    """PKCS style zero pad to a multiple of ``blocksize`` (AES block size)."""
    n = (blocksize - len(data)) % blocksize
    return data + bytes(n)


def _toc_cipher() -> AES:
    return AES.new(ARC_KEY, mode=AES.MODE_CFB, iv=ARC_IV, segment_size=128)


@dataclass
class Entry:
    """One file inside the PSARC archive."""

    md5: bytes
    zindex: int
    length: int  # uncompressed size in bytes
    offset: int  # absolute byte offset within the archive
    zlength: list[int] = field(default_factory=list)
    filepath: str = ""


def _read_entry_data(f, entry: Entry) -> bytes:
    """Walk the block list for one entry and concatenate the decompressed bytes."""
    out = bytearray()
    f.seek(entry.offset)
    i = 0
    while len(out) < entry.length:
        z = entry.zlength[i]
        if z == 0:
            out += f.read(PSARC_BLOCK_SIZE)
        else:
            chunk = f.read(z)
            try:
                out += zlib.decompress(chunk)
            except zlib.error:
                out += chunk
        i += 1
    return bytes(out[: entry.length])


def read_toc(f) -> list[Entry]:
    """Decrypt the PSARC TOC and return the list of file entries.

    The first entry in the raw TOC is the manifest (a newline separated list
    of paths). This function reads it and assigns each subsequent entry its
    filepath, then returns only those file entries to the caller.
    """
    f.seek(0)
    magic, version, comp, toc_total, entry_size, nfiles, block_size, flags = (
        struct.unpack(PSARC_HEADER_FMT, f.read(PSARC_HEADER_SIZE))
    )
    if magic != b"PSAR":
        raise ValueError(f"not a PSARC file (magic={magic!r})")
    if entry_size != PSARC_ENTRY_SIZE:
        raise ValueError(f"unexpected PSARC entry size {entry_size}")

    toc_size = toc_total - PSARC_HEADER_SIZE
    toc = _toc_cipher().decrypt(_pad(f.read(toc_size)))

    entries: list[Entry] = []
    pos = 0
    for _ in range(nfiles):
        chunk = toc[pos : pos + PSARC_ENTRY_SIZE]
        entries.append(
            Entry(
                md5=chunk[:16],
                zindex=struct.unpack(">I", chunk[16:20])[0],
                length=struct.unpack(">Q", b"\x00" * 3 + chunk[20:25])[0],
                offset=struct.unpack(">Q", b"\x00" * 3 + chunk[25:30])[0],
            )
        )
        pos += PSARC_ENTRY_SIZE

    n_blocks = (toc_size - PSARC_ENTRY_SIZE * nfiles) // 2
    zlength: list[int] = []
    for _ in range(n_blocks):
        zlength.append(struct.unpack(">H", toc[pos : pos + 2])[0])
        pos += 2

    for e in entries:
        e.zlength = zlength[e.zindex :]

    # entry[0] is the manifest (newline separated file listing).
    listing = _read_entry_data(f, entries[0]).split()
    for entry, path in zip(entries[1:], listing):
        entry.filepath = path.decode("utf-8", errors="replace")
    return entries[1:]


def extract_psarc(src: Path) -> dict[str, bytes]:
    """Read every file of a PSARC archive into an in memory ``{path: bytes}`` map."""
    files: dict[str, bytes] = {}
    with src.open("rb") as f:
        entries = read_toc(f)
        for e in entries:
            files[e.filepath] = _read_entry_data(f, e)
    return files
