# YouTube Channel Subtitle Downloader

A command-line helper that bulk downloads subtitles from a YouTube channel, converts them to plain text, and emits a metadata summary. The script uses `yt-dlp` under the hood and saves one transcript per video.
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
Run the downloader from this directory:

```bash
python3 run_channel_downloader.py DanKoeTalks --limit 10 --log-level INFO
```

### Arguments
- `channel_name` *(required)* – the channel handle (with or without the leading `@`).
- `--log-level` *(default: `INFO`)* – adjust verbosity (`DEBUG`, `WARNING`, etc.).
- `--limit` *(default: `0`)* – cap how many videos to process; `0` means "download every video".
- `--output-dir` – override the default output directory (`all-transcript-from-<channel>`).
- `--cookie-file` – point to a different cookies export (default `./cookies.txt`).
- `--urls-file` – override where the intermediate playlist file is written (default `<channel>-list.txt` inside the output directory).

## Output Structure
- `<output-dir>/final/YouTube - <channel> - <title>.txt` – cleaned transcript with header (title, URL, upload date) + single-language body.
- `<output-dir>/transcripts_summary.csv` – metadata summary: ID, title, URL, upload date, transcript path, languages downloaded.
- `<output-dir>/<channel>-list.txt` – playlist of video URLs processed in the run.

## Notes
- The script currently saves only the highest-priority subtitle language (English preferred). Adjust `determine_languages` in `run_channel_downloader.py` if you need multi-language transcripts again.
- Hitting rate limits (HTTP 429) typically means YouTube is throttling requests. Re-run after a short pause or provide fresh cookies.
