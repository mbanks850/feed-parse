#!/usr/bin/env bash
# convert_all.sh : batch convert every .psarc under song_lib/source/ into a
# .feedpak zip under song_lib/feedpak/. Skips files that already have an
# output unless --force is given.
#
# Uses the locally installed `feedpak` command from this project's venv.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/song_lib/source"
OUTPUT_DIR="${SCRIPT_DIR}/song_lib/feedpak"
FORCE=0

usage() {
    cat <<EOF
Usage: $0 [--force]

Recursively converts every .psarc file in:
  $SOURCE_DIR
into a .feedpak zip in:
  $OUTPUT_DIR

Mirrors the subdirectory structure. Skips outputs that already exist
unless --force is given.

  --force       convert again even when the output already exists
  -h, --help    show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
    esac
done

# Make sure the venv exists.
if [[ ! -x "$SCRIPT_DIR/.venv/bin/feed-parse" ]]; then
    echo "Bootstrapping venv (uv sync)..."
    (cd "$SCRIPT_DIR" && uv sync)
fi

CLI="$SCRIPT_DIR/.venv/bin/feed-parse"
if [[ ! -x "$CLI" ]]; then
    echo "feed-parse CLI not found at $CLI" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Enumerate source files (case insensitive .psarc match), sorted for stable runs.
mapfile -t FILES < <(find "$SOURCE_DIR" -type f -iname '*.psarc' | sort)

TOTAL=${#FILES[@]}
if [[ $TOTAL -eq 0 ]]; then
    echo "No .psarc files in $SOURCE_DIR"
    exit 0
fi

WIDTH=${#TOTAL}
CONVERTED=0
SKIPPED=0
FAILED=0
I=0

start=$(date +%s)
echo "Converting $TOTAL PSARC file(s)..."
echo

shopt -s nocasematch
for SRC in "${FILES[@]}"; do
    I=$((I+1))
    REL="${SRC#$SOURCE_DIR/}"
    OUT_REL="${REL%.psarc}.feedpak"
    OUT="$OUTPUT_DIR/$OUT_REL"

    if [[ -e "$OUT" && $FORCE -eq 0 ]]; then
        printf "  [%*d/%d] SKIP    %s\n" "$WIDTH" "$I" "$TOTAL" "$REL"
        SKIPPED=$((SKIPPED+1))
        continue
    fi

    printf "  [%*d/%d] CONVERT %s ... " "$WIDTH" "$I" "$TOTAL" "$REL"
    mkdir -p "$(dirname "$OUT")"
    LOG=$(mktemp -t feedpak_convert)
    if "$CLI" "$SRC" "$OUT" -z >"$LOG" 2>&1; then
        printf "OK\n"
        CONVERTED=$((CONVERTED+1))
    else
        printf "FAIL\n"
        sed 's/^/      /' "$LOG" >&2
        FAILED=$((FAILED+1))
        # Clean partial output so the next run can retry cleanly.
        rm -f "$OUT"
    fi
    rm -f "$LOG"

    # Live progress estimate.
    now=$(date +%s)
    elapsed=$((now - start))
    avg=$((elapsed / I))
    remaining=$((avg * (TOTAL - I)))
    printf "      (%ds elapsed, ~%ds remaining)\n" "$elapsed" "$remaining"
done
shopt -u nocasematch

echo
echo "Done: $CONVERTED converted, $SKIPPED skipped, $FAILED failed ($TOTAL total)"
[[ $FAILED -eq 0 ]]
