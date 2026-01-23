# Claude Skill: YouTube Subtitle Downloader

This skill wraps the existing `run_downloader.py` logic so Claude (or any
automation) can drive subtitle downloads without crafting CLI commands. The
runner reads a JSON request, executes the download via the refactored
`downloader` library, converts the resulting subtitles to Markdown, and emits
either a single Markdown file or a `.zip` archive (when multiple files are
produced).

## Features

- **Automatic yt-dlp version management**: Checks yt-dlp version before each
  download and auto-updates if outdated (configurable via `auto_update_ytdlp`)
- **Version reporting**: Response includes yt-dlp version info for diagnostics
- **Incremental downloads**: Only fetches new videos from a channel
- **Markdown artifacts**: Converts subtitles to Markdown for easy consumption

## Entry Point

```bash
python skills/download.py --input request.json --artifact-dir skill-artifacts
```

- `--input` (default: `-`) – path to a JSON payload. Use `-` to read from
  stdin.
- `--artifact-dir` (default: `skill-artifacts`) – directory where Markdown
  outputs (and optional ZIP bundles) are written.
- `--log-level` – overrides the downloader logger level (defaults to `INFO`).

## Request Schema

All fields are optional unless marked *required* for a given mode.

| Field | Type | Description |
| --- | --- | --- |
| `mode` | string | `"video"` or `"channel"`. Defaults to `"video"` if `video_url` is supplied, otherwise `"channel"`. |
| `video_url` | string | *Required in video mode.* Link to the YouTube video. |
| `channel` / `channel_name` | string | Channel handle (with or without `@`). Required for channel mode unless `video_url` is provided (single video mode can auto-detect). |
| `limit` | int | Only process the first `N` channel entries. `null`/`0` = no limit. |
| `full` | bool | Force full re-download (ignores incremental skips). |
| `incremental` | bool | If `false`, process every fetched entry unless `full` is also `false`. Default `true`. |
| `output_dir` | string | Override output folder (defaults to `from-channel-<slug>`). |
| `urls_file` | string | Custom playlist list file (defaults to `<channel>-list.txt`). |
| `cookie_file` | string | Path to `cookies.txt` (defaults to `./cookies.txt`). |
| `write_summary` | bool | (Video mode only) Append to `subtitles_summary.csv`. Defaults to `true`. |
| `artifact_dir` | string | Override where Markdown/ZIP artifacts are written. |
| `log_level` | string | Per-request log level (falls back to CLI arg / env). |
| `auto_update_ytdlp` | bool | Auto-update yt-dlp if outdated. Default `true`. |

## Example Requests

### Single Video

```json
{
  "mode": "video",
  "video_url": "https://www.youtube.com/watch?v=abc123",
  "channel": "DanKoeTalks",
  "cookie_file": "cookies.txt"
}
```

### Channel Batch

```json
{
  "mode": "channel",
  "channel": "@DanKoeTalks",
  "limit": 5,
  "full": false,
  "incremental": true,
  "cookie_file": "cookies.txt",
  "artifact_dir": "skill-artifacts/dankoe"
}
```

### Disable Auto-Update

```json
{
  "mode": "video",
  "video_url": "https://www.youtube.com/watch?v=abc123",
  "auto_update_ytdlp": false
}
```

## Response Shape

`skills/download.py` prints a JSON object to stdout:

```json
{
  "status": "success",
  "mode": "channel",
  "artifact_type": "zip",
  "artifact_path": "skill-artifacts/subtitles-20240101-120000.zip",
  "markdown_files": ["skill-artifacts/YouTube - Channel - Video.md", "..."],
  "results": [...],
  "zip_path": "skill-artifacts/subtitles-20240101-120000.zip",
  "ytdlp_version": "2025.12.8",
  "ytdlp_outdated": false,
  "ytdlp_age_days": 15
}
```

### Response Fields

| Field | Description |
| --- | --- |
| `status` | `"success"` or `"error"` |
| `mode` | `"video"` or `"channel"` |
| `artifact_type` | `"markdown"` (single file), `"zip"` (bundle), or `"none"` |
| `artifact_path` | Path to the primary artifact file |
| `markdown_files` | Array of all generated Markdown file paths |
| `results` | Array of `VideoDownloadResult` objects |
| `ytdlp_version` | Installed yt-dlp version |
| `ytdlp_outdated` | `true` if version is older than 30 days |
| `ytdlp_age_days` | Age of the installed version in days |
| `ytdlp_warning` | Warning message if version issues detected |

## yt-dlp Version Management

YouTube frequently changes its API, which can break subtitle downloads. The
skill includes automatic version management:

1. **Version Check**: Before each download, checks if yt-dlp is current
2. **Auto-Update**: If outdated (>30 days or below minimum), automatically
   updates via `uv pip` or `pip`
3. **Diagnostics**: Response always includes version info for troubleshooting

### Minimum Version

The skill enforces a minimum recommended version (`2025.12.01`) that handles
YouTube's PO token requirements for subtitle access.

### Troubleshooting

If downloads fail with "no subtitles" errors:

1. Check `ytdlp_warning` in the response
2. Manually update: `pip install --upgrade yt-dlp`
3. Refresh `cookies.txt` if authentication issues persist

## Project Structure

```
Youtube-Subtitle-Downloader/
├── downloader/
│   ├── __init__.py      # Public API exports
│   ├── core.py          # Main download logic
│   ├── artifacts.py     # Markdown/ZIP generation
│   └── version.py       # yt-dlp version management
├── skills/
│   └── download.py      # JSON skill runner
├── run_downloader.py    # CLI entry point
├── vtt2txt.py           # VTT to text converter
├── cookies.txt          # YouTube auth cookies
├── SKILL.md             # This file
└── CLAUDE.md            # Project documentation
```

## Notes

- The script injects the repository root onto `PYTHONPATH`, so it must live
  inside the project checkout.
- `cookies.txt` still needs to be supplied (either via default location or
  `cookie_file`). Export using browser extension "Get cookies.txt LOCALLY".
- Artifacts are written in plain Markdown using sanitized filenames derived
  from the subtitle text files. When multiple videos are downloaded the script
  bundles the Markdown files into a ZIP archive for easy transfer to Claude.
