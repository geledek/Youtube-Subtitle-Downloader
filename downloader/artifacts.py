import datetime as _dt
import pathlib
import zipfile
from typing import List, Optional

from .core import VideoDownloadResult, sanitize_filename


def _timestamp() -> str:
    return _dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _unique_path(directory: pathlib.Path, filename: str) -> pathlib.Path:
    candidate = directory / filename
    counter = 1
    while candidate.exists():
        stem = pathlib.Path(filename).stem
        suffix = pathlib.Path(filename).suffix
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def create_markdown_file(
    result: VideoDownloadResult, artifact_dir: pathlib.Path
) -> Optional[pathlib.Path]:
    if not result.subtitle_path or not result.subtitle_path.exists():
        return None

    artifact_dir.mkdir(parents=True, exist_ok=True)
    subtitle_text = result.subtitle_path.read_text(encoding="utf-8", errors="ignore").strip()
    filename = pathlib.Path(result.subtitle_path.name).with_suffix(".md").name
    filename = sanitize_filename(filename) or f"subtitle-{result.video_id}.md"
    md_path = _unique_path(artifact_dir, filename)

    languages = ", ".join(result.languages) if result.languages else "unknown"
    lines = [
        f"# {result.title or 'Unknown Title'}",
        "",
        f"- **URL**: {result.url}",
        f"- **Upload Date**: {result.upload_date}",
    ]
    if result.channel:
        lines.append(f"- **Channel**: {result.channel}")
    lines.append(f"- **Languages**: {languages}")
    lines.extend(
        [
            "",
            "## Subtitle",
            "",
            "```text",
            subtitle_text,
            "```",
            "",
        ]
    )

    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return md_path


def build_markdown_artifacts(
    results: List[VideoDownloadResult], artifact_dir: pathlib.Path
) -> List[pathlib.Path]:
    markdown_files: List[pathlib.Path] = []
    for result in results:
        md_path = create_markdown_file(result, artifact_dir)
        if md_path:
            markdown_files.append(md_path)
    return markdown_files


def zip_markdown(markdown_files: List[pathlib.Path], artifact_dir: pathlib.Path) -> pathlib.Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"subtitles-{_timestamp()}.zip"
    zip_path = _unique_path(artifact_dir, zip_name)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in markdown_files:
            archive.write(path, arcname=path.name)
    return zip_path


def create_summary_markdown(
    results: List[VideoDownloadResult], artifact_dir: pathlib.Path
) -> pathlib.Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    name = f"download-summary-{_timestamp()}.md"
    summary_path = _unique_path(artifact_dir, name)
    lines = [
        "# Download Summary",
        "",
        f"Generated: {_dt.datetime.utcnow().isoformat()}Z",
        "",
    ]
    if not results:
        lines.append("No videos were processed.")
    else:
        lines.append("## Videos")
        lines.append("")
        for result in results:
            title = result.title or result.video_id
            lines.append(
                f"- **{title}** — status: `{result.status}` — [Link]({result.url})"
            )
            if result.message:
                lines.append(f"  - {result.message}")
    summary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summary_path
