"""Side channel media: WEM audio transcoding and DDS album art conversion.

Both helpers return success booleans so callers can fall back gracefully
(passthrough WEM bytes, or skip the cover) instead of crashing the whole
conversion when an optional binary is missing.
"""

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

__all__ = ["handle_audio", "convert_dds"]


def _decode_wem_to_ogg(wem_bytes: bytes, target: Path) -> bool:
    """Decode a WEM (Wwise Vorbis) blob to Ogg Vorbis.

    ffmpeg cannot decode WEM directly, so we go WEM to WAV with
    ``vgmstream-cli`` and then WAV to OGG with either ``oggenc`` (preferred)
    or ffmpeg's native vorbis encoder.
    """
    vgmstream = shutil.which("vgmstream-cli") or shutil.which("vgmstream")
    if not vgmstream:
        sys.stderr.write(
            "warning: vgmstream-cli not found. Install with `brew install vgmstream` "
            "to enable WEM decoding.\n"
        )
        return False
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        wem = tmpdir / "in.wem"
        wav = tmpdir / "out.wav"
        wem.write_bytes(wem_bytes)
        r = subprocess.run(
            [vgmstream, "-o", str(wav), str(wem)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if r.returncode != 0 or not wav.exists():
            sys.stderr.write(
                "warning: vgmstream failed to decode WEM:\n"
                + r.stderr.decode("utf-8", errors="replace")[:500] + "\n"
            )
            return False
        oggenc = shutil.which("oggenc")
        if oggenc:
            r = subprocess.run(
                [oggenc, "-q", "5", "-o", str(target), str(wav)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        else:
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(wav), "-vn",
                 "-c:a", "vorbis", "-strict", "-2", "-b:a", "192k",
                 "-f", "ogg", str(target)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        return r.returncode == 0 and target.exists() and target.stat().st_size > 0


def handle_audio(
    files: dict[str, bytes], stems_dir: Path
) -> tuple[list[dict[str, Any]], Path | None]:
    """Place the song's main audio file into ``stems/`` as OGG when possible.

    Returns ``(stem_entries, full_path)``. ``full_path`` is None when no
    OGG was produced (e.g. WEM passthrough), which signals the orchestrator
    to skip OGG based duration probing.
    """
    stems_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        p for p in files
        if p.startswith("audio/") and p.endswith((".wem", ".ogg", ".wav"))
    ]
    if not candidates:
        return [], None
    # The biggest audio file is the full mix; smaller ones are stems.
    candidates.sort(key=lambda p: len(files[p]), reverse=True)
    main_path = candidates[0]
    main_bytes = files[main_path]
    ext = Path(main_path).suffix.lower()

    if ext == ".ogg":
        target = stems_dir / "full.ogg"
        target.write_bytes(main_bytes)
        return [{"id": "full", "file": "stems/full.ogg", "default": True}], target
    if ext == ".wav":
        target = stems_dir / "full.wav"
        target.write_bytes(main_bytes)
        return [{"id": "full", "file": "stems/full.wav", "default": True}], target

    target = stems_dir / "full.ogg"
    if _decode_wem_to_ogg(main_bytes, target):
        return [{"id": "full", "file": "stems/full.ogg", "default": True}], target

    sys.stderr.write(
        "warning: could not decode WEM stem; writing it verbatim with codec: wem. "
        "Install vgmstream (and vorbis tools for better quality) to enable "
        "WEM to OGG transcoding, or supply a pre decoded OGG with --audio.\n"
    )
    target = stems_dir / "full.wem"
    target.write_bytes(main_bytes)
    return (
        [{"id": "full", "file": "stems/full.wem", "codec": "wem", "default": True}],
        None,
    )


def convert_dds(dds_bytes: bytes, out_png: Path) -> bool:
    """Convert a DDS image to PNG. Tries ffmpeg first, then Pillow (DXT native)."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", "pipe:0", "-f", "png", str(out_png)],
            input=dds_bytes, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if proc.returncode == 0 and out_png.exists() and out_png.stat().st_size > 0:
            return True
    except FileNotFoundError:
        pass
    try:
        from PIL import Image  # type: ignore
        img = Image.open(io.BytesIO(dds_bytes))
        img.save(out_png, format="PNG")
        return True
    except Exception:
        return False
