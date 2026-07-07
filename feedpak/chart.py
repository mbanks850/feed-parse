"""Translate a parsed SNG dict into a feedpak arrangement payload.

The arrangement dict matches the feedpak v1 arrangement schema: notes,
chords, anchors, templates, plus the song level ``beats`` and ``sections``
arrays. The field names use the short form (``t``, ``s``, ``f``, ``sl`` ...)
mandated by the spec to keep arrangement JSON files small.

RS2014 packs multiple difficulty levels per arrangement. Levels ``0..N`` form
the easy to hard ramp; anything above ``N`` is sometimes an alternate path
(solo only, bonus chart). The player wants the densest single chart, so we
pick the level with the most events rather than the highest difficulty.
"""

from typing import Any

from .binary import round6
from .constants import (
    M_ACCENT,
    M_BEND,
    M_CHORD,
    M_FRET_HAND_MUTE,
    M_HAMMER,
    M_HARMONIC,
    M_HIGH_DENSITY,
    M_IGNORE,
    M_PALM_MUTE,
    M_PINCH_HARMONIC,
    M_PLUCK,
    M_PULL,
    M_SLAP,
    M_SLIDE,
    M_SLIDE_UNPITCHED,
    M_SUSTAIN,
    M_TAP,
    M_TREMOLO,
    M_VIBRATO,
    M_MUTED,
)

__all__ = ["arrangement_id", "sng_to_arrangement", "LEVEL_PICKER_NOTE"]


# Vocals arrangements aren't guitar charts; they're diverted to top level
# lyrics files by the orchestrator. This sentinel is the arrangement id
# returned for them so the orchestrator can recognise the diversion.
VOCALS_IDS: tuple[str, ...] = ("vocals", "vocals_jv")


def arrangement_id(arr_name: str, part: int) -> str:
    """Map an RS2014 arrangement name + part code to a feedpak arrangement id.

    Name patterns win over the part code: RS2014 sets ``metadata.part=1``
    for every guitar and bass arrangement, so it cannot distinguish lead
    from rhythm from bass.
    """
    n = (arr_name or "").lower()
    if "jvocal" in n:
        return "vocals_jv"
    if "vocal" in n:
        return "vocals"
    if "bass" in n:
        return "bass"
    if "rhythm" in n:
        return "rhythm"
    if "lead" in n:
        return "lead"
    if part == 1:
        return "bass"
    if part == 2:
        return "vocals"
    return "arrangement"


LEVEL_PICKER_NOTE = (
    "Pick the densest level as the canonical chart. RS2014 packs multiple "
    "levels per arrangement: 0..N is the easy to hard ramp, but extra levels "
    "above N are sometimes used for alternative paths (solo only, bonus). "
    "The full chart the player wants is the level with the most events."
)


def _event_count(lv: dict[str, Any]) -> int:
    """Count chart events in a level: individual notes plus unique chord times."""
    indiv = sum(1 for n in lv["notes"] if not (n["mask"] & M_CHORD))
    chord_ts = len({n["time"] for n in lv["notes"] if (n["mask"] & M_CHORD)})
    return indiv + chord_ts


def _choose_level(levels: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the densest level by event count (see :data:`LEVEL_PICKER_NOTE`)."""
    return max(levels, key=_event_count) if levels else None


def _note_to_dict(n: dict[str, Any]) -> dict[str, Any]:
    mask = n["mask"]
    out: dict[str, Any] = {
        "t": round6(n["time"]),
        "s": n["string"],
        "f": n["fret"],
    }
    if mask & M_SUSTAIN and n["sustain"] > 0:
        out["sus"] = round6(n["sustain"])
    if mask & M_SLIDE and n["slideTo"] >= 0:
        out["sl"] = n["slideTo"]
    if mask & M_SLIDE_UNPITCHED and n["slideUnpitchTo"] >= 0:
        out["slu"] = n["slideUnpitchTo"]
    if mask & M_BEND and n["maxBend"] > 0:
        out["bn"] = round6(n["maxBend"])
        if n["bends"]:
            out["bendPoints"] = n["bends"]
    if mask & M_HAMMER: out["ho"] = True
    if mask & M_PULL: out["po"] = True
    if mask & M_HARMONIC: out["hm"] = True
    if mask & M_PINCH_HARMONIC: out["hp"] = True
    if mask & M_PALM_MUTE: out["pm"] = True
    if mask & M_MUTED: out["mt"] = True
    if mask & M_VIBRATO: out["vb"] = True
    if mask & M_TREMOLO: out["tr"] = True
    if mask & M_ACCENT: out["ac"] = True
    if mask & M_TAP: out["tp"] = True
    if mask & M_FRET_HAND_MUTE: out["fhm"] = True
    if mask & M_HIGH_DENSITY: out["hd"] = True
    if mask & M_IGNORE: out["ig"] = True
    if mask & M_PLUCK: out["plk"] = True
    if mask & M_SLAP: out["slp"] = True
    if n["leftHand"] >= 0:
        out["lh"] = n["leftHand"]
    if n["pickDirection"] >= 0:
        out["pkd"] = n["pickDirection"]
    return out


def _arrangement_name(stem: str) -> str:
    """Map an SNG filename stem suffix to a human readable arrangement name."""
    suffix = stem.rsplit("_", 1)[-1] if "_" in stem else stem
    return {
        "jvocals": "JVocals",
        "vocals": "Vocals",
        "lead": "Lead",
        "rhythm": "Rhythm",
        "bass": "Bass",
    }.get(suffix.lower(), suffix.title())


def sng_to_arrangement(sng: dict[str, Any], stem: str) -> dict[str, Any]:
    """Build the feedpak arrangement payload for one non vocal SNG file.

    Returns ``{"id": str, "name": str, "data": dict}``. Beats and sections
    are embedded on every arrangement; the orchestrator strips them from
    all but the first to avoid duplicate storage while still letting each
    arrangement be loaded independently.
    """
    md = sng["metadata"]
    # Tuning is high string first in SNG; feedpak wants lowest string first.
    tuning = list(reversed(md["tuning"])) if md["tuning"] else [0] * 6
    capo = md["capo"] if md["capo"] >= 0 else 0

    templates = [
        {
            "name": ct["name"],
            "frets": list(reversed(ct["frets"])),
            "fingers": list(reversed(ct["fingers"])),
        }
        for ct in sng["chordTemplates"]
    ]

    chosen = _choose_level(sng["levels"])
    notes: list[dict[str, Any]] = []
    chords: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    if chosen:
        for n in chosen["notes"]:
            if n["mask"] & M_CHORD:
                chords.append({"t": round6(n["time"]), "id": n["chordId"]})
            else:
                notes.append(_note_to_dict(n))
        for a in chosen["anchors"]:
            anchors.append({
                "time": round6(a["time"]),
                "fret": a["fret"],
                "width": a["width"],
            })

    beats = [{"time": b_["time"]} for b_ in sng["beats"]]
    sections = [
        {
            "name": s_["name"].lower(),
            "number": s_["number"],
            "time": s_["startTime"],
        }
        for s_ in sng["sections"]
    ]

    name = _arrangement_name(stem)
    arr_id = arrangement_id(name, md["part"])

    data: dict[str, Any] = {
        "name": name,
        "tuning": tuning,
        "capo": capo,
        "centOffset": 0.0,
        "notes": notes,
        "chords": chords,
        "anchors": anchors,
        "handshapes": [],
        "templates": templates,
    }
    if beats:
        data["beats"] = beats
    if sections:
        data["sections"] = sections
    return {"id": arr_id, "name": name, "data": data}
