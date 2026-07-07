"""Read song level metadata out of the RS2014 manifest JSON inside the PSARC.

Each CDLC ships a ``manifests/songs_dlc_*.json`` file (not the ``.hsan``
aggregate) whose ``Entries`` map contains the per arrangement attributes.
Any single arrangement's attributes block carries the song level fields we
need (title, artist, album, duration, album art URN).
"""

import json
from typing import Any

__all__ = ["read_manifest_attrs", "extract_metadata"]


def read_manifest_attrs(files: dict[str, bytes]) -> dict[str, Any]:
    """Return the first valid ``Attributes`` block found in the manifests."""
    for path, blob in files.items():
        if not path.startswith("manifests/songs_dlc_") or not path.endswith(".json"):
            continue
        if path.endswith(".hsan"):
            continue
        try:
            doc = json.loads(blob)
        except json.JSONDecodeError:
            continue
        entries = list(doc.get("Entries", {}).values())
        if not entries:
            continue
        attrs = entries[0].get("Attributes", {})
        if "SongName" in attrs or "ArtistName" in attrs:
            return attrs
    return {}


def extract_metadata(attrs: dict[str, Any], src_stem: str) -> dict[str, Any]:
    """Project the RS2014 attributes block into the fields the converter needs."""
    return {
        "title": attrs.get("SongName") or src_stem.replace("_", " "),
        "artist": attrs.get("ArtistName") or "Unknown Artist",
        "album": attrs.get("AlbumName", "") or "",
        "year": attrs.get("SongYear"),
        "duration": float(attrs.get("SongLength", 0.0)),
        "album_art_urn": attrs.get("AlbumArt", ""),
    }
