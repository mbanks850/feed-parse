"""Top level orchestration: PSARC archive to feedpak v1 package.

The :func:`convert` function is the only public surface in this module.
Callers (the CLI, batch scripts, library users) pass a source PSARC path
and an output path; everything else is internal.

The work splits into five stages, each delegated to a focused module:

1. **PSARC container** (:mod:`feed_parse.psarc`): decrypt the TOC, reassemble
   every internal file into an in memory ``{path: bytes}`` map.
2. **Metadata** (:mod:`feed_parse.metadata`): pull song level fields out of
   the RS2014 manifest JSON.
3. **Arrangements** (:mod:`feed_parse.sng` + :mod:`feed_parse.chart`): decrypt
   and parse each ``.sng`` file, then project to a feedpak arrangement
   dict. Vocal arrangements are diverted into lyric sources.
4. **Lyrics** (:mod:`feed_parse.lyrics`): emit top level ``lyrics.json``
   (and ``lyrics_romaji.json`` when both Japanese and romanized tracks
   exist).
5. **Media** (:mod:`feed_parse.media`): transcode the WEM stem to OGG and
   convert the DDS album art to PNG.

Finally the manifest is composed and either written to a directory or
packed into a zip.
"""

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import yaml

from . import chart, lyrics, media, metadata, psarc, sng
from .constants import FEEDPAK_VERSION

__all__ = ["convert"]


def _dedupe(arrangements: list[tuple[str, str, dict[str, Any]]]) -> list[tuple[str, str, dict[str, Any]]]:
    """Append an index suffix to arrangement ids that collide."""
    seen: dict[str, int] = {}
    finalized: list[tuple[str, str, dict[str, Any]]] = []
    for arr_id, name, data in arrangements:
        if arr_id in seen:
            seen[arr_id] += 1
            arr_id = f"{arr_id}_{seen[arr_id]}"
        else:
            seen[arr_id] = 0
        finalized.append((arr_id, name, data))
    return finalized


