"""Command line entry point.

Invocable as ``feed-parse SRC OUT [-z] [--audio PATH]``. The ``feed-parse``
command is registered by ``pyproject.toml`` via the
``feed_parse.cli:main`` script entry point.
"""

import argparse
import sys
from pathlib import Path

from .convert import convert

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="feed-parse",
        description="Convert a Rocksmith .psarc into a feedpak v1 package.",
    )
    ap.add_argument("src", help="source .psarc path")
    ap.add_argument("out", help="output directory (or .feedpak path with -z)")
    ap.add_argument(
        "-z", "--zip", action="store_true",
        help="emit a .feedpak zip instead of a directory",
    )
    ap.add_argument(
        "--audio", type=Path,
        help="path to a pre decoded OGG/WAV to use as the full stem",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = convert(Path(args.src), Path(args.out), args.audio, args.zip)
    print(f"wrote {result}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
