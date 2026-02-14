"""Shared configuration constants for the Snapchat splitter pipeline."""

import re

TARGET_AVATAR_SIZE = 54
MAX_BITMOJI_WORKERS = 8
MIN_HUE_SEPARATION = 30
BITMOJI_API_TIMEOUT = 10
BITMOJI_RETRY_TOTAL = 3
BITMOJI_BACKOFF_FACTOR = 0.5


def sanitize_filename(name: str) -> str:
    """Sanitize a string for safe use as a filename."""
    return re.sub(r'[^\w\-.]', '_', name.strip()) if name else "user"
