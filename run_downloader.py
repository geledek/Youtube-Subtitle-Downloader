import argparse
import csv
import logging
import os
import pathlib
import re
import shutil
import time
from typing import Dict, Iterable, List, Optional, Tuple

import yt_dlp

from vtt2txt import process as vtt_to_txt

try:
    import whisper_transcribe

    _whisper_available = True
except ImportError:
    _whisper_available = False

logger = logging.getLogger("channel_downloader")

AUTO_CAPTION_ALLOWLIST = {
    "en",
    "en-US",
    "en-GB",
    "en-CA",
    "en-AU",
    "en-IN",
    "zh",
    "zh-CN",
    "zh-TW",
    "zh-Hans",
    "zh-Hant",
}

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


def configure_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
    logger.setLevel(level)


def ensure_cookiefile(opts: Dict, cookie_path: pathlib.Path) -> None:
    if cookie_path.exists():
        opts["cookiefile"] = str(cookie_path)
    elif "cookiefile" in opts:
        opts.pop("cookiefile", None)


def get_channel_video_entries(
    channel_url: str, *, cookie_path: pathlib.Path
) -> Optional[List[Dict]]:
    """Return basic metadata for every video listed on the channel."""
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
    }
    ensure_cookiefile(ydl_opts, cookie_path)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(channel_url, download=False)
    except Exception as exc:  # pragma: no cover - network failure path
        logger.error("Failed to fetch channel listing: %s", exc)
        return None

    entries = []
    for entry in result.get("entries", []):
        url = entry.get("url")
        if not url:
            continue
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        entries.append(
            {
                "id": entry.get("id"),
                "title": entry.get("title"),
                "url": url,
            }
        )
    return entries


def retry(operation, *, max_attempts: int = 3, delay_seconds: float = 5.0):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - runtime resilience
            last_error = exc
            logger.warning(
                "Attempt %s/%s failed with error: %s", attempt, max_attempts, exc
            )
            if attempt < max_attempts:
                sleep_time = delay_seconds * attempt
                logger.info("Retrying in %.1f seconds...", sleep_time)
                time.sleep(sleep_time)
    raise last_error  # noqa: RAS003


def format_upload_date(raw: Optional[str]) -> str:
    if not raw:
        return "Unknown"
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def collect_language_order(langs: Iterable[str]) -> List[str]:
    priority = [
        "en",
        "en-US",
        "en-GB",
        "zh-Hans",
        "zh-Hant",
        "zh-CN",
        "zh-TW",
    ]
    ordered = []
    for fav in priority:
        for lang in langs:
            if lang == fav and lang not in ordered:
                ordered.append(lang)
    for lang in langs:
        if lang not in ordered:
            ordered.append(lang)
    return ordered


def write_summary_row(summary_path: pathlib.Path, row: List[str]) -> None:
    write_header = not summary_path.exists()
    with summary_path.open("a", encoding="utf-8", newline="") as csvfile:
        writer = csv.writer(csvfile)
        if write_header:
            writer.writerow(
                [
                    "video_id",
                    "title",
                    "url",
                    "upload_date",
                    "duration",
                    "subtitle_path",
                    "languages",
                    "subtitle_source",
                ]
            )
        writer.writerow(row)


