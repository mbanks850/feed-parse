"""Convert RS2014 vocal entries to feedpak lyric syllables.

The feedpak v1 lyric schema (spec section 7.1) is a flat array of
``{"t": <seconds>, "d": <duration seconds>, "w": <syllable text>}``.

* A trailing ``-`` on ``w`` joins syllables into one word (no space).
* A trailing ``+`` on ``w`` marks the end of a line.

RS2014 uses ``+`` as a line break marker, either standalone (no audible
syllable) or as a prefix on a word that starts a new line. This module
translates both conventions to feedpak's trailing ``+`` form.
"""

from typing import Any

from .binary import round6

__all__ = ["vocals_to_lyrics"]


def _close_line(out: list[dict[str, Any]]) -> None:
    """Append ``+`` to the last emitted word to close the current line."""
    if out and not out[-1]["w"].endswith("+"):
        out[-1]["w"] = out[-1]["w"] + "+"


def vocals_to_lyrics(rs_vocals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate RS2014 ``vocals`` entries to feedpak ``{t, d, w}`` syllables."""
    out: list[dict[str, Any]] = []

    for v in rs_vocals:
        text = (v.get("lyrics") or "").strip()
        if text == "" or text == "+":
            _close_line(out)
            continue
        if text.startswith("+"):
            _close_line(out)
            text = text[1:].lstrip()
            if not text:
                continue
        out.append({
            "t": round6(v["time"]),
            "d": round6(v["length"]),
            "w": text,
        })
    _close_line(out)
    return out