def _write_arrangements(
    build_dir: Path, finalized: list[tuple[str, str, dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Write each arrangement to JSON and return the manifest entries.

    Beats and sections are stripped from all but the first arrangement to
    avoid duplicating song level data across files; the spec allows any
    arrangement to carry them, so consumers reading a single file still
    work as long as they pick the first.
    """
    out: list[dict[str, Any]] = []
    first = True
    for arr_id, name, data in finalized:
        if not first:
            data.pop("beats", None)
            data.pop("sections", None)
        first = False
        (build_dir / "arrangements" / f"{arr_id}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        out.append({
            "id": arr_id,
            "name": name,
            "file": f"arrangements/{arr_id}.json",
            "tuning": data.get("tuning", [0] * 6),
            "capo": data.get("capo", 0),
            "centOffset": data.get("centOffset", 0.0),
        })
    return out


def _probe_duration(full_ogg: Path) -> float:
    """Use ffprobe to read the OGG duration in seconds. Returns 0.0 on failure."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(full_ogg)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    if proc.returncode != 0:
        return 0.0
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _convert_cover(
    files: dict[str, bytes], build_dir: Path, art_urn: str
) -> str | None:
    """Find the 256/128/64 DDS variant for the album art URN and convert it."""
    art_basename = art_urn.split(":")[-1] if art_urn else ""
    if not art_basename:
        return None
    for size in (256, 128, 64):
        cand = f"gfxassets/album_art/{art_basename}_{size}.dds"
        if cand not in files:
            continue
        (build_dir / "gfx").mkdir(exist_ok=True)
        png = build_dir / "gfx" / "cover.png"
        if media.convert_dds(files[cand], png):
            return "gfx/cover.png"
        # Fall back to DDS passthrough if conversion failed (non portable).
        dds = build_dir / "gfx" / "cover.dds"
        dds.write_bytes(files[cand])
        return "gfx/cover.dds"
    return None


def _write_lyrics(
    build_dir: Path, lyric_sources: dict[str, dict[str, Any]]
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Emit ``lyrics.json`` (and optional romaji) for the found vocal tracks.

    Returns ``(primary_lyrics_path, primary_language, lyric_tracks)``. The
    orchestrator only adds ``lyric_tracks`` to the manifest when more than
    one track exists; the primary path/language are always set when any
    lyrics were emitted.
    """
    tracks: list[dict[str, Any]] = []
    primary: str | None = None
    language: str | None = None

    jv = lyric_sources.get("vocals_jv", {}).get("vocals")
    rom = lyric_sources.get("vocals", {}).get("vocals")

    if jv:
        data = lyrics.vocals_to_lyrics(jv)
        (build_dir / "lyrics.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        primary = "lyrics.json"
        language = "ja"
        tracks.append({
            "id": "ja", "file": "lyrics.json",
            "language": "ja", "kind": "original", "name": "日本語",
        })
        if rom:
            data = lyrics.vocals_to_lyrics(rom)
            (build_dir / "lyrics_romaji.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            tracks.append({
                "id": "romaji", "file": "lyrics_romaji.json",
                "language": "ja-Latn", "kind": "transliteration", "name": "Romaji",
            })
    elif rom:
        data = lyrics.vocals_to_lyrics(rom)
        (build_dir / "lyrics.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        primary = "lyrics.json"
        language = "en"
        tracks.append({
            "id": "default", "file": "lyrics.json",
            "language": "en", "kind": "original",
        })

    return primary, language, tracks


def _parse_arrangements(
    files: dict[str, bytes],
) -> tuple[list[tuple[str, str, dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Decrypt and parse every SNG file.

    Returns ``(arrangements, lyric_sources)``. ``arrangements`` is the
    list of feedpak arrangement tuples for guitar/bass charts. ``lyric_sources``
    maps ``vocals``/``vocals_jv`` to the parsed SNG dict for the lyrics
    translator to consume.
    """
    arrangements: list[tuple[str, str, dict[str, Any]]] = []
    lyric_sources: dict[str, dict[str, Any]] = {}

    sng_paths = [p for p in files if p.startswith("songs/bin/") and p.endswith(".sng")]
    for sp in sorted(sng_paths):
        platform = "mac" if "/macos/" in sp else "win"
        try:
            decrypted = sng.decrypt_sng(files[sp], platform)
            parsed = sng.parse_sng(decrypted)
        except Exception as exc:
            sys.stderr.write(f"warning: failed to parse {sp}: {exc}\n")
            continue
        stem = Path(sp).stem
        result = chart.sng_to_arrangement(parsed, stem)
        if result["id"] in chart.VOCALS_IDS:
            lyric_sources[result["id"]] = parsed
            continue
        arrangements.append((result["id"], result["name"], result["data"]))

    if not arrangements and not lyric_sources:
        raise SystemExit("no arrangements found inside the PSARC")
    return arrangements, lyric_sources


def convert(
    src: Path,
    out: Path,
    audio_arg: Path | None = None,
    zip_output: bool = False,
) -> Path:
    """Convert ``src`` (a ``.psarc``) into a feedpak package at ``out``.

    Parameters
    ----------
    src
        Path to the source PSARC archive.
    out
        Output directory (default) or ``.feedpak`` zip path (when
        ``zip_output`` is True).
    audio_arg
        Optional pre decoded OGG/WAV to use as the full stem. Overrides
        any audio embedded in the PSARC.
    zip_output
        When True, build a staging directory, write the package there,
        then zip it into ``out`` and remove the staging directory.

    Returns
    -------
    Path
        The path that was written (``out`` for zip mode, the build
        directory otherwise).
    """
    if not src.exists():
        raise SystemExit(f"source not found: {src}")

    files = psarc.extract_psarc(src)
    if not files:
        raise SystemExit("PSARC contains no files")

    attrs = metadata.read_manifest_attrs(files)
    meta = metadata.extract_metadata(attrs, src.stem)

    arrangements, lyric_sources = _parse_arrangements(files)
    finalized = _dedupe(arrangements)

    if zip_output:
        build_dir = out.parent / f".{out.stem}.build"
    else:
        build_dir = out
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    (build_dir / "arrangements").mkdir()

    arrangements_manifest = _write_arrangements(build_dir, finalized)

    stems_dir = build_dir / "stems"
    stem_entries, full_ogg = media.handle_audio(files, stems_dir)
    if audio_arg and audio_arg.exists():
        target = stems_dir / "full.ogg"
        shutil.copy(audio_arg, target)
        stem_entries = [{"id": "full", "file": "stems/full.ogg", "default": True}]
    if not stem_entries:
        raise SystemExit("no audio stem located in PSARC and no --audio supplied")

    duration = meta.get("duration") or 0.0
    if duration == 0.0 and full_ogg and full_ogg.suffix == ".ogg":
        duration = _probe_duration(full_ogg)

    cover_rel = _convert_cover(files, build_dir, meta.get("album_art_urn", ""))
    primary_lyrics, primary_language, lyric_tracks = _write_lyrics(build_dir, lyric_sources)

    manifest: dict[str, Any] = {
        "feedpak_version": FEEDPAK_VERSION,
        "title": meta["title"],
        "artist": meta["artist"],
        "duration": round(duration, 3),
        "arrangements": arrangements_manifest,
        "stems": stem_entries,
        "authors": [
            {"name": "feed_parse psarc converter", "role": "transcriber"}
        ],
    }
    if primary_lyrics:
        manifest["lyrics"] = primary_lyrics
    if primary_language:
        manifest["language"] = primary_language
    if len(lyric_tracks) > 1:
        manifest["lyric_tracks"] = lyric_tracks
    if meta.get("album"):
        manifest["album"] = meta["album"]
    if meta.get("year"):
        try:
            manifest["year"] = int(meta["year"])
        except (TypeError, ValueError):
            pass
    if cover_rel:
        manifest["cover"] = cover_rel

    (build_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )

    if zip_output:
        if out.exists():
            if out.is_dir():
                shutil.rmtree(out)
            else:
                out.unlink()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in build_dir.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(build_dir).as_posix())
        shutil.rmtree(build_dir)
        return out

    return build_dir
