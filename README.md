# feedpak

Convert Rocksmith 2014 CDLC `.psarc` archives into [feedpak v1](https://got-feedback.github.io/feedpak-spec/feedpak-v1.html) packages.

The converter decrypts the PSARC table of contents, unpacks and decrypts every SNG arrangement, picks the densest difficulty level for each chart, transcodes WEM audio to Ogg Vorbis, converts the DDS album art to PNG, and emits top level `lyrics.json` (plus a `lyric_tracks` block when the CDLC ships both `vocals` and `jvocals`).

Licensed under the WTFPL. See [LICENSE](LICENSE).

## Install

Pick whichever fits your workflow.

### uvx (zero install, runs from git)

```bash
uvx --from git+https://github.com/HRNPH/feedpak feedpak song.psarc out/song.feedpak -z
```

### pip from git

```bash
pip install git+https://github.com/HRNPH/feedpak
feedpak song.psarc out/song.feedpak -z
```

### Local development clone

```bash
git clone https://github.com/HRNPH/feedpak
cd feedpak
uv sync
uv run feedpak song.psarc out/song.feedpak -z
```

## External binaries

Python handles the PSARC, SNG, lyrics, DDS, and manifest work. Two external binaries are required for audio transcoding:

| Binary            | Purpose                          | Install                           |
| ----------------- | -------------------------------- | --------------------------------- |
| `vgmstream-cli`   | WEM to WAV decoding              | `brew install vgmstream`          |
| `oggenc` or `ffmpeg` | WAV to Ogg Vorbis encoding    | `brew install vorbis-tools` (preferred) or `brew install ffmpeg` |
| `ffprobe`         | OGG duration probing (optional)  | bundled with ffmpeg               |

If `vgmstream-cli` is missing the converter still runs but writes the raw WEM bytes with a `codec: wem` marker instead of transcoding.

## Usage

```bash
feedpak SRC OUT [-z] [--audio PATH]
```

* `SRC` is a `.psarc` archive.
* `OUT` is a directory (default) or a `.feedpak` zip path (with `-z`).
* `-z` / `--zip` produces a single zip file. Recommended for upload or sharing.
* `--audio PATH` overrides the embedded WEM with a pre decoded OGG or WAV.

### Examples

Emit a `.feedpak` zip:

```bash
feedpak song.psarc out/song.feedpak -z
```

Emit an unpacked directory (handy for inspection):

```bash
feedpak song.psarc out/song.feedpak
```

Override the embedded audio:

```bash
feedpak song.psarc out/song.feedpak -z --audio path/to/full.ogg
```

Run as a module without installing:

```bash
uv run python -m feedpak song.psarc out/song.feedpak -z
```

## Output layout

```
song.feedpak/
├── manifest.yaml          # feedpak v1 manifest (arrangements, stems, lyrics)
├── arrangements/
│   ├── lead.json          # one chart per arrangement
│   ├── rhythm.json
│   └── bass.json
├── lyrics.json            # primary lyrics (Japanese when jvocals present)
├── lyrics_romaji.json     # romaji transliteration (when both tracks exist)
├── stems/
│   └── full.ogg           # transcoded from the embedded WEM
└── gfx/
    └── cover.png          # album art (converted from DDS)
```

## Batch conversion

A small shell helper, [`convert_all.sh`](convert_all.sh), recursively converts every `.psarc` under `song_lib/source/` into `song_lib/feedpak/`, skipping outputs that already exist.

```bash
./convert_all.sh             # skip already parsed
./convert_all.sh --force     # re convert everything
```

## Package layout

The converter is split into focused modules under `feedpak/`:

| Module        | Responsibility                                                       |
| ------------- | ------------------------------------------------------------------- |
| `psarc.py`    | PSARC container: AES CFB TOC decrypt + zlib block reassembly        |
| `sng.py`      | SNG file: AES CTR decrypt + binary body parser                       |
| `chart.py`    | Parsed SNG to feedpak arrangement dict (notes, chords, anchors)     |
| `lyrics.py`   | RS2014 vocals to feedpak `{t, d, w}` syllable schema                 |
| `media.py`    | WEM to OGG transcoding and DDS to PNG conversion                    |
| `metadata.py` | Song level fields from the RS2014 manifest JSON                     |
| `convert.py`  | Top level orchestration tying the above stages together             |
| `cli.py`      | Argparse entry point (`feedpak` command)                            |
| `binary.py`   | Small little endian byte cursor used by the SNG parser              |
| `constants.py`| AES keys, magic numbers, and note technique bit masks               |

## License

DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE, Version 2. See [LICENSE](LICENSE).
