import argparse
import logging
import os
from typing import Optional

from downloader.core import (
    DownloadError,
    configure_logging,
    download_channel,
    download_single_video,
)

logger = logging.getLogger("channel_downloader")


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
        "-c",
        "--channel",
        dest="channel_name",
        help="Channel handle (with or without leading @).",
    )
    parser.add_argument(
        "-v",
        "--video",
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
        help="Destination directory for subtitles (defaults to from-channel-<channel>).",
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
        "-p",
        "--print",
        dest="print_output",
        action="store_true",
        help="Print subtitle to stdout instead of saving to file (single video mode only).",
    )
    return parser.parse_args()


def _limit_value(limit: int) -> Optional[int]:
    return limit if limit and limit > 0 else None


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    if args.print_output and not args.video_url:
        logger.error("The -p/--print flag can only be used with -v/--video (single video mode).")
        return

    cookie_file = args.cookie_file

    if args.video_url:
        logger.info("Single video mode: %s", args.video_url)
        try:
            result = download_single_video(
                args.video_url,
                channel_name=args.channel_name,
                output_dir=args.output_dir,
                cookie_file=cookie_file,
                print_output=args.print_output,
                write_summary=True,
            )
            if not args.print_output and result.subtitle_path:
                logger.info("Single video processing completed. Subtitle located in %s", result.subtitle_path)
        except DownloadError as exc:
            logger.error("%s", exc)
        return

    if not args.channel_name:
        logger.error("Either -c/--channel or -v/--video must be provided.")
        return

    try:
        batch_result = download_channel(
            args.channel_name,
            output_dir=args.output_dir,
            cookie_file=cookie_file,
            urls_file=args.urls_file,
            limit=_limit_value(args.limit),
            full=args.full,
        )
    except DownloadError as exc:
        logger.error("%s", exc)
        return

    successes = [r for r in batch_result.results if r.status == "success"]
    if successes:
        logger.info("All tasks completed. Subtitles located in %s", batch_result.output_dir / "final")
    else:
        logger.info("Completed without generating subtitles (no new videos or all failed).")


if __name__ == "__main__":
    main()
