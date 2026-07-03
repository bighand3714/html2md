"""URL downloading for html2md."""

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .errors import DownloadError


class Downloader:
    """Download HTML pages from URLs."""

    _URL_RE = re.compile(r"^https?://", re.IGNORECASE)

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    @staticmethod
    def is_url(input_str: str) -> bool:
        """Check if an input string is a URL (vs. a local file path)."""
        return bool(Downloader._URL_RE.match(input_str))

    def download(self, url: str, output_dir: Path) -> Path:
        """Download a URL to output_dir, returning the saved file path.

        The filename is derived from the URL path. If the path ends with
        '/' or no recognizable filename, uses 'index'.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        response = requests.get(
            url,
            timeout=self.timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()

        # Determine filename from URL
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path and "/" in path:
            filename = path.rsplit("/", 1)[-1]
        elif path:
            filename = path.lstrip("/")
        else:
            filename = parsed.netloc.replace(".", "_")

        # Add .html extension if missing
        if not filename.endswith((".html", ".htm")):
            filename += ".html"

        # Sanitize filename: remove query-string-like characters
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)

        filepath = output_dir / filename

        # Detect encoding from response or fallback to utf-8
        encoding = response.encoding or "utf-8"
        with open(filepath, "w", encoding=encoding) as f:
            f.write(response.text)

        return filepath
