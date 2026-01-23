import csv
import logging
import pathlib
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import yt_dlp

from vtt2txt import process as vtt_to_txt

from .version import ensure_ytdlp_current

logger = logging.getLogger("channel_downloader")

PathLike = Union[str, pathlib.Path]


class DownloadError(RuntimeError):
    """Raised when the downloader cannot complete a requested task."""


def _resolve_path(value: Optional[PathLike], *, default: Optional[str] = None) -> pathlib.Path:
    if value is None:
        if default is None:
            raise ValueError("A default path must be provided when value is None.")
        path = pathlib.Path(default)
    else:
        path = pathlib.Path(value)
    return path.expanduser()


@dataclass
class VideoDownloadResult:
    video_id: str
    title: str
    url: str
    upload_date: str
    channel: Optional[str]
    subtitle_path: Optional[pathlib.Path]
    languages: List[str] = field(default_factory=list)
    status: str = "success"
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "url": self.url,
            "upload_date": self.upload_date,
            "channel": self.channel,
            "subtitle_path": str(self.subtitle_path) if self.subtitle_path else None,
            "languages": self.languages,
            "status": self.status,
            "message": self.message,
        }


@dataclass
class BatchDownloadResult:
    channel_slug: str
    output_dir: pathlib.Path
    urls_file: pathlib.Path
    results: List[VideoDownloadResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_slug": self.channel_slug,
            "output_dir": str(self.output_dir),
            "urls_file": str(self.urls_file),
            "results": [result.to_dict() for result in self.results],
        }

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


def _failure_result(entry: Dict, exc: Exception) -> VideoDownloadResult:
    return VideoDownloadResult(
        video_id=entry.get("id") or "unknown",
        title=entry.get("title") or "",
        url=entry.get("url", ""),
        upload_date="Unknown",
        channel=None,
        subtitle_path=None,
        languages=[],
        status="error",
        message=str(exc),
    )


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
                    "subtitle_path",
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
    return ordered[:1]


def gather_subtitle_sections(
    video_dir: pathlib.Path, video_url: str
) -> Tuple[List[Tuple[str, str]], List[str]]:
    vtt_files = sorted(video_dir.glob("*.vtt"))
    if not vtt_files:
        logger.warning("No subtitle files were downloaded for %s", video_url)
        return [], []

    language_to_path: Dict[str, pathlib.Path] = {}
    for vtt_file in vtt_files:
        parts = vtt_file.stem.split(".")
        lang = parts[-1] if len(parts) > 1 else "unknown"
        language_to_path[lang] = vtt_file

    subtitle_sections: List[Tuple[str, str]] = []
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
            logger.debug("Skipping empty subtitle for %s", txt_path)
            continue
        subtitle_sections.append((lang, text_content))
        used_languages.append(lang)

    if not subtitle_sections:
        logger.warning("All subtitles empty or unavailable for %s", video_url)
        return [], []

    unique_languages = list(dict.fromkeys(used_languages))
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
    *,
    cookie_path: pathlib.Path,
    summary_path: Optional[pathlib.Path] = None,
    print_output: bool = False,
    write_summary: bool = True,
) -> VideoDownloadResult:
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
        for lang in languages:
            lang_opts = dict(base_download_opts)
            lang_opts["subtitleslangs"] = [lang]
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

    resolved_url = info.get("webpage_url") or video_url
    title = info.get("title") or entry.get("title") or ""
    channel_name = info.get("channel") or info.get("uploader")
    upload_date = format_upload_date(info.get("upload_date"))

    # Handle print-to-stdout mode
    if print_output:
        subtitle_sections, languages = gather_subtitle_sections(video_dir, video_url)
        if subtitle_sections:
            lines = compose_subtitle_lines(info, subtitle_sections, video_url)
            print("\n".join(lines).rstrip())
        cleanup_intermediate_dir(video_dir)
        return VideoDownloadResult(
            video_id=video_id,
            title=title,
            url=resolved_url,
            upload_date=upload_date,
            channel=channel_name,
            subtitle_path=None,
            languages=languages or requested_languages,
            status="printed",
            message="Subtitle printed to stdout.",
        )

    # Normal file-saving mode
    final_dir = output_dir / "final"
    subtitle_path, languages = build_subtitle(info, video_dir, final_dir, video_url)
    language_list = languages or requested_languages or sorted(
        {path.stem.split(".")[-1] for path in video_dir.glob("*.vtt")}
    )

    status = "success"
    message = None
    if subtitle_path and summary_path and write_summary:
        try:
            relative_path = str(subtitle_path.relative_to(output_dir))
        except ValueError:
            relative_path = str(subtitle_path)
        write_summary_row(
            summary_path,
            [
                video_id,
                title,
                resolved_url,
                upload_date,
                relative_path,
                ",".join(language_list),
            ],
        )
    elif not subtitle_path:
        status = "missing_subtitle"
        message = "Subtitle file was not created."
        logger.warning("Skipping summary entry for %s due to missing subtitle", video_url)

    cleanup_intermediate_dir(video_dir)

    return VideoDownloadResult(
        video_id=video_id,
        title=title,
        url=resolved_url,
        upload_date=upload_date,
        channel=channel_name,
        subtitle_path=subtitle_path,
        languages=language_list,
        status=status,
        message=message,
    )


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


