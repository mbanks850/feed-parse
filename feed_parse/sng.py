"""Decrypt and parse a Rocksmith 2014 SNG arrangement file.

A packed SNG is::

    magic(4) = 0x4A         # uint32 LE
    platformHeader(4)
    iv(16)
    encrypted_payload(...)   # AES CTR encrypted
    signature(56)            # RSA signature, ignored by this tool

AES CTR is keyed with :data:`feed_parse.constants.MAC_KEY` for macOS archives
and :data:`feed_parse.constants.WIN_KEY` for Windows archives. The initial
counter value is the first 4 bytes of the IV read big endian. The decrypted
payload begins with a uint32 LE *uncompressed length* followed by a zlib
compressed SNG body.

The body itself is a sequence of length prefixed little endian arrays
(beats, phrases, chord templates, etc.). :func:`parse_sng` walks it once and
returns a dict of plain lists ready for the chart / lyrics translators.
"""

import struct
import zlib
from typing import Any, Callable

from Crypto.Cipher import AES

from .binary import Bin, round6, utf8_z
from .constants import MAC_KEY, SNG_MAGIC, WIN_KEY

__all__ = ["decrypt_sng", "parse_sng"]


def _pad16(data: bytes) -> bytes:
    n = (16 - len(data)) % 16
    return data + bytes(n)


def _try_decrypt_inflate(data: bytes, key: bytes) -> bytes:
    """Decrypt with ``key`` and inflate. Raises on failure."""
    iv = data[8:24]
    ctr_init = int.from_bytes(iv, "big")
    payload = data[24 : len(data) - 56]
    cipher = AES.new(key, AES.MODE_CTR, initial_value=ctr_init, nonce=b"")
    decrypted = cipher.decrypt(_pad16(payload))
    (uncompressed_len,) = struct.unpack("<I", decrypted[:4])
    body = decrypted[4:]
    try:
        out = zlib.decompress(body)
    except zlib.error:
        out = zlib.decompressobj().decompress(body)
    return out[:uncompressed_len] if uncompressed_len else out


def decrypt_sng(data: bytes, platform: str = "mac") -> bytes:
    """AES CTR decrypt an SNG payload and inflate the zlib body.

    If ``data`` does not begin with the SNG magic it is returned unchanged;
    this makes the function safe to call on already decrypted SNG bodies.

    When the preferred key (based on *platform*) fails decompression the
    other key is attempted automatically. This handles ``generic`` paths
    that can be encrypted with either key.
    """
    magic = struct.unpack("<I", data[:4])[0]
    if magic != SNG_MAGIC:
        return data
    primary = MAC_KEY if platform == "mac" else WIN_KEY
    fallback = WIN_KEY if platform == "mac" else MAC_KEY
    try:
        return _try_decrypt_inflate(data, primary)
    except (zlib.error, struct.error):
        return _try_decrypt_inflate(data, fallback)


def _read_bend(b: Bin) -> dict[str, Any]:
    """BENDDATA: f32 time, f32 step, skip 3, i8 unused."""
    t = b.f32()
    step = b.f32()
    b.skip(3)
    b.i8()
    return {"t": round6(t), "v": round6(step)}


