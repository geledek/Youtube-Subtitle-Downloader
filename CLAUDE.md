# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A command-line tool that downloads subtitles from YouTube channels or individual videos using `yt-dlp`. The script converts VTT subtitle files to plain text, removes duplicates, and generates metadata summaries. Supports incremental downloads to fetch only new videos from a channel.

## Key Commands

### Setup
```bash
# Using uv (recommended - faster, no activation needed)
uv venv
uv pip install yt-dlp

# Using standard venv
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install yt-dlp
```

### Running the Downloader
```bash
# Channel mode (incremental by default)
python3 run_downloader.py -c DanKoeTalks --limit 10
python3 run_downloader.py -c DanKoeTalks  # subsequent runs only fetch new videos

# Single video mode
python3 run_downloader.py -v "https://youtube.com/watch?v=abc123"
python3 run_downloader.py -v "URL" -p  # print to stdout instead of saving

# Force full re-download
python3 run_downloader.py -c DanKoeTalks --full

# With uv, prefix commands with: uv run python3 ...
```

### VTT to Text Conversion (Standalone)
```bash
python3 vtt2txt.py file1.vtt file2.vtt
python3 vtt2txt.py /path/to/directory  # processes all .vtt files recursively
```

## Architecture

### Two-Script Design

1. **run_downloader.py** - Main orchestrator (645 lines)
   - Entry point and command-line interface
   - Channel video discovery via yt-dlp flat extraction
   - Incremental download tracking via CSV
   - Subtitle download coordination (per-language)
   - File organization and metadata management
   - Retry logic with exponential backoff

2. **vtt2txt.py** - VTT subtitle converter (45 lines)
   - Standalone utility that converts WebVTT to plain text
   - Strips timing, headers, inline tags, and HTML entities
   - Global deduplication of subtitle lines
   - Called by run_downloader.py after each subtitle download

### Data Flow

```
Channel URL → yt-dlp (flat) → Video list → Filter (incremental) → For each video:
  1. Fetch metadata
  2. Determine subtitle languages (prefer en, then zh variants)
  3. Download VTT files (subtitles + auto-captions from allowlist)
  4. Convert VTT → TXT via vtt2txt.py
  5. Build final subtitle file with header (title, URL, date, channel)
  6. Append row to subtitles_summary.csv
  7. Clean up intermediate directory
```

### Output Structure

All outputs are written to `from-channel-<channel>/`:
```
from-channel-<channel>/
├── final/
│   └── YouTube - <channel> - <title>.txt  # final subtitle with metadata header
├── subtitles_summary.csv                   # CSV tracking all processed videos
└── <channel>-list.txt                      # URLs from most recent run
```

### Key Design Decisions

- **Incremental mode**: By default, `subtitles_summary.csv` tracks processed video IDs. New runs skip already-downloaded videos. Use `--full` to override.

- **Language selection**: `determine_languages()` (run_downloader.py:179) returns only the highest-priority language. Priority order: en variants → zh variants → other. Controlled by `AUTO_CAPTION_ALLOWLIST` (run_downloader.py:17).

- **Single video mode**: Videos are added to the same `from-channel-<channel>/` structure. If no channel is provided via `-c`, the script extracts it from video metadata.

- **Print mode (`-p`)**: Single video mode only. Prints subtitle to stdout and skips file creation. Useful for piping to other tools.

- **Retry logic**: `retry()` wrapper (run_downloader.py:86) handles transient failures with exponential backoff (3 attempts, 5s base delay).

- **Cookies requirement**: YouTube serves subtitles more reliably when authenticated. Export `cookies.txt` using browser extension "Get cookies.txt LOCALLY".

- **Deduplication**: `vtt2txt.py` uses a global `seen` set to remove duplicate subtitle lines within each video.

## Important Constraints

- Only downloads one language per video (highest priority from `determine_languages`)
- Auto-captions are only downloaded for languages in `AUTO_CAPTION_ALLOWLIST`
- Rate limiting (HTTP 429) typically means YouTube is throttling; re-run after pause or refresh cookies
- The script expects Python 3.9+ (3.10+ recommended by yt-dlp)
