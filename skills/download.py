#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import sys
from typing import Any, Dict, List, Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from downloader.artifacts import (
    build_markdown_artifacts,
    create_summary_markdown,
    zip_markdown,
)
from downloader.core import (
    BatchDownloadResult,
    DownloadError,
    VideoDownloadResult,
    configure_logging,
    download_channel,
    download_single_video,
)
from downloader.version import check_version, ensure_ytdlp_current


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Skill runner that produces Markdown artifacts for subtitle downloads.",
    )
    parser.add_argument(
        "--input",
        default="-",
        help="Path to JSON input. Defaults to stdin when '-' is provided.",
    )
    parser.add_argument(
        "--artifact-dir",
        default="skill-artifacts",
        help="Directory where Markdown/zip artifacts should be written.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("CHANNEL_DL_LOG_LEVEL", "INFO"),
        help="Log level override (default: INFO).",
    )
    return parser.parse_args()


def _load_request(path: str) -> Dict[str, Any]:
    if not path or path == "-":
        payload = sys.stdin.read()
    else:
        payload = pathlib.Path(path).read_text(encoding="utf-8")
    if not payload.strip():
        raise ValueError("Input payload is empty.")
    return json.loads(payload)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected integer value, received {value!r}") from exc
    return parsed


def _channel_name(payload: Dict[str, Any]) -> Optional[str]:
    return payload.get("channel") or payload.get("channel_name")


def _video_url(payload: Dict[str, Any]) -> Optional[str]:
    return payload.get("video_url") or payload.get("video")


def _artifact_directory(request: Dict[str, Any], default_dir: str) -> pathlib.Path:
    override = request.get("artifact_dir") or default_dir
    return pathlib.Path(override).expanduser()


def _results_to_dict(results: List[VideoDownloadResult]) -> List[Dict[str, Any]]:
    return [result.to_dict() for result in results]


def _emit(response: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, indent=2))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _run_video(request: Dict[str, Any]) -> List[VideoDownloadResult]:
    video_url = _video_url(request)
    if not video_url:
        raise DownloadError("Video mode requires a video_url field.")
    return [
        download_single_video(
            video_url,
            channel_name=_channel_name(request),
            output_dir=request.get("output_dir"),
            cookie_file=request.get("cookie_file"),
            print_output=False,
            write_summary=_bool(request.get("write_summary"), True),
            auto_update_ytdlp=_bool(request.get("auto_update_ytdlp"), True),
        )
    ]


def _run_channel(request: Dict[str, Any]) -> BatchDownloadResult:
    channel = _channel_name(request)
    if not channel:
        raise DownloadError("Channel mode requires a channel field.")
    limit_value = request.get("limit")
    limit = _int(limit_value) if limit_value not in (None, "") else None
    return download_channel(
        channel,
        output_dir=request.get("output_dir"),
        cookie_file=request.get("cookie_file"),
        urls_file=request.get("urls_file"),
        limit=limit,
        full=_bool(request.get("full"), False),
        incremental=_bool(request.get("incremental"), True),
        auto_update_ytdlp=_bool(request.get("auto_update_ytdlp"), True),
    )


def _artifact_payload(markdown_files: List[pathlib.Path], artifact_dir: pathlib.Path) -> Dict[str, Any]:
    artifact_info: Dict[str, Any] = {
        "markdown_files": [str(path) for path in markdown_files],
        "artifact_dir": str(artifact_dir),
    }
    if not markdown_files:
        artifact_info.update({"artifact_type": "none", "artifact_path": None})
    elif len(markdown_files) == 1:
        artifact_info.update({"artifact_type": "markdown", "artifact_path": str(markdown_files[0])})
    else:
        zip_path = zip_markdown(markdown_files, artifact_dir)
        artifact_info.update({"artifact_type": "zip", "artifact_path": str(zip_path), "zip_path": str(zip_path)})
    return artifact_info


def main() -> None:
    args = parse_args()
    try:
        request = _load_request(args.input)
    except (ValueError, json.JSONDecodeError) as exc:
        _emit({"status": "error", "message": str(exc)})
        return

    log_level = request.get("log_level") or args.log_level
    configure_logging(str(log_level))

    artifact_dir = _artifact_directory(request, args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Check and report yt-dlp version
    version_info = check_version()
    ytdlp_status = {
        "ytdlp_version": version_info.version,
        "ytdlp_outdated": version_info.is_outdated,
        "ytdlp_age_days": version_info.age_days,
    }
    if version_info.message:
        ytdlp_status["ytdlp_warning"] = version_info.message

    mode = (request.get("mode") or ("video" if _video_url(request) else "channel")).lower()
    batch: Optional[BatchDownloadResult] = None
    try:
        if mode == "video":
            results = _run_video(request)
        elif mode == "channel":
            batch = _run_channel(request)
            results = batch.results
        else:
            raise DownloadError(f"Unsupported mode: {mode}")
    except (DownloadError, ValueError) as exc:
        _emit({"status": "error", "message": str(exc), **ytdlp_status})
        return

    markdown_files = build_markdown_artifacts(results, artifact_dir)
    if not markdown_files:
        markdown_files = [create_summary_markdown(results, artifact_dir)]

    artifact_info = _artifact_payload(markdown_files, artifact_dir)

    response: Dict[str, Any] = {
        "status": "success",
        "mode": mode,
        "results": _results_to_dict(results),
        **artifact_info,
        **ytdlp_status,
    }
    if batch is not None:
        response.update(
            {
                "channel_slug": batch.channel_slug,
                "output_dir": str(batch.output_dir),
                "urls_file": str(batch.urls_file),
            }
        )
    _emit(response)


if __name__ == "__main__":
    main()