def sanitize_filename(value: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "output"
    # Avoid trailing periods/spaces that some file systems dislike.
    cleaned = cleaned.rstrip(" .")
    return cleaned[:200]


def normalize_channel_name(name: str) -> str:
    slug = name.strip()
    if not slug:
        raise ValueError("Channel name cannot be empty.")
    if slug.startswith("@"):
        slug = slug[1:]
    return slug


def cleanup_intermediate_dir(directory: pathlib.Path) -> None:
    if not directory.exists():
        return
    try:
        shutil.rmtree(directory)
        logger.debug("Removed intermediate directory %s", directory)
    except Exception as exc:  # pragma: no cover - filesystem variance
        logger.warning("Unable to remove intermediate directory %s: %s", directory, exc)


def download_audio(
    video_url: str,
    video_dir: pathlib.Path,
    video_id: str,
    *,
    cookie_path: pathlib.Path,
) -> Optional[pathlib.Path]:
    """Download audio from a video and extract to WAV format."""
    audio_path = video_dir / f"{video_id}.wav"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(video_dir / f"{video_id}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }
        ],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    ensure_cookiefile(ydl_opts, cookie_path)

    try:
        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

        retry(_download)
    except Exception as exc:
        logger.warning("Failed to download audio for %s: %s", video_url, exc)
        return None

    if audio_path.exists():
        return audio_path

    logger.warning("Audio file not found at %s after download", audio_path)
    return None


def determine_languages(info: Dict) -> List[str]:
    languages = set()
    for lang in (info.get("subtitles") or {}).keys():
        languages.add(lang)
    for lang in (info.get("automatic_captions") or {}).keys():
        if lang in AUTO_CAPTION_ALLOWLIST:
            languages.add(lang)

    if not languages:
        fallback = info.get("language")
        if fallback:
            languages.add(fallback)
        else:
            languages.add("en")

    ordered = collect_language_order(sorted(languages))
    return ordered[:1]


def gather_subtitle_sections(
    video_dir: pathlib.Path, video_url: str
) -> Tuple[List[Tuple[str, str]], List[str]]:
    vtt_files = sorted(video_dir.glob("*.vtt"))
    whisper_files = sorted(video_dir.glob("*.whisper-*.txt"))

    if not vtt_files and not whisper_files:
        logger.warning("No subtitle files were downloaded for %s", video_url)
        return [], []

    language_to_content: Dict[str, str] = {}

    # Process VTT files
    for vtt_file in vtt_files:
        parts = vtt_file.stem.split(".")
        lang = parts[-1] if len(parts) > 1 else "unknown"
        try:
            vtt_to_txt(vtt_file)
        except Exception as exc:
            logger.warning("Failed to convert %s: %s", vtt_file, exc)
            continue
        txt_path = vtt_file.with_suffix(".txt")
        if not txt_path.exists():
            logger.warning("Missing converted text for %s", vtt_file)
            continue
        text_content = txt_path.read_text(encoding="utf-8").strip()
        if text_content:
            language_to_content[lang] = text_content

    # Process Whisper files (only if VTT didn't provide that language)
    for whisper_file in whisper_files:
        match = re.search(r"\.whisper-(.+)$", whisper_file.stem)
        if not match:
            continue
        lang = match.group(1)
        if lang in language_to_content:
            continue
        text_content = whisper_file.read_text(encoding="utf-8").strip()
        if text_content:
            language_to_content[lang] = text_content

    if not language_to_content:
        logger.warning("All subtitles empty or unavailable for %s", video_url)
        return [], []

    ordered = collect_language_order(language_to_content.keys())
    subtitle_sections = [(lang, language_to_content[lang]) for lang in ordered]
    unique_languages = list(dict.fromkeys(ordered))
    return subtitle_sections, unique_languages


def compose_subtitle_lines(
    info: Dict, subtitle_sections: List[Tuple[str, str]], video_url: str
) -> List[str]:
    header = [
        f"Title: {info.get('title') or 'Unknown'}",
        f"URL: {info.get('webpage_url') or video_url}",
        f"Upload Date: {format_upload_date(info.get('upload_date'))}",
    ]
    if info.get("channel"):
        header.append(f"Channel: {info['channel']}")

    lines = header + [""]
    for lang, text_content in subtitle_sections:
        lines.append(f"--- Subtitle ({lang}) ---")
        lines.append(text_content)
        lines.append("")
    return lines


def build_subtitle(
    info: Dict,
    video_dir: pathlib.Path,
    final_dir: pathlib.Path,
    video_url: str,
) -> Tuple[Optional[pathlib.Path], List[str]]:
    subtitle_sections, languages = gather_subtitle_sections(video_dir, video_url)
    if not subtitle_sections:
        return None, []

    final_dir.mkdir(parents=True, exist_ok=True)
    author = info.get("channel") or info.get("uploader") or "Unknown"
    title = info.get("title") or "Unknown Title"
    filename = sanitize_filename(f"YouTube - {author} - {title}") or "YouTube-Unknown"
    final_path = final_dir / f"{filename}.txt"
    counter = 1
    while final_path.exists():
        final_path = final_dir / f"{filename} ({counter}).txt"
        counter += 1

    lines = compose_subtitle_lines(info, subtitle_sections, video_url)
    final_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    logger.info("Subtitle saved to %s", final_path)
    return final_path, languages


def process_single_video(
    entry: Dict,
    output_dir: pathlib.Path,
    summary_path: pathlib.Path,
    *,
    cookie_path: pathlib.Path,
    print_output: bool = False,
    whisper_model: Optional[str] = None,
) -> None:
    video_url = entry["url"]
    logger.info("Processing video: %s", video_url)

    template = str(output_dir / "%(id)s" / "%(id)s.%(language)s.%(ext)s")

    def _operation() -> Tuple[Dict, List[str], str]:
        metadata_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        ensure_cookiefile(metadata_opts, cookie_path)

        with yt_dlp.YoutubeDL(metadata_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

        languages = determine_languages(info)
        logger.debug("Languages selected for %s: %s", video_url, ",".join(languages))

        base_download_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "skip_download": True,
            "noplaylist": True,
            "ignoreerrors": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": {"subtitle": template},
            "overwrites": True,
        }

        ensure_cookiefile(base_download_opts, cookie_path)

        video_id_local = info.get("id")
        if video_id_local:
            target_dir = output_dir / video_id_local
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)

        downloaded_languages: List[str] = []
        subtitle_source = "none"
        for lang in languages:
            lang_opts = dict(base_download_opts)
            lang_opts["subtitleslangs"] = [lang]
            try:
                with yt_dlp.YoutubeDL(lang_opts) as ydl:
                    ydl.download([video_url])
                downloaded_languages.append(lang)
                if lang in info.get("subtitles", {}):
                    logger.debug("Downloaded subtitle (%s) for %s", lang, video_url)
                    subtitle_source = "manual"
                else:
                    logger.debug("Downloaded auto-caption (%s) for %s", lang, video_url)
                    if subtitle_source != "manual":
                        subtitle_source = "auto-caption"
            except Exception as exc:  # pragma: no cover - network resilience
                logger.warning(
                    "Unable to download subtitles for %s (%s): %s", lang, video_url, exc
                )
                time.sleep(1.5)
                continue
            time.sleep(0.5)

        if not downloaded_languages:
            logger.warning("No subtitles were downloaded for %s", video_url)

        return info, downloaded_languages, subtitle_source

    info, requested_languages, subtitle_source = retry(_operation)

    video_id = info.get("id") or entry.get("id") or "unknown"
    video_dir = output_dir / video_id
    if not video_dir.exists():
        logger.warning("Expected download directory %s missing; creating manually", video_dir)
        video_dir.mkdir(parents=True, exist_ok=True)

    # Whisper fallback: if no VTT files were downloaded, try transcription
    if not list(video_dir.glob("*.vtt")) and whisper_model:
        if _whisper_available:
            logger.info("No subtitles found; attempting Whisper transcription for %s", video_url)
            audio_path = download_audio(
                video_url, video_dir, video_id, cookie_path=cookie_path
            )
            if audio_path:
                try:
                    text, detected_lang = whisper_transcribe.transcribe(
                        audio_path, whisper_model
                    )
                    if text:
                        whisper_file = video_dir / f"{video_id}.whisper-{detected_lang}.txt"
                        whisper_file.write_text(text + "\n", encoding="utf-8")
                        subtitle_source = "whisper"
                        logger.info(
                            "Whisper transcription saved (%s) for %s",
                            detected_lang,
                            video_url,
                        )
                    else:
                        logger.warning("Whisper returned empty transcription for %s", video_url)
                except Exception as exc:
                    logger.warning("Whisper transcription failed for %s: %s", video_url, exc)
        else:
            logger.warning(
                "Whisper not installed; skipping transcription fallback for %s. "
                "Install with: pip install openai-whisper",
                video_url,
            )

    # Handle print-to-stdout mode
    if print_output:
        subtitle_sections, _ = gather_subtitle_sections(video_dir, video_url)
        if subtitle_sections:
            lines = compose_subtitle_lines(info, subtitle_sections, video_url)
            print("\n".join(lines).rstrip())

        cleanup_intermediate_dir(video_dir)
        return

    # Normal file-saving mode
    final_dir = output_dir / "final"
    subtitle_path, languages = build_subtitle(info, video_dir, final_dir, video_url)

    if subtitle_path:
        language_list = languages or requested_languages or sorted(
            {path.stem.split(".")[-1] for path in video_dir.glob("*.vtt")}
        )
        duration = info.get("duration")
        write_summary_row(
            summary_path,
            [
                video_id,
                info.get("title") or entry.get("title") or "",
                info.get("webpage_url") or video_url,
                format_upload_date(info.get("upload_date")),
                str(int(duration)) if duration else "",
                str(subtitle_path.relative_to(output_dir)),
                ",".join(language_list),
                subtitle_source,
            ],
        )
    else:
        logger.warning("Skipping summary entry for %s due to missing subtitle", video_url)

    cleanup_intermediate_dir(video_dir)


