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
                    "transcript_path",
                    "languages",
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
    # Preserve insertion order while removing duplicates, but keep only the highest priority language.
    unique = list(dict.fromkeys(ordered))
    return unique[:1]


def build_transcript(
    info: Dict,
    video_dir: pathlib.Path,
    final_dir: pathlib.Path,
    video_url: str,
) -> Tuple[Optional[pathlib.Path], List[str]]:
    vtt_files = sorted(video_dir.glob("*.vtt"))
    if not vtt_files:
        logger.warning("No subtitle files were downloaded for %s", video_url)
        return None, []

    language_to_path: Dict[str, pathlib.Path] = {}
    for vtt_file in vtt_files:
        parts = vtt_file.stem.split(".")
        lang = parts[-1] if len(parts) > 1 else "unknown"
        language_to_path[lang] = vtt_file

    transcript_sections = []
    used_languages: List[str] = []
    for lang in collect_language_order(language_to_path.keys()):
        vtt_path = language_to_path[lang]
        try:
            vtt_to_txt(vtt_path)
        except Exception as exc:
            logger.warning("Failed to convert %s: %s", vtt_path, exc)
            continue
        txt_path = vtt_path.with_suffix(".txt")
        if not txt_path.exists():
            logger.warning("Missing converted text for %s", vtt_path)
            continue
        text_content = txt_path.read_text(encoding="utf-8").strip()
        if not text_content:
            logger.debug("Skipping empty transcript for %s", txt_path)
            continue
        transcript_sections.append((lang, text_content))
        used_languages.append(lang)

    if not transcript_sections:
        logger.warning("All transcripts empty or unavailable for %s", video_url)
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

    header = [
        f"Title: {info.get('title') or 'Unknown'}",
        f"URL: {info.get('webpage_url') or video_url}",
        f"Upload Date: {format_upload_date(info.get('upload_date'))}",
    ]
    if info.get("channel"):
        header.append(f"Channel: {info['channel']}")

    lines = header + [""]
    for lang, text_content in transcript_sections:
        lines.append(f"--- Transcript ({lang}) ---")
        lines.append(text_content)
        lines.append("")

    final_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    logger.info("Transcript saved to %s", final_path)
    unique_languages = list(dict.fromkeys(used_languages))
    return final_path, unique_languages


def process_single_video(
    entry: Dict,
    output_dir: pathlib.Path,
    summary_path: pathlib.Path,
    *,
    cookie_path: pathlib.Path,
) -> None:
    video_url = entry["url"]
    logger.info("Processing video: %s", video_url)

    template = str(output_dir / "%(id)s" / "%(id)s.%(language)s.%(ext)s")

    def _operation() -> Tuple[Dict, List[str]]:
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
            "outtmpl": {
                "default": template,
                "subtitle": template,
            },
            "overwrites": True,
        }

        video_id_local = info.get("id")
        if video_id_local:
            target_dir = output_dir / video_id_local
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)

        downloaded_languages: List[str] = []
        for lang in languages:
            lang_opts = dict(base_download_opts)
            lang_opts["subtitleslangs"] = [lang]
            ensure_cookiefile(lang_opts, cookie_path)
            try:
                with yt_dlp.YoutubeDL(lang_opts) as ydl:
                    ydl.download([video_url])
                downloaded_languages.append(lang)
                if lang in info.get("subtitles", {}):
                    logger.debug("Downloaded subtitle (%s) for %s", lang, video_url)
                else:
                    logger.debug("Downloaded auto-caption (%s) for %s", lang, video_url)
            except Exception as exc:  # pragma: no cover - network resilience
                logger.warning(
                    "Unable to download subtitles for %s (%s): %s", lang, video_url, exc
                )
                time.sleep(1.5)
                continue
            time.sleep(0.5)

        if not downloaded_languages:
            logger.warning("No subtitles were downloaded for %s", video_url)

        return info, downloaded_languages

    info, requested_languages = retry(_operation)

    video_id = info.get("id") or entry.get("id") or "unknown"
    video_dir = output_dir / video_id
    if not video_dir.exists():
        logger.warning("Expected download directory %s missing; creating manually", video_dir)
        video_dir.mkdir(parents=True, exist_ok=True)

    final_dir = output_dir / "final"
    transcript_path, languages = build_transcript(info, video_dir, final_dir, video_url)

    if transcript_path:
        language_list = languages or requested_languages or sorted(
            {path.stem.split(".")[-1] for path in video_dir.glob("*.vtt")}
        )
        write_summary_row(
            summary_path,
            [
                video_id,
                info.get("title") or entry.get("title") or "",
                info.get("webpage_url") or video_url,
                format_upload_date(info.get("upload_date")),
                str(transcript_path.relative_to(output_dir)),
                ",".join(language_list),
            ],
        )
    else:
        logger.warning("Skipping summary entry for %s due to missing transcript", video_url)

    cleanup_intermediate_dir(video_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download YouTube subtitles and build transcripts from a channel."
    )
    parser.add_argument(
        "channel_name",
        help="Channel handle (with or without leading @).",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("CHANNEL_DL_LOG_LEVEL", "INFO"),
        help="Logging level (default: INFO).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N videos (0 means no limit).",
    )
    parser.add_argument(
        "--output-dir",
        help="Optional destination directory for transcripts (defaults to all-transcript-from-<channel>).",
    )
    parser.add_argument(
        "--cookie-file",
        help="Optional cookies file path (defaults to ./cookies.txt).",
    )
    parser.add_argument(
        "--urls-file",
        help="Optional path for the intermediate playlist file (defaults to <channel>-list.txt inside the output dir).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    try:
        channel_slug = normalize_channel_name(args.channel_name)
    except ValueError as exc:
        logger.error("%s", exc)
        return
    channel_url = f"https://www.youtube.com/@{channel_slug}/videos"

    output_dir = pathlib.Path(args.output_dir) if args.output_dir else pathlib.Path(
        f"all-transcript-from-{channel_slug}"
    )
    cookie_path = pathlib.Path(args.cookie_file) if args.cookie_file else pathlib.Path(
        "cookies.txt"
    )

    if args.urls_file:
        urls_file = pathlib.Path(args.urls_file)
        if not urls_file.is_absolute():
            urls_file = output_dir / urls_file
    else:
        urls_file = output_dir / f"{channel_slug}-list.txt"

    output_dir.mkdir(parents=True, exist_ok=True)
    urls_file.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting YouTube channel subtitle downloader for @%s", channel_slug
    )
    logger.info("Fetching channel entries from %s", channel_url)
    entries = get_channel_video_entries(channel_url, cookie_path=cookie_path)
    if not entries:
        logger.error("No entries retrieved; exiting.")
        return

    limit = args.limit if args.limit and args.limit > 0 else None
    if limit:
        entries = entries[:limit]
        logger.info("Limiting processing to the first %s videos", limit)

    with open(urls_file, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(f"{entry['url']}\n")
    logger.info("Saved %s video URLs to %s", len(entries), urls_file)

    summary_path = output_dir / "transcripts_summary.csv"
    if summary_path.exists():
        summary_path.unlink()

    for idx, entry in enumerate(entries, start=1):
        logger.info("[%s/%s] %s", idx, len(entries), entry.get("title") or entry["url"])
        try:
            process_single_video(
                entry,
                output_dir,
                summary_path,
                cookie_path=cookie_path,
            )
        except Exception as exc:
            logger.error("Failed to process %s: %s", entry["url"], exc)

    logger.info("All tasks completed. Transcripts located in %s", output_dir / "final")


if __name__ == "__main__":
    main()
