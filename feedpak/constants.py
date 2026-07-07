"""Crypto keys, magic numbers, and bit masks used across the package.

The AES keys and PSARC container constants come from the public RS2014 CDLC
tooling references (sandiz/psarcjs, 0x0L/rs-utils). The note technique masks
come from rs toolkit's SNG documentation. Centralising them here keeps the
binary parsers free of magic numbers.
"""

import codecs

# AES keys for the PSARC table of contents (ARC_*) and the per arrangement
# SNG payloads (MAC_/WIN_). macOS SNGs use MAC_KEY, Windows uses WIN_KEY.
ARC_KEY: bytes = codecs.decode(
    "C53DB23870A1A2F71CAE64061FDD0E1157309DC85204D4C5BFDF25090DF2572C", "hex"
)
ARC_IV: bytes = codecs.decode("E915AA018FEF71FC508132E4BB4CEB42", "hex")
MAC_KEY: bytes = codecs.decode(
    "9821330E34B91F70D0A48CBD625993126970CEA09192C0E6CDA676CC9838289D", "hex"
)
WIN_KEY: bytes = codecs.decode(
    "CB648DF3D12A16BF71701414E69619EC171CCA5D2A142E3E59DE7ADDA18A3A30", "hex"
)

# PSARC container layout. Header is 32 bytes; each TOC entry is 30 bytes.
PSARC_HEADER_FMT: str = ">4sI4sIIIII"
PSARC_HEADER_SIZE: int = 32
PSARC_ENTRY_SIZE: int = 30
PSARC_BLOCK_SIZE: int = 65536

# Packed SNG files start with this magic (uint32 little endian).
SNG_MAGIC: int = 0x4A

# feedpak spec version emitted by this tool.
FEEDPAK_VERSION: str = "1.14.0"

# Note technique bit masks (RS2014 SNG note mask field).
M_SUSTAIN: int = 1 << 3
M_BEND: int = 1 << 4
M_ACCENT: int = 1 << 7
M_HAMMER: int = 1 << 9
M_PULL: int = 1 << 10
M_HOPO: int = 1 << 11
M_HARMONIC: int = 1 << 12
M_PINCH_HARMONIC: int = 1 << 13
M_PALM_MUTE: int = 1 << 14
M_MUTED: int = 1 << 15
M_VIBRATO: int = 1 << 17
M_FRET_HAND_MUTE: int = 1 << 19
M_TREMOLO: int = 1 << 20
M_HIGH_DENSITY: int = 1 << 22
M_IGNORE: int = 1 << 23
M_TAP: int = 1 << 24
M_SLIDE: int = 1 << 25
M_SLIDE_UNPITCHED: int = 1 << 26
M_SLAP: int = 1 << 27
M_PLUCK: int = 1 << 28
M_CHORD: int = 1 << 1