def parse_sng(buf: bytes) -> dict[str, Any]:
    """Parse a decrypted SNG body into a dict of plain Python lists."""
    b = Bin(buf)

    def array(read_item: Callable[[], Any]) -> list[Any]:
        n = b.u32()
        return [read_item() for _ in range(n)]

    beats = array(lambda: {
        "time": round6(b.f32()),
        "measure": b.u16(),
        "beat": b.u16(),
        "phraseIteration": b.u32(),
        "mask": b.u32(),
    })

    phrases = array(lambda: {
        "solo": b.i8(),
        "disparity": b.i8(),
        "ignore": b.i8(),
        "_pad": b.i8(),
        "maxDifficulty": b.u32(),
        "phraseIterationLinks": b.u32(),
        "name": utf8_z(b.take(32)),
    })

    def chord_template() -> dict[str, Any]:
        mask = b.u32()
        frets = [b.i8() for _ in range(6)]
        fingers = [b.i8() for _ in range(6)]
        notes = [b.i32() for _ in range(6)]
        return {
            "mask": mask,
            "frets": frets,
            "fingers": fingers,
            "notes": notes,
            "name": utf8_z(b.take(32)),
        }

    chord_templates = array(chord_template)

    def chord_note() -> dict[str, Any]:
        mask = [b.i32() for _ in range(6)]
        bends: list[dict[str, Any]] = []
        for _ in range(6):
            for _ in range(32):
                bends.append(_read_bend(b))
            b.u32()  # bend count
        slide_to = [b.i8() for _ in range(6)]
        slide_unpitch = [b.i8() for _ in range(6)]
        vibrato = [b.i16() for _ in range(6)]
        return {
            "mask": mask,
            "bends": bends,
            "slideTo": slide_to,
            "slideUnpitchTo": slide_unpitch,
            "vibrato": vibrato,
        }

    chord_notes = array(chord_note)

    vocals = array(lambda: {
        "time": round6(b.f32()),
        "note": b.i32(),
        "length": round6(b.f32()),
        "lyrics": utf8_z(b.take(48)),
    })

    # Symbols block: only present when the vocals array was non empty.
    # We skip the contents; they're glyph atlases for in game rendering.
    if len(vocals) != 0:
        ha_length = b.u32()
        for _ in range(ha_length):
            for _ in range(8):
                b.i32()
        texture_length = b.u32()
        for _ in range(texture_length):
            b.take(128)
            b.i32()
            b.skip(4)
            b.i32()
            b.i32()
        def_length = b.u32()
        for _ in range(def_length):
            b.take(12)
            for _ in range(2):
                b.f32(); b.f32(); b.f32(); b.f32()

    phrase_iterations = array(lambda: {
        "phraseId": b.u32(),
        "startTime": round6(b.f32()),
        "nextPhraseTime": round6(b.f32()),
        "difficulty": [b.u32() for _ in range(3)],
    })

    def phrase_extra_item() -> dict[str, Any]:
        return {
            "phraseId": b.u32(),
            "difficulty": b.u32(),
            "empty": b.u32(),
            "levelJump": b.i8(),
            "redundant": b.i16(),
        }

    n = b.u32()
    phrase_extra = [phrase_extra_item() for _ in range(n)]
    for _ in phrase_extra:
        b.skip(1)  # trailing pad byte per item

    nld_len = b.u32()
    new_linked_diffs: list[dict[str, Any]] = []
    for _ in range(nld_len):
        level_break = b.i32()
        m = b.u32()
        phrase = [b.i32() for _ in range(m)]
        new_linked_diffs.append({"levelBreak": level_break, "phrase": phrase})

    def action() -> dict[str, Any]:
        t = b.f32()
        return {"time": round6(t), "name": utf8_z(b.take(256))}

    actions_len = b.u32()
    actions = [action() for _ in range(actions_len)]

    events_len = b.u32()
    events = [action() for _ in range(events_len)]

    def tone() -> dict[str, Any]:
        t = b.f32()
        i = b.u32()
        return {"time": round6(t), "id": i}

    tone_len = b.u32()
    tone = [tone() for _ in range(tone_len)]

    dna_len = b.u32()
    dna = [tone() for _ in range(dna_len)]

    sections = array(lambda: {
        "name": utf8_z(b.take(32)),
        "number": b.u32(),
        "startTime": round6(b.f32()),
        "endTime": round6(b.f32()),
        "startPhraseIterationId": b.u32(),
        "endPhraseIterationId": b.u32(),
        "stringMask": [b.i8() for _ in range(36)],
    })

    def read_anchor() -> dict[str, Any]:
        return {
            "time": round6(b.f32()),
            "endTime": round6(b.f32()),
            "unkTime": round6(b.f32()),
            "unkTime2": round6(b.f32()),
            "fret": b.i32(),
            "width": b.i32(),
            "phraseIterationId": b.i32(),
        }

    def read_anchor_ext() -> dict[str, Any]:
        t = b.f32()
        f = b.i8()
        b.skip(7)
        return {"time": round6(t), "fret": f}

    def read_fingerprint() -> dict[str, Any]:
        return {
            "chordId": b.u32(),
            "startTime": round6(b.f32()),
            "endTime": round6(b.f32()),
            "unkStartTime": round6(b.f32()),
            "unkEndTime": round6(b.f32()),
        }

    def read_note() -> dict[str, Any]:
        mask = b.u32()
        flags = b.u32()
        b.u32()  # hash
        time = b.f32()
        string = b.i8()
        fret = b.i8()
        anchor_fret = b.i8()
        anchor_width = b.i8()
        chord_id = b.u32()
        chord_note_id = b.u32()
        phrase_id = b.u32()
        phrase_iter_id = b.u32()
        fp1 = b.u16(); fp2 = b.u16()
        next_iter = b.u16()
        prev_iter = b.u16()
        parent_prev = b.u16()
        slide_to = b.i8()
        slide_unpitch = b.i8()
        left_hand = b.i8()
        tap = b.i8()
        pick_dir = b.i8()
        slap = b.i8()
        pluck = b.i8()
        vibrato = b.i16()
        sustain = b.f32()
        max_bend = b.f32()
        n_bends = b.u32()
        bends = [_read_bend(b) for _ in range(n_bends)]
        return {
            "mask": mask,
            "flags": flags,
            "time": round6(time),
            "string": string,
            "fret": fret,
            "anchorFret": anchor_fret,
            "anchorWidth": anchor_width,
            "chordId": chord_id,
            "chordNoteId": chord_note_id,
            "phraseId": phrase_id,
            "phraseIterationId": phrase_iter_id,
            "fingerPrintId": [fp1, fp2],
            "nextIterNote": next_iter,
            "prevIterNote": prev_iter,
            "parentPrevNote": parent_prev,
            "slideTo": slide_to,
            "slideUnpitchTo": slide_unpitch,
            "leftHand": left_hand,
            "tap": tap,
            "pickDirection": pick_dir,
            "slap": slap,
            "pluck": pluck,
            "vibrato": vibrato,
            "sustain": round6(sustain),
            "maxBend": round6(max_bend),
            "bends": bends,
        }

    def level() -> dict[str, Any]:
        difficulty = b.u32()
        n_anchors = b.u32()
        anchors = [read_anchor() for _ in range(n_anchors)]
        n_anchor_ext = b.u32()
        anchor_ext = [read_anchor_ext() for _ in range(n_anchor_ext)]
        fingerprints: list[list[dict[str, Any]]] = []
        for _ in range(2):
            m = b.u32()
            fingerprints.append([read_fingerprint() for _ in range(m)])
        n_notes = b.u32()
        notes = [read_note() for _ in range(n_notes)]
        anpi_len = b.u32()
        anpi = [b.f32() for _ in range(anpi_len)]
        niicni_len = b.u32()
        niicni = [b.i32() for _ in range(niicni_len)]
        niic_len = b.u32()
        niic = [b.i32() for _ in range(niic_len)]
        return {
            "difficulty": difficulty,
            "anchors": anchors,
            "anchorExtensions": anchor_ext,
            "fingerprints": fingerprints,
            "notes": notes,
            "averageNotesPerIter": anpi,
            "notesInIterCountNoIgnored": niicni,
            "notesInIterCount": niic,
        }

    levels_len = b.u32()
    levels = [level() for _ in range(levels_len)]

    metadata = {
        "maxScores": b.f64(),
        "maxNotesAndChords": b.f64(),
        "maxNotesAndChordsReal": b.f64(),
        "pointsPerNote": b.f64(),
        "firstBeatLength": round6(b.f32()),
        "startTime": round6(b.f32()),
        "capo": b.i8(),
        "lastConversionDateTime": utf8_z(b.take(32)).encode("ascii", "replace").decode("ascii"),
        "part": b.i16(),
        "songLength": round6(b.f32()),
        "tuning": [b.i16() for _ in range(b.u32())],
        "firstNoteTime": round6(b.f32()),
        "firstNoteTime2": round6(b.f32()),
        "maxDifficulty": b.i32(),
    }

    return {
        "beats": beats,
        "phrases": phrases,
        "chordTemplates": chord_templates,
        "chordNotes": chord_notes,
        "vocals": vocals,
        "phraseIterations": phrase_iterations,
        "phraseExtraInfos": phrase_extra,
        "newLinkedDiffs": new_linked_diffs,
        "actions": actions,
        "events": events,
        "tone": tone,
        "dna": dna,
        "sections": sections,
        "levels": levels,
        "metadata": metadata,
    }