def get_channel_from_video(video_url: str, *, cookie_path: pathlib.Path) -> Optional[str]:
    """Extract channel name from a video URL."""
    try:
        metadata_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        ensure_cookiefile(metadata_opts, cookie_path)

        with yt_dlp.YoutubeDL(metadata_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            channel = info.get("channel") or info.get("uploader")
            if channel:
                return channel
    except Exception as exc:
        logger.warning("Failed to extract channel from video %s: %s", video_url, exc)

    return None


def get_existing_video_ids(summary_path: pathlib.Path) -> set:
    """Read existing CSV and return set of video IDs already processed."""
    if not summary_path.exists():
        return set()

    existing_ids = set()
    try:
        with summary_path.open("r", encoding="utf-8", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                video_id = row.get("video_id")
                if video_id:
                    existing_ids.add(video_id)
        logger.debug("Found %s existing video IDs in summary", len(existing_ids))
    except Exception as exc:
        logger.warning("Failed to read existing summary %s: %s", summary_path, exc)

    return existing_ids


def filter_new_videos(entries: List[Dict], existing_ids: set) -> List[Dict]:
    """Return only videos not in existing_ids."""
    if not existing_ids:
        return entries

    new_entries = [e for e in entries if e.get("id") not in existing_ids]
    skipped = len(entries) - len(new_entries)
    if skipped > 0:
        logger.info("Skipping %s already processed videos", skipped)
    return new_entries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download YouTube subtitles from a channel or single video.",
        epilog="Examples:\n"
               "  %(prog)s -c DanKoeTalks --limit 10\n"
               "  %(prog)s -v https://youtube.com/watch?v=abc123\n"
               "  %(prog)s -c ChannelName --full",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c", "--channel",
        dest="channel_name",
        help="Channel handle (with or without leading @).",
    )
    parser.add_argument(
        "-v", "--video",
        dest="video_url",
        help="Download subtitles from a single video URL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N videos from channel (default: 0 = no limit).",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("CHANNEL_DL_LOG_LEVEL", "INFO"),
        help="Logging level (default: INFO).",
    )
    parser.add_argument(
        "--output-dir",
        help="Destination directory for subtitles (defaults to downloads/from-channel-<channel>).",
    )
    parser.add_argument(
        "--cookie-file",
        help="Path to cookies.txt file (default: ./cookies.txt).",
    )
    parser.add_argument(
        "--urls-file",
        help="Path for the intermediate playlist file (defaults to <channel>-list.txt).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force full re-download of all videos, ignoring existing subtitles.",
    )
    parser.add_argument(
        "-p", "--print",
        dest="print_output",
        action="store_true",
        help="Print subtitle to stdout instead of saving to file (single video mode only).",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size for transcription fallback (default: base).",
    )
    parser.add_argument(
        "--no-whisper",
        action="store_true",
        help="Disable Whisper transcription fallback entirely.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    # Validate that -p/--print is only used with -v/--video
    if args.print_output and not args.video_url:
        logger.error("The -p/--print flag can only be used with -v/--video (single video mode).")
        return

    cookie_path = pathlib.Path(args.cookie_file) if args.cookie_file else pathlib.Path(
        "cookies.txt"
    )

    whisper_model = None if args.no_whisper else args.whisper_model

    # Single video mode
    if args.video_url:
        logger.info("Single video mode: %s", args.video_url)

        # Extract or use provided channel name
        if args.channel_name:
            try:
                channel_slug = normalize_channel_name(args.channel_name)
            except ValueError as exc:
                logger.error("%s", exc)
                return
        else:
            # Try to extract channel from video metadata
            logger.info("Extracting channel name from video metadata...")
            channel_name = get_channel_from_video(args.video_url, cookie_path=cookie_path)
            if not channel_name:
                logger.error("Could not determine channel name. Please provide -c/--channel.")
                return
            channel_slug = sanitize_filename(channel_name)
            logger.info("Detected channel: %s", channel_slug)

        output_dir = pathlib.Path(args.output_dir) if args.output_dir else pathlib.Path(
            f"downloads/from-channel-{channel_slug}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        summary_path = output_dir / "subtitles_summary.csv"

        # Create a minimal entry dict for the single video
        entry = {"url": args.video_url, "id": None, "title": None}

        try:
            process_single_video(
                entry,
                output_dir,
                summary_path,
                cookie_path=cookie_path,
                print_output=args.print_output,
                whisper_model=whisper_model,
            )
            if not args.print_output:
                logger.info("Single video processing completed. Subtitle located in %s", output_dir / "final")
        except Exception as exc:
            logger.error("Failed to process video %s: %s", args.video_url, exc)

        return

    # Channel mode
    if not args.channel_name:
        logger.error("Either -c/--channel or -v/--video must be provided.")
        return

    try:
        channel_slug = normalize_channel_name(args.channel_name)
    except ValueError as exc:
        logger.error("%s", exc)
        return
    channel_url = f"https://www.youtube.com/@{channel_slug}/videos"

    output_dir = pathlib.Path(args.output_dir) if args.output_dir else pathlib.Path(
        f"from-channel-{channel_slug}"
    )

    if args.urls_file:
        urls_file = pathlib.Path(args.urls_file)
        if not urls_file.is_absolute():
            urls_file = output_dir / urls_file
    else:
        urls_file = output_dir / f"{channel_slug}-list.txt"

    output_dir.mkdir(parents=True, exist_ok=True)
    urls_file.parent.mkdir(parents=True, exist_ok=True)

    summary_path = output_dir / "subtitles_summary.csv"

    logger.info(
        "Starting YouTube channel subtitle downloader for @%s", channel_slug
    )
    logger.info("Fetching channel entries from %s", channel_url)
    entries = get_channel_video_entries(channel_url, cookie_path=cookie_path)
    if not entries:
        logger.error("No entries retrieved; exiting.")
        return

    # Incremental mode: filter out already processed videos
    if not args.full:
        existing_ids = get_existing_video_ids(summary_path)
        if existing_ids:
            logger.info("Incremental mode: filtering already processed videos")
            entries = filter_new_videos(entries, existing_ids)
            if not entries:
                logger.info("No new videos to process.")
                return
    else:
        logger.info("Full mode: processing all videos")
        if summary_path.exists():
            summary_path.unlink()
            logger.info("Existing summary file deleted")

    limit = args.limit if args.limit and args.limit > 0 else None
    if limit:
        entries = entries[:limit]
        logger.info("Limiting processing to the first %s videos", limit)

    with open(urls_file, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(f"{entry['url']}\n")
    logger.info("Saved %s video URLs to %s", len(entries), urls_file)

    for idx, entry in enumerate(entries, start=1):
        logger.info("[%s/%s] %s", idx, len(entries), entry.get("title") or entry["url"])
        try:
            process_single_video(
                entry,
                output_dir,
                summary_path,
                cookie_path=cookie_path,
                whisper_model=whisper_model,
            )
        except Exception as exc:
            logger.error("Failed to process %s: %s", entry["url"], exc)

    logger.info("All tasks completed. Subtitles located in %s", output_dir / "final")


if __name__ == "__main__":
    main()
