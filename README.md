# YouTube Channel Subtitle Downloader

A command-line helper that downloads subtitles from YouTube channels or individual videos, converts them to plain text, and emits a metadata summary. The script uses `yt-dlp` under the hood and saves one subtitle per video. Supports incremental downloads to fetch only new videos from a channel.

Inspired by the scripts used in https://www.youtube.com/watch?v=ND_87nkh-sI

## Requirements
- Python 3.9 or later (3.10+ recommended by `yt-dlp`)
- `cookies.txt` exported from your browser (needed so YouTube serves subtitles reliably)

### Set Up A Virtual Environment
Creating an isolated environment keeps dependencies contained. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install yt-dlp
```

When you are done, deactivate with `deactivate`.

> Already have a venv? Just run `pip install yt-dlp` inside it to pull the lone dependency.

### Exporting `cookies.txt`
1. Install the Chrome extension **Get cookies.txt LOCALLY** (from the Chrome Web Store).
2. Open the target YouTube channel in Chrome, ensure you are signed in, and let the page finish loading.
3. Click the extension icon and choose **Export cookies**. Save the file as `cookies.txt` in this project directory (or point `--cookie-file` to the saved path).
4. Re-export whenever your YouTube session expires.

## Usage

### Download from a Channel (Incremental)

By default, the script operates in **incremental mode**, downloading only new videos that haven't been processed yet:

```bash
# First run - downloads all videos (or up to --limit)
python3 run_channel_downloader.py DanKoeTalks --limit 10 --log-level INFO

# Second run - only downloads new videos since last run
python3 run_channel_downloader.py DanKoeTalks
```

### Download from a Single Video

Download subtitles from a single video and add it to the channel's output folder:

```bash
# With channel name specified
python3 run_channel_downloader.py --video-url "https://youtube.com/watch?v=abc123" --channel-name DanKoeTalks

# Auto-detect channel from video metadata
python3 run_channel_downloader.py --video-url "https://youtube.com/watch?v=abc123"
```

### Force Full Re-download

Use `--full` to re-download all videos, ignoring existing subtitles:

```bash
python3 run_channel_downloader.py DanKoeTalks --full
```

### Arguments
- `channel_name` – the channel handle (with or without the leading `@`). Required for channel mode, optional for single video mode.
- `--video-url` – download subtitles from a single video instead of entire channel.
- `--log-level` *(default: `INFO`)* – adjust verbosity (`DEBUG`, `WARNING`, etc.).
- `--limit` *(default: `0`)* – cap how many videos to process; `0` means "download every video" (channel mode only).
- `--output-dir` – override the default output directory (`from-channel-<channel>`).
- `--cookie-file` – point to a different cookies export (default `./cookies.txt`).
- `--urls-file` – override where the intermediate playlist file is written (default `<channel>-list.txt` inside the output directory).
- `--full` – force full re-download of all videos, ignoring existing subtitles (channel mode only).

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
