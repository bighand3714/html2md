"""Site strategy configuration and auto-detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from bs4 import BeautifulSoup

from .errors import StrategyNotFoundError


@dataclass
class CitationConfig:
    """Configuration for citation/footnote extraction and mapping."""

    superscript_selector: str = "sup.reference"
    # Regex to extract the citation ID from the <a href="..."> in a superscript.
    # Must contain exactly one capture group for the cite ID.
    cite_href_pattern: str = r"#cite_note-(.+)"
    # Attribute on the bottom reference element that holds the display number/letter.
    # e.g. Wikipedia uses "data-mw-footnote-number".
    display_number_attr: str | None = "data-mw-footnote-number"
    # Regex that display numbers matching (letters) indicate Notes.
    notes_pattern: str = r"^[a-z]$"
    # Regex that display numbers matching (digits) indicate References.
    refs_pattern: str = r"^\d+$"
    # CSS selector for the references container at the page bottom.
    references_container_selector: str = ".mw-references-wrap ol.references"
    # CSS selector for individual reference items within the container.
    reference_item_selector: str = "li"
    # Attribute on the reference item whose value (after stripping) forms the cite_id.
    reference_item_id_attr: str = "id"
    # Prefix to strip from the id attribute value to get the bare cite_id.
    # e.g. Wikipedia items have id="cite_note-1" → strip "cite_note-"
    reference_item_id_prefix: str | None = None
    # Fallback prefixes to try if the primary prefix doesn't match.
    # Used for old-style Wikipedia pages that use "cite_ref-" instead of "cite_note-".
    reference_item_id_prefixes: list[str] | None = None


@dataclass
class ContentConfig:
    """Configuration for content extraction and cleaning."""

    main_selector: str = ".mw-parser-output"
    title_selector: str = "#firstHeading"
    subtitle_selector: str | None = "#siteSub"
    remove_selectors: list[str] = field(default_factory=lambda: [
        ".mw-editsection",
        "[role='navigation']",
        ".mw-jump-link",
        "style",
        "script",
    ])


@dataclass
class ElementConfig:
    """Configuration for special element handling."""

    infobox_handling: Literal["table", "remove"] = "table"
    toc_handling: Literal["remove", "keep"] = "remove"
    heading_offset: int = 0
    template_selectors: list[str] = field(default_factory=list)


@dataclass
class LinkConfig:
    """Configuration for link rewriting."""

    base_url: str = ""
    external_link_sections: list[str] = field(default_factory=list)


@dataclass
class SiteStrategy:
    """Complete site strategy loaded from a YAML file."""

    name: str = ""
    site_id: str = ""
    url_patterns: list[str] = field(default_factory=list)
    meta_selectors: list[str] = field(default_factory=list)
    encoding: str = "utf-8"
    content: ContentConfig = field(default_factory=ContentConfig)
    citations: CitationConfig = field(default_factory=CitationConfig)
    elements: ElementConfig = field(default_factory=ElementConfig)
    links: LinkConfig = field(default_factory=LinkConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "SiteStrategy":
        """Load a strategy from a YAML file."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(
            name=data.get("name", ""),
            site_id=data.get("site_id", path.stem),
            url_patterns=data.get("url_patterns", []),
            meta_selectors=data.get("meta_selectors", []),
            encoding=data.get("encoding", "utf-8"),
            content=ContentConfig(**data.get("content", {})),
            citations=CitationConfig(**data.get("citations", {})),
            elements=ElementConfig(**data.get("elements", {})),
            links=LinkConfig(**data.get("links", {})),
        )

    @classmethod
    def load_all(cls, sites_dir: Path) -> dict[str, "SiteStrategy"]:
        """Load all .yaml strategy files from a directory.

        Returns a dict mapping site_id → SiteStrategy.
        """
        strategies: dict[str, SiteStrategy] = {}
        if not sites_dir.is_dir():
            return strategies
        for yaml_file in sorted(sites_dir.glob("*.yaml")):
            strategy = cls.from_yaml(yaml_file)
            strategies[strategy.site_id] = strategy
        return strategies

    @classmethod
    def detect(
        cls,
        html: str,
        url_hint: str | None = None,
        strategies: dict[str, "SiteStrategy"] | None = None,
    ) -> "SiteStrategy":
        """Auto-detect which site strategy matches the input.

        Detection priority:
        1. If url_hint is provided, match against url_patterns by domain.
        2. For local HTML files (no url_hint), check meta_selectors.
        3. If nothing matches, raise StrategyNotFoundError.

        Args:
            html: The HTML content as a string.
            url_hint: URL or file path hint.
            strategies: Dict of loaded strategies. If None, no strategies are loaded.

        Returns:
            The matched SiteStrategy.

        Raises:
            StrategyNotFoundError: If no strategy matches.
        """
        if strategies is None:
            strategies = {}

        if not strategies:
            raise StrategyNotFoundError(
                "No site strategies loaded. Ensure sites/*.yaml files exist."
            )

        # Priority 1: URL domain matching
        if url_hint:
            for strategy in strategies.values():
                for pattern in strategy.url_patterns:
                    if pattern in url_hint:
                        return strategy

        # Priority 2: HTML meta tag matching (for local files)
        soup = BeautifulSoup(html, "lxml")
        for strategy in strategies.values():
            for selector in strategy.meta_selectors:
                if soup.select_one(selector):
                    return strategy

        # Priority 3: Heuristic fallback for local files
        matched = cls._detect_heuristic(soup, html)
        if matched:
            return matched

        # Nothing matched
        available = ", ".join(strategies.keys())
        raise StrategyNotFoundError(
            f"Cannot detect site strategy. Available: {available}. "
            f"Use --strategy to specify one manually."
        )

    @classmethod
    def _detect_heuristic(
        cls,
        soup: BeautifulSoup,
        html: str,
    ) -> "SiteStrategy | None":
        """Fallback heuristic detection for local HTML files without meta tags.

        Checks common features that distinguish wiki sites even in
        saved/downloaded HTML.
        """
        # Load all strategies for matching
        from pathlib import Path as _Path
        sites_dir = _Path(__file__).resolve().parent.parent.parent / "sites"
        strategies = cls.load_all(sites_dir)
        if not strategies:
            return None

        # Check <html lang="ja"> for Japanese Wikipedia
        html_tag = soup.find("html")
        lang = html_tag.get("lang", "") if html_tag else ""

        # Check generator meta tag
        generator = soup.select_one("meta[name='generator']")
        generator_content = generator.get("content", "") if generator else ""

        # Check title
        title_tag = soup.find("title")
        title_text = title_tag.get_text() if title_tag else ""

        # Check for page class patterns
        page_classes = " ".join(html_tag.get("class", [])) if html_tag else ""

        # Wikipedia JP: lang="ja" + MediaWiki generator
        if lang == "ja" and "MediaWiki" in generator_content:
            if "wikipedia_jp" in strategies:
                return strategies["wikipedia_jp"]

        # Wikipedia EN: lang="en" + Wikipedia in title
        if "Wikipedia" in title_text:
            if "wikipedia_en" in strategies:
                return strategies["wikipedia_en"]

        # Fandom: fandom.com patterns in page classes or hrefs
        if "fandom" in page_classes.lower() or "fandom" in html.lower():
            if "fandom" in strategies:
                return strategies["fandom"]

        # MediaWiki-based (generic fallback to Wikipedia EN)
        if "MediaWiki" in generator_content and lang == "en":
            if "wikipedia_en" in strategies:
                return strategies["wikipedia_en"]

        return None


def resolve_strategy(
    html: str,
    url_hint: str | None = None,
    strategy_name: str | None = None,
    sites_dir: Path | None = None,
) -> SiteStrategy:
    """Resolve the strategy to use for conversion.

    Args:
        html: HTML content.
        url_hint: URL or file path hint for auto-detection.
        strategy_name: Manual strategy override (site_id).
        sites_dir: Directory containing site YAML files.

    Returns:
        The resolved SiteStrategy.

    Raises:
        StrategyNotFoundError: If strategy_name is given but not found,
            or if auto-detection fails.
    """
    if sites_dir is None:
        # Default: sites/ directory relative to the package
        sites_dir = Path(__file__).resolve().parent.parent.parent / "sites"

    strategies = SiteStrategy.load_all(sites_dir)

    if strategy_name:
        if strategy_name not in strategies:
            available = ", ".join(strategies.keys())
            raise StrategyNotFoundError(
                f"Strategy '{strategy_name}' not found. Available: {available}"
            )
        return strategies[strategy_name]

    return SiteStrategy.detect(html, url_hint, strategies)
