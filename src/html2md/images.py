"""Image processing: base64 extraction and external URL preservation."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from bs4 import Tag

from .errors import ImageExtractionError, WarningCollector


class ImageProcessor:
    """Process images in the HTML document.

    - External URL images: Keep as-is, ensuring proper Markdown format.
    - Base64-encoded images: Decode and save to img/ directory,
      replace src with relative path.
    """

    def __init__(
        self,
        collector: WarningCollector | None = None,
    ):
        self.collector = collector or WarningCollector()
        self._img_counter: dict[str, int] = {}

    @staticmethod
    def is_base64(src: str) -> bool:
        """Check if an image src is a base64 data URI."""
        return src.startswith("data:image/")

    def process(self, soup: Tag, output_dir: Path) -> None:
        """Process all <img> elements in-place.

        Args:
            soup: The BeautifulSoup document or element to process.
            output_dir: Directory where img/ subfolder will be created.
        """
        img_tags = soup.find_all("img")
        for img in img_tags:
            self._process_single(img, output_dir)

    def _process_single(self, img: Tag, output_dir: Path) -> None:
        """Process a single <img> tag."""
        src = img.get("src", "")

        # Fandom lazy-loading: real image is in data-src,
        # src is a 1x1 placeholder. Use data-src when available.
        data_src = img.get("data-src", "")
        if data_src and not self.is_base64(data_src):
            img["src"] = data_src
            src = data_src

        if not src:
            self.collector.warn("Image with no src attribute", img)
            return

        if self.is_base64(src):
            try:
                new_src = self._extract_base64(src, output_dir, img)
                img["src"] = new_src
            except Exception as e:
                self.collector.warn(f"Failed to extract base64 image: {e}", img)
        elif not src.startswith(("http://", "https://", "data:", "img/", "//")):
            # Local path from browser "Save As" — src was rewritten
            # to a relative file path. Try to recover the original URL
            # from Wikipedia's resource attribute.
            resource = img.get("resource", "")
            if resource:
                new_src = self._resolve_resource_url(resource)
                if new_src:
                    img["src"] = new_src
        else:
            # External URL: keep as-is. The converter will handle the
            # [![](url)](link_url) wrapping if the img is inside an <a> tag.
            pass

    def _extract_base64(self, src: str, output_dir: Path, img_tag: Tag) -> str:
        """Decode a base64 image, save to img/, return relative path.

        Args:
            src: The base64 data URI.
            output_dir: The parent output directory.
            img_tag: The img Tag (for context in error messages).

        Returns:
            Relative path to the saved image file (e.g. 'img/image_001.png').
        """
        # Parse data URI: data:image/png;base64,<data>
        match = re.match(r"data:image/(\w+);base64,(.+)", src, re.IGNORECASE)
        if not match:
            raise ImageExtractionError(f"Invalid base64 data URI format")

        ext = match.group(1).lower()
        data = match.group(2)

        # Normalize extensions
        ext_map = {"jpeg": "jpg", "svg+xml": "svg"}
        ext = ext_map.get(ext, ext)

        # URL-decode (Fandom encodes '=' as '%3D') and fix padding
        from urllib.parse import unquote
        data = unquote(data)
        # Add missing padding
        missing = len(data) % 4
        if missing:
            data += "=" * (4 - missing)

        try:
            image_bytes = base64.b64decode(data)
        except Exception as e:
            raise ImageExtractionError(f"Base64 decode failed: {e}")

        # Create img/ subdirectory
        img_dir = output_dir / "img"
        img_dir.mkdir(parents=True, exist_ok=True)

        # Generate sequential filename per extension
        self._img_counter.setdefault(ext, 0)
        self._img_counter[ext] += 1
        filename = f"image_{self._img_counter[ext]:03d}.{ext}"
        filepath = img_dir / filename

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        return f"img/{filename}"

    @staticmethod
    def _resolve_resource_url(resource: str) -> str | None:
        """Convert a Wikipedia resource attribute to a working image URL.

        Browser "Save As" rewrites img src to local paths but preserves
        the original File: page URL in the resource attribute, e.g.:
            resource="//en.wikipedia.org/wiki/File:Hideo_Kojima.jpg"

        We build a Special:FilePath URL that 302-redirects to the
        actual image on upload.wikimedia.org.

        Returns:
            Absolute image URL, or None if resource can't be parsed.
        """
        from urllib.parse import urlparse, unquote

        if resource.startswith("//"):
            resource = "https:" + resource

        parsed = urlparse(resource)
        domain = parsed.netloc
        path = unquote(parsed.path)

        # Extract filename from /wiki/File:XXX or /wiki/ファイル:XXX
        match = re.match(
            r"/wiki/(?:File|ファイル|檔案|Archivo|Fichier|Datei):(.+)",
            path, re.IGNORECASE,
        )
        if not match:
            return None

        filename = match.group(1).strip()
        if not filename:
            return None

        return f"https://{domain}/wiki/Special:FilePath/{filename}"
