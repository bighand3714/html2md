"""Content extraction: page cleanup, title extraction, and DOM normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from .errors import WarningCollector
from .obsidian import separated_inline_text
from .strategy import SiteStrategy


@dataclass
class ExtractedDocument:
    """Result of content extraction."""

    title: str
    subtitle: str | None  # e.g. "From Wikipedia, the free encyclopedia"
    body_soup: BeautifulSoup  # Cleaned DOM ready for further processing


class Extractor:
    """Extract and clean content from a Wiki HTML page."""

    def __init__(
        self,
        strategy: SiteStrategy,
        collector: WarningCollector | None = None,
    ):
        self.strategy = strategy
        self.collector = collector or WarningCollector()

    def extract(self, html_path: Path) -> ExtractedDocument:
        """Extract title, subtitle, and cleaned body from an HTML file.

        Args:
            html_path: Path to the HTML file.

        Returns:
            ExtractedDocument with title, subtitle, and cleaned DOM.
        """
        with open(html_path, "r", encoding=self.strategy.encoding) as f:
            html = f.read()

        parser = getattr(self.strategy, "parser", None) or "html.parser"
        soup = BeautifulSoup(html, parser)
        title, subtitle = self._extract_title(soup)
        self._clean_dom(soup)

        return ExtractedDocument(
            title=title,
            subtitle=subtitle,
            body_soup=soup,
        )

    def _extract_title(self, soup: BeautifulSoup) -> tuple[str, str | None]:
        """Extract the page title and optional subtitle.

        Returns:
            (title, subtitle) tuple. subtitle may be None.
        """
        title = ""
        subtitle = None

        title_el = soup.select_one(self.strategy.content.title_selector)
        if title_el:
            title = separated_inline_text(title_el)
            if not title:
                img = title_el.find("img")
                if img:
                    title = img.get("alt", "").strip()

        if not title and soup.title:
            title = soup.title.get_text(strip=True)

        if self.strategy.content.subtitle_selector:
            sub_el = soup.select_one(self.strategy.content.subtitle_selector)
            if sub_el:
                subtitle = separated_inline_text(sub_el)

        return title, subtitle

    def _clean_dom(self, soup: BeautifulSoup) -> None:
        """Remove unwanted elements from the DOM.

        Handles: TOC removal, element removal via strategy selectors,
        navbox removal, and empty container cleanup.
        """
        # Remove TOC
        if self.strategy.elements.toc_handling == "remove":
            for toc in soup.select("#toc, .toc, .mw-toc, nav.toc"):
                toc.decompose()

        # Remove <noscript> fallback content (avoids duplicate images etc.)
        for el in soup.find_all("noscript"):
            el.decompose()

        # Remove elements specified in strategy
        for selector in self.strategy.content.remove_selectors:
            for el in soup.select(selector):
                el.decompose()

        # Remove navbox templates
        for el in soup.select(".navbox, .NavFrame, .navbox-container, .navbox-wrapper"):
            el.decompose()

        # Remove template elements
        for selector in self.strategy.elements.template_selectors:
            for el in soup.select(selector):
                el.decompose()

        # Remove style and script tags
        for el in soup.find_all(["style", "script"]):
            el.decompose()

        # Remove hidden elements
        for el in soup.select("[style*='display:none'], [style*='display: none']"):
            el.decompose()

    @staticmethod
    def unhide_collapsible_content(root: Tag) -> int:
        """Drop ``hidden="until-found"`` so collapsed content is converted.

        MediaWiki wraps collapsible infobox sections (and other collapsed
        blocks) in an element carrying ``hidden="until-found"``. That content
        is real, renderable content — browsers reveal it on interaction and
        include it in find-in-page — so it must be converted. The Converter's
        hidden-element check would otherwise discard the whole subtree,
        silently dropping rows such as an infobox's regional release dates
        (and their citations, which then survive only as orphan footnotes).

        ``hidden`` in its bare/true form is left alone: that is genuinely
        hidden content.

        Returns:
            Number of elements un-hidden.
        """
        count = 0
        for el in root.find_all(hidden="until-found"):
            del el["hidden"]
            count += 1
        return count

    def get_main_content(self, soup: BeautifulSoup) -> Tag | None:
        """Extract the main content element from the page.

        Returns:
            The main content Tag, or None if not found.
        """
        return soup.select_one(self.strategy.content.main_selector)
