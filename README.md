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
python3 run_channel_downloader.py \
  --channel-url "https://www.youtube.com/@DanKoeTalks/videos" \
  --output-dir DanKoe \
  --cookie-file cookies.txt \
  --urls-file playlist-DanKoe.txt \
  --limit 1 \
  --log-level INFO
```

### Arguments
- `--channel-url` *(default: Dan Koe channel)* – the channel “Videos” page to enumerate.
- `--output-dir` *(default: `DanKoe`)* – folder for raw VTT files, transcripts, and summary CSV.
- `--cookie-file` *(default: `cookies.txt`)* – passed to `yt-dlp` if present; omit or point to another file when not needed.
- `--urls-file` *(default: `playlist-DanKoe.txt`)* – where the script writes the discovered video URLs.
- `--limit` – optional cap on how many videos to process (omit to run the full channel).
- `--log-level` – standard logging level (e.g., `INFO`, `DEBUG`).

## Output Structure
- `<output-dir>/<video_id>/` – raw `.vtt` captions per processed video.
- `<output-dir>/final/<video_id>.txt` – cleaned transcript with header (title, URL, upload date) + single-language body.
- `<output-dir>/transcripts_summary.csv` – metadata summary: ID, title, URL, upload date, transcript path, languages downloaded.

## Notes
- The script currently saves only the highest-priority subtitle language (English preferred). Adjust `determine_languages` in `run_channel_downloader.py` if you need multi-language transcripts again.
- Hitting rate limits (HTTP 429) typically means YouTube is throttling requests. Re-run after a short pause or provide fresh cookies.
