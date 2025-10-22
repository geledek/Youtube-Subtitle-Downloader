# YouTube Channel Subtitle Downloader

A command-line helper that downloads subtitles from YouTube channels or individual videos, converts them to plain text, and emits a metadata summary. The script uses `yt-dlp` under the hood and saves one subtitle per video. Supports incremental downloads to fetch only new videos from a channel.

Inspired by the scripts used in https://www.youtube.com/watch?v=ND_87nkh-sI

## Requirements
- Python 3.9 or later (3.10+ recommended by `yt-dlp`)
- `cookies.txt` exported from your browser (needed so YouTube serves subtitles reliably)

### Set Up A Virtual Environment

**Option 1: Using `uv` (recommended - faster, no activation needed)**

```bash
# Install uv if you don't have it: https://docs.astral.sh/uv/
uv venv
uv pip install yt-dlp
```

With `uv`, you can run commands directly without activating:
```bash
uv run python3 run_channel_downloader.py -c DanKoeTalks --limit 10
```

**Option 2: Using standard Python venv**

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install yt-dlp
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
# Using uv (no activation needed)
uv run python3 run_channel_downloader.py -c DanKoeTalks --limit 10

# Or with activated venv
python3 run_channel_downloader.py -c DanKoeTalks --limit 10

# Second run - only downloads new videos since last run
uv run python3 run_channel_downloader.py -c DanKoeTalks

# Download all videos (no limit)
uv run python3 run_channel_downloader.py -c @ChannelName
```

### Download from a Single Video

Download subtitles from a single video and add it to the channel's output folder:

```bash
# With channel name specified
uv run python3 run_channel_downloader.py -v "https://youtube.com/watch?v=abc123" -c DanKoeTalks

# Auto-detect channel from video metadata
uv run python3 run_channel_downloader.py -v "https://youtube.com/watch?v=abc123"

# Print subtitles to stdout instead of saving to file (single video only)
uv run python3 run_channel_downloader.py -v "https://youtube.com/watch?v=abc123" -p
```

### Force Full Re-download

Use `--full` to re-download all videos, ignoring existing subtitles:

```bash
uv run python3 run_channel_downloader.py -c DanKoeTalks --full
```

### Arguments
- `-c`, `--channel` – Channel handle (with or without the leading `@`). Required for channel mode, optional for single video mode.
- `-v`, `--video` – Download subtitles from a single video URL instead of entire channel.
- `-p`, `--print` – Print subtitle to stdout instead of saving to file. Only works with single video mode (`-v`).
- `--limit N` *(default: 0)* – Process only the first N videos from channel. `0` means no limit (download all videos).
- `--log-level` *(default: INFO)* – Adjust verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- `--output-dir` – Override the default output directory (`from-channel-<channel>`).
- `--cookie-file` – Path to cookies.txt file (default: `./cookies.txt`).
- `--urls-file` – Path for the intermediate playlist file (default: `<channel>-list.txt`).
- `--full` – Force full re-download of all videos, ignoring existing subtitles (channel mode only).

## Output Structure

Subtitles are saved in a folder named `from-channel-<channel>/`:

```
from-channel-<channel>/
├── final/
│   └── YouTube - <channel> - <title>.txt
├── subtitles_summary.csv
└── <channel>-list.txt
```

- `final/YouTube - <channel> - <title>.txt` – cleaned subtitle with header (title, URL, upload date) + single-language body.
- `subtitles_summary.csv` – metadata summary: ID, title, URL, upload date, subtitle path, languages downloaded.
- `<channel>-list.txt` – playlist of video URLs processed in the most recent run.

## Notes
- **Incremental downloads**: By default, the script tracks processed videos in `subtitles_summary.csv` and skips them on subsequent runs. Use `--full` to override this behavior.
- **Single video mode**: Videos are added to the same `from-channel-<channel>/` structure and appended to the existing CSV.
- The script currently saves only the highest-priority subtitle language (English preferred). Adjust `determine_languages` in `run_channel_downloader.py` if you need multi-language subtitles.
- Hitting rate limits (HTTP 429) typically means YouTube is throttling requests. Re-run after a short pause or provide fresh cookies.

## Migration from Old Version

If you have existing folders named `all-transcript-from-<channel>` from a previous version, you can:

1. **Rename the folder** to match the new format:
   ```bash
   mv all-transcript-from-DanKoeTalks from-channel-DanKoeTalks
   ```

2. **Rename the CSV file** inside the folder:
   ```bash
   cd from-channel-DanKoeTalks
   mv transcripts_summary.csv subtitles_summary.csv
   ```

3. **Update the CSV header** (optional, for consistency):
   - Open `subtitles_summary.csv` and change the header `transcript_path` to `subtitle_path`

The script will recognize the existing data and continue in incremental mode.
