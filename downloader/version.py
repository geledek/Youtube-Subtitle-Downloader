"""yt-dlp version management utilities."""

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

logger = logging.getLogger("channel_downloader")

# yt-dlp versions older than this many days trigger a warning
MAX_AGE_DAYS = 30

# Known minimum version that handles YouTube's PO token requirements
MIN_RECOMMENDED_VERSION = "2025.12.01"


@dataclass
class VersionInfo:
    version: str
    is_outdated: bool
    age_days: Optional[int]
    needs_update: bool
    message: Optional[str]


def parse_version_date(version: str) -> Optional[datetime]:
    """Parse yt-dlp version string (YYYY.MM.DD format) to datetime."""
    match = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", version)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def get_ytdlp_version() -> Optional[str]:
    """Get installed yt-dlp version."""
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except (ImportError, AttributeError):
        pass

    # Fallback to CLI
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return None


def check_version() -> VersionInfo:
    """Check yt-dlp version and determine if update is needed."""
    version = get_ytdlp_version()

    if not version:
        return VersionInfo(
            version="unknown",
            is_outdated=True,
            age_days=None,
            needs_update=True,
            message="yt-dlp not found. Install with: pip install yt-dlp",
        )

    version_date = parse_version_date(version)
    now = datetime.now()

    age_days = None
    is_outdated = False

    if version_date:
        age_days = (now - version_date).days
        is_outdated = age_days > MAX_AGE_DAYS

    # Check against minimum recommended version
    min_date = parse_version_date(MIN_RECOMMENDED_VERSION)
    needs_update = False
    message = None

    if version_date and min_date and version_date < min_date:
        needs_update = True
        message = (
            f"yt-dlp {version} is older than recommended minimum {MIN_RECOMMENDED_VERSION}. "
            "YouTube may block subtitle access. Update recommended."
        )
    elif is_outdated:
        needs_update = True
        message = (
            f"yt-dlp {version} is {age_days} days old. "
            "YouTube frequently changes; update recommended."
        )

    return VersionInfo(
        version=version,
        is_outdated=is_outdated,
        age_days=age_days,
        needs_update=needs_update,
        message=message,
    )


def update_ytdlp() -> Tuple[bool, str]:
    """Attempt to update yt-dlp. Returns (success, message)."""
    logger.info("Attempting to update yt-dlp...")

    # Try uv first (faster)
    for cmd in [
        ["uv", "pip", "install", "--upgrade", "yt-dlp"],
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
    ]:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                new_version = get_ytdlp_version()
                return True, f"Updated yt-dlp to {new_version}"
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            continue
        except Exception as e:
            logger.warning("Update attempt failed: %s", e)
            continue

    return False, "Failed to update yt-dlp. Try manually: pip install --upgrade yt-dlp"


def ensure_ytdlp_current(auto_update: bool = True) -> VersionInfo:
    """
    Check yt-dlp version and optionally auto-update if outdated.

    Args:
        auto_update: If True, automatically update when version is outdated.

    Returns:
        VersionInfo with current state after any updates.
    """
    info = check_version()

    if info.needs_update:
        logger.warning(info.message)

        if auto_update:
            success, msg = update_ytdlp()
            if success:
                logger.info(msg)
                # Re-check after update
                return check_version()
            else:
                logger.warning(msg)

    return info
