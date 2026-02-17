# YouTube Channel Subtitle Downloader

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![yt-dlp](https://img.shields.io/badge/yt--dlp-required-green)
![Whisper](https://img.shields.io/badge/whisper-optional-yellow)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

A command-line tool that downloads subtitles from YouTube channels or individual videos, converts them to plain text, and generates metadata summaries. When no subtitles are available, it can fall back to local transcription using OpenAI Whisper.

Inspired by the scripts used in https://www.youtube.com/watch?v=ND_87nkh-sI

## Features

- **Channel & single-video modes** — download subtitles from an entire channel or a single URL
- **Incremental downloads** — only fetches new videos on subsequent runs
- **Whisper fallback** — transcribes audio locally when no subtitles or auto-captions exist
- **Print mode** — pipe subtitle text to stdout with `-p`
- **Enriched CSV tracking** — logs video metadata, duration, and subtitle source (`manual` / `auto-caption` / `whisper`)

## Requirements
- Python 3.9 or later (3.10+ recommended by `yt-dlp`)
- `cookies.txt` exported from your browser (needed so YouTube serves subtitles reliably)
- **Optional:** [OpenAI Whisper](https://github.com/openai/whisper) + `ffmpeg` for transcription fallback

### Set Up A Virtual Environment

**Option 1: Using `uv` (recommended - faster, no activation needed)**

```bash
# Install uv if you don't have it: https://docs.astral.sh/uv/
uv venv
uv pip install yt-dlp
uv pip install openai-whisper  # optional: enables Whisper transcription fallback
```

With `uv`, you can run commands directly without activating. For example:
```bash
uv run python3 run_downloader.py -c DanKoeTalks --limit 10
```

**Option 2: Using standard Python venv**

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install yt-dlp
pip install openai-whisper  # optional
```

When you are done, deactivate with `deactivate`.

### Exporting `cookies.txt`
1. Install the Chrome extension **Get cookies.txt LOCALLY** (from the Chrome Web Store).
2. Open the target YouTube channel in Chrome, ensure you are signed in, and let the page finish loading.
3. Click the extension icon and choose **Export cookies**. Save the file as `cookies.txt` in this project directory (or point `--cookie-file` to the saved path).
4. Re-export whenever your YouTube session expires.

## Usage

> **Note:** If using `uv`, prefix commands with `uv run`. Otherwise, activate your venv first.

### Download from a Channel (Incremental)

By default, the script operates in **incremental mode**, downloading only new videos that haven't been processed yet:

```bash
python3 run_downloader.py -c DanKoeTalks --limit 10   # process first 10 videos
python3 run_downloader.py -c DanKoeTalks              # subsequent runs pull only new videos
python3 run_downloader.py -c @ChannelName             # download all videos
```
Prefix with `uv run` if you're using `uv`.

### Download from a Single Video

Download subtitles from a single video and add it to the channel's output folder:

```bash
python3 run_downloader.py -v "https://youtube.com/watch?v=abc123"
```
- Add `-c DanKoeTalks` to force the output into a specific channel folder.
- Add `-p` to print the subtitle to stdout instead of writing a file (single video only).
- Omit `-c` to auto-detect the channel from video metadata.
Prefix with `uv run` if you're using `uv`.

### Force Full Re-download

Use `--full` to re-download all videos, ignoring existing subtitles:

```bash
uv run python3 run_downloader.py -c DanKoeTalks --full
```

### Whisper Transcription Fallback

When a video has no subtitles or auto-captions, the script automatically downloads audio and transcribes it locally using OpenAI Whisper:

```bash
python3 run_downloader.py -v "https://youtube.com/watch?v=abc123" --whisper-model small
python3 run_downloader.py -c ChannelName --no-whisper   # disable fallback
```

If `openai-whisper` is not installed, the fallback is skipped gracefully (no crash).

### Arguments
- `-c`, `--channel` – Channel handle (with or without the leading `@`). Required for channel mode, optional for single video mode.
- `-v`, `--video` – Download subtitles from a single video URL instead of entire channel.
- `-p`, `--print` – Print subtitle to stdout instead of saving to file. Only works with single video mode (`-v`).
- `--limit N` *(default: 0)* – Process only the first N videos from channel. `0` means no limit (download all videos).
- `--whisper-model` *(default: base)* – Whisper model size: `tiny`, `base`, `small`, `medium`, `large`.
- `--no-whisper` – Disable Whisper transcription fallback entirely.
- `--log-level` *(default: INFO)* – Adjust verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- `--output-dir` – Override the default output directory (`downloads/from-channel-<channel>`).
- `--cookie-file` – Path to cookies.txt file (default: `./cookies.txt`).
- `--urls-file` – Path for the intermediate playlist file (default: `<channel>-list.txt`).
- `--full` – Force full re-download of all videos, ignoring existing subtitles (channel mode only).

## Output Structure

Subtitles are saved in `downloads/from-channel-<channel>/`:

```
downloads/
└── from-channel-<channel>/
    ├── final/
    │   └── YouTube - <channel> - <title>.txt
    ├── subtitles_summary.csv
    └── <channel>-list.txt
```

- `final/YouTube - <channel> - <title>.txt` – cleaned subtitle with header (title, URL, upload date) + single-language body.
- `subtitles_summary.csv` – metadata summary with columns: `video_id`, `title`, `url`, `upload_date`, `duration`, `subtitle_path`, `languages`, `subtitle_source`.
- `<channel>-list.txt` – playlist of video URLs processed in the most recent run.

## Notes
- **Incremental downloads**: By default, the script tracks processed videos in `subtitles_summary.csv` and skips them on subsequent runs. Use `--full` to override this behavior.
- **Single video mode**: Videos are added to the same `downloads/from-channel-<channel>/` structure and appended to the existing CSV.
- **Whisper fallback**: When no subtitles exist, the script downloads audio, transcribes with Whisper, and outputs sentence-level line breaks. The `subtitle_source` CSV column tracks how each video's text was obtained.
- The script currently saves only the highest-priority subtitle language (English preferred). Adjust `determine_languages` in `run_downloader.py` if you need multi-language subtitles.
- Hitting rate limits (HTTP 429) typically means YouTube is throttling requests. Re-run after a short pause or provide fresh cookies.

## Migration from Old Version

If you have existing folders named `all-transcript-from-<channel>` from a previous version, you can:

1. **Rename the folder** to match the new format:
   ```bash
   mkdir -p downloads
   mv all-transcript-from-DanKoeTalks downloads/from-channel-DanKoeTalks
   ```

2. **Rename the CSV file** inside the folder:
   ```bash
   cd downloads/from-channel-DanKoeTalks
   mv transcripts_summary.csv subtitles_summary.csv
   ```

3. **Update the CSV header** (optional, for consistency):
   - Open `subtitles_summary.csv` and change the header `transcript_path` to `subtitle_path`

The script will recognize the existing data and continue in incremental mode.
