"""HTML to Markdown core converter.

Recursively walks the BeautifulSoup DOM tree and emits Markdown.
Handles headings, paragraphs, lists, links, images, tables,
emphasis, and inline formatting.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

from bs4 import Comment, NavigableString, Tag

from .errors import WarningCollector
from .strategy import SiteStrategy


class Converter:
    """Convert cleaned HTML DOM to Markdown text."""

    # Tags treated as block-level (force surrounding newlines)
    BLOCK_TAGS = {
        "p", "div", "section", "article", "header", "footer",
        "blockquote", "pre", "hr", "figure", "figcaption",
        "ul", "ol", "dl", "table",
    }

    # Tags treated as inline (no extra newlines)
    INLINE_TAGS = {
        "span", "a", "b", "strong", "i", "em", "u", "s", "del",
        "code", "tt", "kbd", "sub", "sup", "small", "mark",
        "abbr", "cite", "q", "br",
    }

    # Tags to skip entirely (their children are processed inline)
    SKIP_TAGS = {"span", "div"}

    def __init__(
        self,
        strategy: SiteStrategy,
        output_dir: Path | None = None,
        collector: WarningCollector | None = None,
    ):
        self.strategy = strategy
        self.output_dir = output_dir or Path(".")
        self.collector = collector or WarningCollector()
        self._heading_offset = strategy.elements.heading_offset
        self._base_url = strategy.links.base_url

    def convert(self, element: Tag) -> str:
        """Convert an HTML element and its children to Markdown.

        Args:
            element: A BeautifulSoup Tag to convert.

        Returns:
            Markdown string.
        """
        return self._convert_element(element)

    def _convert_element(self, element: Tag | NavigableString) -> str:
        """Recursively convert any node to Markdown."""
        if isinstance(element, Comment):
            return ""
        if isinstance(element, NavigableString):
            return self._text_to_md(str(element))

        tag_name = element.name.lower() if element.name else ""

        # Skip hidden elements
        if element.get("hidden") or "display:none" in element.get("style", ""):
            return ""

        # Dispatch by tag name
        handlers = {
            "h1": self._heading_to_md,
            "h2": self._heading_to_md,
            "h3": self._heading_to_md,
            "h4": self._heading_to_md,
            "h5": self._heading_to_md,
            "h6": self._heading_to_md,
            "p": self._para_to_md,
            "br": self._br_to_md,
            "hr": self._hr_to_md,
            "ul": self._list_to_md,
            "ol": self._list_to_md,
            "li": self._li_to_md,
            "a": self._link_to_md,
            "img": self._image_to_md,
            "b": lambda e: f"**{self._children_text(e)}**",
            "strong": lambda e: f"**{self._children_text(e)}**",
            "i": lambda e: f"*{self._children_text(e)}*",
            "em": lambda e: f"*{self._children_text(e)}*",
            "s": lambda e: f"~~{self._children_text(e)}~~",
            "del": lambda e: f"~~{self._children_text(e)}~~",
            "code": self._code_to_md,
            "pre": self._pre_to_md,
            "blockquote": self._blockquote_to_md,
            "figure": self._figure_to_md,
            "figcaption": lambda e: f"\n*{self._children_text(e)}*\n",
            "table": self._table_to_md,
            "aside": self._infobox_to_md,
        }

        handler = handlers.get(tag_name)
        if handler:
            return handler(element)

        # Unknown tags: recurse children
        if tag_name in self.SKIP_TAGS:
            return self._children_text(element)
        return self._children_text(element)

    # ------------------------------------------------------------------
    # Heading
    # ------------------------------------------------------------------

    def _heading_to_md(self, element: Tag) -> str:
        """Convert h1-h6 to Markdown heading with level offset."""
        level = int(element.name[1]) + self._heading_offset
        level = min(level, 6)  # Markdown only supports h1-h6
        text = " ".join(self._children_text(element).split())
        return f"\n\n{'#' * level} {text}\n\n"

    # ------------------------------------------------------------------
    # Paragraph
    # ------------------------------------------------------------------

    def _para_to_md(self, element: Tag) -> str:
        """Convert <p> to Markdown paragraph."""
        text = " ".join(self._children_text(element).split())
        # Skip empty paragraphs
        if not text.strip():
            return ""
        return f"\n\n{text}\n\n"

    # ------------------------------------------------------------------
    # Line breaks and horizontal rules
    # ------------------------------------------------------------------

    def _br_to_md(self, element: Tag) -> str:
        return "\n"

    def _hr_to_md(self, element: Tag) -> str:
        return "\n\n---\n\n"

    # ------------------------------------------------------------------
    # Lists
    # ------------------------------------------------------------------

    def _list_to_md(self, element: Tag) -> str:
        """Convert <ul>/<ol> to Markdown list."""
        items = element.find_all("li", recursive=False)
        if not items:
            return ""

        is_ordered = element.name == "ol"
        lines: list[str] = []

        # Check for Notes group (lower-alpha) — use letter labels
        group = element.get("data-mw-group", "")
        is_notes_list = group == "lower-alpha"

        for i, li in enumerate(items):
            if is_notes_list:
                # Letter labels: a, b, c, ...
                letter = chr(ord("a") + i) if i < 26 else str(i)
                prefix = f"{letter}. "
            elif is_ordered:
                prefix = f"{i + 1}. "
            else:
                prefix = "- "
            text = self._children_text(li)
            lines.append(f"{prefix}{text}")

        return "\n\n" + "\n".join(lines) + "\n\n"

    def _li_to_md(self, element: Tag) -> str:
        """Convert <li> text (used when li is processed via _list_to_md)."""
        return self._children_text(element)

    # ------------------------------------------------------------------
    # Links and images
    # ------------------------------------------------------------------

    def _link_to_md(self, element: Tag) -> str:
        """Convert <a> to [text](url). Handles image links."""
        href = element.get("href", "")
        if not href:
            return self._children_text(element)

        # Resolve relative URLs
        if self._base_url and not href.startswith(("http://", "https://", "#", "mailto:")):
            href = urljoin(self._base_url, href)

        # Check if this link contains an image
        img = element.find("img")
        if img and len(list(element.children)) == 1:
            # Single image link: [![](src)](href)
            src = img.get("src", "")
            alt = img.get("alt", "")
            if self._base_url and src and not src.startswith(("http://", "https://", "data:", "img/")):
                src = urljoin(self._base_url, src)
            # Apply display width for Wikipedia Special:FilePath images.
            # Escaped pipe (\|) avoids table column-separator conflicts.
            width = img.get("width", "")
            if width and "Special:FilePath" in src:
                return f"[![{alt}\\|{width}]({src})]({href})"
            return f"[![{alt}]({src})]({href})"

        text = self._children_text(element)
        if not text:
            text = href

        return f"[{text}]({href})"

    def _image_to_md(self, element: Tag) -> str:
        """Convert <img> to ![](url).

        Wikipedia Special:FilePath URLs return full-resolution originals
        (e.g. 4480px wide). We apply the HTML width attribute via
        Obsidian's |WIDTH syntax so images render at the intended size.
        Fandom and other CDN images (which already serve resized
        thumbnails) are not affected.
        """
        src = element.get("src", "")
        alt = element.get("alt", "")

        if not src:
            return ""

        # Resolve relative URLs for images
        if self._base_url and not src.startswith(("http://", "https://", "data:", "img/")):
            src = urljoin(self._base_url, src)

        # Apply display width for Wikipedia images (special:filepath returns original).
        # Escaped pipe (\|) avoids table column-separator conflicts.
        width = element.get("width", "")
        if width and "Special:FilePath" in src:
            return f"![{alt}\\|{width}]({src})"

        return f"![{alt}]({src})"

    # ------------------------------------------------------------------
    # Code blocks
    # ------------------------------------------------------------------

    def _code_to_md(self, element: Tag) -> str:
        text = element.get_text()
        return f"`{text}`"

    def _pre_to_md(self, element: Tag) -> str:
        code = element.find("code")
        lang = code.get("class", [""])[0].replace("language-", "") if code else ""
        text = element.get_text()
        return f"\n\n```{lang}\n{text}\n```\n\n"

    # ------------------------------------------------------------------
    # Blockquote
    # ------------------------------------------------------------------

    def _blockquote_to_md(self, element: Tag) -> str:
        lines = self._children_text(element).strip().split("\n")
        quoted = "\n".join(f"> {line}" for line in lines)
        return f"\n\n{quoted}\n\n"

    # ------------------------------------------------------------------
    # Figure
    # ------------------------------------------------------------------

    def _figure_to_md(self, element: Tag) -> str:
        """Convert <figure> containing <img> and <figcaption>."""
        parts: list[str] = []
        for child in element.children:
            if isinstance(child, Tag) and child.name == "img":
                parts.append(self._image_to_md(child))
            elif isinstance(child, Tag) and child.name == "figcaption":
                parts.append(self._figcaption_to_md(child))
            else:
                result = self._convert_element(child)
                if result.strip():
                    parts.append(result)
        return "\n\n" + "\n\n".join(parts) + "\n\n"

    def _figcaption_to_md(self, element: Tag) -> str:
        return f"*{self._children_text(element)}*"

    # ------------------------------------------------------------------
    # Tables (delegates to TableConverter)
    # ------------------------------------------------------------------

    def _table_to_md(self, element: Tag) -> str:
        """Convert <table> to Markdown table.

        Delegates to TableConverter for complex processing.
        For simple fallback, generates a basic Markdown table.
        """
        # Check if this table has already been processed by TableConverter
        # (merged cells split). If not, do a basic conversion.
        rows = element.find_all("tr")
        if not rows:
            return ""

        grid: list[list[str]] = []
        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_data = [self._table_cell_text(cell) for cell in cells]
            grid.append(row_data)

        if not grid:
            return ""

        # Normalize columns
        max_cols = max(len(r) for r in grid)
        for r in grid:
            while len(r) < max_cols:
                r.append("")

        lines: list[str] = []
        for i, r in enumerate(grid):
            lines.append("| " + " | ".join(r) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")

        return "\n\n" + "\n".join(lines) + "\n\n"

    # ------------------------------------------------------------------
    # Table cell text (preserves <br> for inline line breaks)
    # ------------------------------------------------------------------

    def _table_cell_text(self, element: Tag) -> str:
        """Extract cell content, converting <br> and nested newlines
        to MD-compatible inline line breaks."""
        parts: list[str] = []
        for child in element.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif child.name == "br":
                parts.append("<br>")
            else:
                parts.append(self._convert_element(child))
        text = "".join(parts).strip()
        # Convert newlines from nested elements (ul/li etc.) to <br>
        text = text.replace("\n", "<br>")
        # Collapse whitespace but preserve <br> tags
        text = " ".join(text.split())
        # Clean up whitespace around <br> tags
        text = text.replace(" <br>", "<br>").replace("<br> ", "<br>")
        return text

    # ------------------------------------------------------------------
    # Infobox (Fandom/ZeldaWiki portable infobox)
    # ------------------------------------------------------------------

    def _infobox_to_md(self, element: Tag) -> str:
        """Convert aside.portable-infobox to Markdown tables.

        Fandom's infobox is an <aside> containing a title, tabbed image
        gallery, and groups of key-value rows. Each group becomes a
        small table; images are extracted inline.
        """
        if "portable-infobox" not in (element.get("class") or []):
            return self._children_text(element)

        parts: list[str] = []

        # Extract all tab images as linked Markdown.
        # Base64 placeholders are replaced with CDN thumbnail URLs
        # derived from the parent <a> href.
        for img in element.select("img.pi-image-thumbnail"):
            alt = img.get("alt", "")
            parent_a = img.find_parent("a")
            if parent_a and parent_a.get("href"):
                href = parent_a["href"]
                # Derive CDN thumbnail URL from full image URL
                parts.append(
                    f"[![{alt}]({self._thumbnail_url(href)})]({href})"
                )
            else:
                parts.append(f"![{alt}]({img.get('src', '')})")

        # Top-level key-value rows (not inside a .pi-group)
        direct_rows: list[tuple[str, str]] = []
        for data in element.select(":scope > .pi-data"):
            label_el = data.select_one(".pi-data-label")
            value_el = data.select_one(".pi-data-value")
            label = label_el.get_text(strip=True) if label_el else ""
            value = self._table_cell_text(value_el).strip() if value_el else ""
            if label or value:
                direct_rows.append((label, value))
        if direct_rows:
            parts.append(self._infobox_table(None, direct_rows))

        # Grouped key-value rows
        for group in element.select(".pi-group"):
            header = group.select_one(".pi-header")
            header_text = header.get_text(strip=True) if header else ""

            rows: list[tuple[str, str]] = []
            for data in group.select(".pi-data"):
                label_el = data.select_one(".pi-data-label")
                value_el = data.select_one(".pi-data-value")
                label = label_el.get_text(strip=True) if label_el else ""
                value = self._table_cell_text(value_el).strip() if value_el else ""
                if label or value:
                    rows.append((label, value))

            if rows:
                parts.append(self._infobox_table(header_text, rows))

        return "".join(parts)

    def _infobox_table(
        self, header: str | None, rows: list[tuple[str, str]]
    ) -> str:
        """Build a Markdown table for an infobox section."""
        lines: list[str] = []
        if header:
            lines.append(f"| **{header}** | |")
        else:
            lines.append("| | |")
        lines.append("|---|---|")
        for label, value in rows:
            lines.append(f"| {label} | {value} |")
        return "\n\n" + "\n".join(lines) + "\n\n"

    @staticmethod
    def _thumbnail_url(full_url: str, width: int = 250) -> str:
        """Derive a Fandom CDN thumbnail URL from a full image URL.

        Inserts /scale-to-width-down/{width} before the query string.
        E.g. .../revision/latest?cb=... → .../revision/latest/scale-to-width-down/250?cb=...
        """
        if "static.wikia.nocookie.net" not in full_url:
            return full_url
        if "/revision/latest" in full_url:
            return full_url.replace(
                "/revision/latest",
                f"/revision/latest/scale-to-width-down/{width}",
            )
        return full_url

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _children_text(self, element: Tag) -> str:
        """Recursively convert all children to Markdown and join."""
        parts: list[str] = []
        for child in element.children:
            result = self._convert_element(child)
            parts.append(result)
        # Join and normalize: single-space between words, preserve
        # exactly one space across element boundaries
        joined = "".join(parts)
        return joined

    def _text_to_md(self, text: str) -> str:
        """Keep text as-is for inline context; block-level handlers
        do their own whitespace normalization."""
        return text
