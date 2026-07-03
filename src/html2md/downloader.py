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

    # Map of domain patterns → site display names
    _SITE_NAMES = {
        "wikipedia.org": "Wikipedia",
        "fandom.com": "Fandom",
        "wikia.com": "Fandom",
    }

    def _extract_site_name(self, netloc: str) -> str | None:
        """Extract a human-readable site name from the domain.

        Returns None if no recognizable site name is found.
        """
        for pattern, name in self._SITE_NAMES.items():
            if pattern in netloc:
                return name
        # Fallback: use the domain's main segment
        # e.g. "zeldawiki.wiki" → "Zeldawiki"
        parts = netloc.split(".")
        if len(parts) >= 2:
            return parts[-2].capitalize()
        return netloc.capitalize()

    def download(self, url: str, output_dir: Path) -> Path:
        """Download a URL to output_dir, returning the saved file path.

        The filename is derived from the URL path and site name.
        Format: PageName - SiteName.html
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        response = requests.get(
            url,
            timeout=self.timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
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
            filename = "index"

        # Extract site name from domain
        site_name = self._extract_site_name(parsed.netloc)

        # Add .html extension if missing
        if not filename.endswith((".html", ".htm")):
            filename += ".html"

        # Sanitize filename
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)

        # Append site name before extension
        if site_name:
            base, ext = filename.rsplit(".", 1)
            filename = f"{base} - {site_name}.{ext}"

        filepath = output_dir / filename

        # Detect encoding from response or fallback to utf-8
        encoding = response.encoding or "utf-8"
        with open(filepath, "w", encoding=encoding) as f:
            f.write(response.text)

        return filepath
