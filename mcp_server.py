#!/usr/bin/env python3
"""MCP Server for YouTube Subtitle Downloader.

This exposes the subtitle downloader as tools for Claude Desktop.

Usage:
    python mcp_server.py
"""

import json
import logging
import pathlib
import sys

# Ensure repo root is in path
REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from downloader import (
    download_single_video,
    download_channel,
    check_version,
    ensure_ytdlp_current,
    DownloadError,
)

# Configure logging to stderr (stdout is for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp-youtube-subtitles")

server = Server("youtube-subtitles")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="download_video_subtitle",
            description="Download subtitles from a single YouTube video and return the transcript text.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_url": {
                        "type": "string",
                        "description": "YouTube video URL (e.g., https://www.youtube.com/watch?v=abc123)",
                    },
                    "channel_name": {
                        "type": "string",
                        "description": "Optional channel name for organizing output files",
                    },
                },
                "required": ["video_url"],
            },
        ),
        Tool(
            name="download_channel_subtitles",
            description="Download subtitles from multiple videos on a YouTube channel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_name": {
                        "type": "string",
                        "description": "YouTube channel handle (with or without @, e.g., 'DanKoeTalks' or '@DanKoeTalks')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of videos to process (default: 10)",
                        "default": 10,
                    },
                    "full": {
                        "type": "boolean",
                        "description": "Force full re-download ignoring previously processed videos",
                        "default": False,
                    },
                },
                "required": ["channel_name"],
            },
        ),
        Tool(
            name="check_ytdlp_version",
            description="Check the installed yt-dlp version and whether it needs updating.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="update_ytdlp",
            description="Update yt-dlp to the latest version.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "download_video_subtitle":
            return await _download_video(arguments)
        elif name == "download_channel_subtitles":
            return await _download_channel(arguments)
        elif name == "check_ytdlp_version":
            return await _check_version()
        elif name == "update_ytdlp":
            return await _update_ytdlp()
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.exception("Tool execution failed")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _download_video(arguments: dict) -> list[TextContent]:
    """Download subtitle from a single video."""
    video_url = arguments.get("video_url")
    if not video_url:
        return [TextContent(type="text", text="Error: video_url is required")]

    channel_name = arguments.get("channel_name")
    cookie_file = REPO_ROOT / "cookies.txt"

    try:
        result = download_single_video(
            video_url,
            channel_name=channel_name,
            cookie_file=str(cookie_file) if cookie_file.exists() else None,
            auto_update_ytdlp=True,
        )

        if result.subtitle_path and result.subtitle_path.exists():
            subtitle_text = result.subtitle_path.read_text(encoding="utf-8")
            response = {
                "status": "success",
                "video_id": result.video_id,
                "title": result.title,
                "url": result.url,
                "upload_date": result.upload_date,
                "channel": result.channel,
                "languages": result.languages,
                "subtitle_path": str(result.subtitle_path),
                "transcript": subtitle_text,
            }
        else:
            response = {
                "status": result.status,
                "video_id": result.video_id,
                "title": result.title,
                "message": result.message or "No subtitles available",
            }

        return [TextContent(type="text", text=json.dumps(response, indent=2, ensure_ascii=False))]

    except DownloadError as e:
        return [TextContent(type="text", text=f"Download error: {str(e)}")]


async def _download_channel(arguments: dict) -> list[TextContent]:
    """Download subtitles from a channel."""
    channel_name = arguments.get("channel_name")
    if not channel_name:
        return [TextContent(type="text", text="Error: channel_name is required")]

    limit = arguments.get("limit", 10)
    full = arguments.get("full", False)
    cookie_file = REPO_ROOT / "cookies.txt"

    try:
        batch = download_channel(
            channel_name,
            cookie_file=str(cookie_file) if cookie_file.exists() else None,
            limit=limit,
            full=full,
            auto_update_ytdlp=True,
        )

        # Build summary
        successful = [r for r in batch.results if r.status == "success"]
        failed = [r for r in batch.results if r.status != "success"]

        response = {
            "status": "success",
            "channel": batch.channel_slug,
            "output_dir": str(batch.output_dir),
            "total_processed": len(batch.results),
            "successful": len(successful),
            "failed": len(failed),
            "videos": [],
        }

        for result in batch.results:
            video_info = {
                "video_id": result.video_id,
                "title": result.title,
                "url": result.url,
                "status": result.status,
            }
            if result.subtitle_path:
                video_info["subtitle_path"] = str(result.subtitle_path)
            if result.message:
                video_info["message"] = result.message
            response["videos"].append(video_info)

        return [TextContent(type="text", text=json.dumps(response, indent=2, ensure_ascii=False))]

    except DownloadError as e:
        return [TextContent(type="text", text=f"Download error: {str(e)}")]


async def _check_version() -> list[TextContent]:
    """Check yt-dlp version."""
    info = check_version()
    response = {
        "version": info.version,
        "outdated": info.is_outdated,
        "age_days": info.age_days,
        "needs_update": info.needs_update,
        "message": info.message,
    }
    return [TextContent(type="text", text=json.dumps(response, indent=2))]


async def _update_ytdlp() -> list[TextContent]:
    """Update yt-dlp."""
    from downloader.version import update_ytdlp

    success, message = update_ytdlp()
    response = {
        "success": success,
        "message": message,
    }
    if success:
        new_info = check_version()
        response["new_version"] = new_info.version
    return [TextContent(type="text", text=json.dumps(response, indent=2))]


async def main():
    """Run the MCP server."""
    logger.info("Starting YouTube Subtitles MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