def download_single_video(
    video_url: str,
    *,
    channel_name: Optional[str] = None,
    output_dir: Optional[PathLike] = None,
    cookie_file: Optional[PathLike] = None,
    print_output: bool = False,
    write_summary: bool = True,
    auto_update_ytdlp: bool = True,
) -> VideoDownloadResult:
    # Check yt-dlp version and auto-update if needed
    version_info = ensure_ytdlp_current(auto_update=auto_update_ytdlp)
    if version_info.needs_update and version_info.message:
        logger.warning("yt-dlp version issue: %s", version_info.message)

    cookie_path = _resolve_path(cookie_file, default="cookies.txt")

    if channel_name:
        try:
            channel_slug = normalize_channel_name(channel_name)
        except ValueError as exc:
            raise DownloadError(str(exc)) from exc
    else:
        logger.info("Extracting channel name from video metadata...")
        channel_from_video = get_channel_from_video(video_url, cookie_path=cookie_path)
        if not channel_from_video:
            raise DownloadError(
                "Could not determine channel name from video metadata. Provide channel_name."
            )
        channel_slug = sanitize_filename(channel_from_video)
        logger.info("Detected channel: %s", channel_slug)

    resolved_output_dir = _resolve_path(output_dir, default=f"from-channel-{channel_slug}")
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_output_dir = resolved_output_dir.resolve()

    summary_path = None
    if write_summary and not print_output:
        summary_path = resolved_output_dir / "subtitles_summary.csv"

    entry = {"url": video_url, "id": None, "title": None}

    try:
        return process_single_video(
            entry,
            resolved_output_dir,
            cookie_path=cookie_path,
            summary_path=summary_path,
            print_output=print_output,
            write_summary=write_summary and not print_output,
        )
    except Exception as exc:  # pragma: no cover - passthrough for CLI/skill handling
        raise DownloadError(f"Failed to process video {video_url}: {exc}") from exc


def download_channel(
    channel_name: str,
    *,
    output_dir: Optional[PathLike] = None,
    cookie_file: Optional[PathLike] = None,
    urls_file: Optional[PathLike] = None,
    limit: Optional[int] = None,
    full: bool = False,
    incremental: bool = True,
    auto_update_ytdlp: bool = True,
) -> BatchDownloadResult:
    # Check yt-dlp version and auto-update if needed
    version_info = ensure_ytdlp_current(auto_update=auto_update_ytdlp)
    if version_info.needs_update and version_info.message:
        logger.warning("yt-dlp version issue: %s", version_info.message)

    try:
        channel_slug = normalize_channel_name(channel_name)
    except ValueError as exc:
        raise DownloadError(str(exc)) from exc

    cookie_path = _resolve_path(cookie_file, default="cookies.txt")
    resolved_output_dir = _resolve_path(output_dir, default=f"from-channel-{channel_slug}")
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_output_dir = resolved_output_dir.resolve()

    if urls_file:
        urls_path = pathlib.Path(urls_file).expanduser()
        if not urls_path.is_absolute():
            urls_path = resolved_output_dir / urls_path
    else:
        urls_path = resolved_output_dir / f"{channel_slug}-list.txt"
    urls_path.parent.mkdir(parents=True, exist_ok=True)

    summary_path = resolved_output_dir / "subtitles_summary.csv"
    channel_url = f"https://www.youtube.com/@{channel_slug}/videos"
    logger.info("Fetching channel entries from %s", channel_url)
    entries = get_channel_video_entries(channel_url, cookie_path=cookie_path)
    if not entries:
        raise DownloadError("No entries retrieved from the channel.")

    if limit and limit > 0:
        logger.info("Limiting processing to the first %s videos", limit)
        entries = entries[:limit]

    if full:
        logger.info("Full mode: processing all videos")
        if summary_path.exists():
            summary_path.unlink()
            logger.info("Existing summary file deleted")
    elif incremental:
        existing_ids = get_existing_video_ids(summary_path)
        if existing_ids:
            logger.info("Incremental mode: filtering already processed videos")
            entries = filter_new_videos(entries, existing_ids)
            if not entries:
                logger.info("No new videos to process.")

    if not entries:
        return BatchDownloadResult(
            channel_slug=channel_slug,
            output_dir=resolved_output_dir,
            urls_file=urls_path,
            results=[],
        )

    with open(urls_path, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(f"{entry['url']}\n")
    logger.info("Saved %s video URLs to %s", len(entries), urls_path)

    results: List[VideoDownloadResult] = []
    for idx, entry in enumerate(entries, start=1):
        logger.info("[%s/%s] %s", idx, len(entries), entry.get("title") or entry["url"])
        try:
            result = process_single_video(
                entry,
                resolved_output_dir,
                cookie_path=cookie_path,
                summary_path=summary_path,
                print_output=False,
                write_summary=True,
            )
        except Exception as exc:  # pragma: no cover - runtime resilience
            logger.error("Failed to process %s: %s", entry["url"], exc)
            result = _failure_result(entry, exc)
        results.append(result)

    return BatchDownloadResult(
        channel_slug=channel_slug,
        output_dir=resolved_output_dir,
        urls_file=urls_path,
        results=results,
    )
