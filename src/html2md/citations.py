"""Citation/footnote conversion: the core of html2md.

Handles the mapping from Wiki citation references to Obsidian [^id] footnotes.
Each site strategy defines how to find and classify citations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bs4 import NavigableString, Tag

from .errors import CitationMappingError, WarningCollector
from .obsidian import (
    clean_inline_html,
    format_footnote_definition,
    format_footnote_ref_marker,
    format_notes_section,
    format_references_section,
    make_footnote_ref,
    sanitize_footnote_id,
)

if TYPE_CHECKING:
    from .strategy import CitationConfig


@dataclass
class Citation:
    """A single citation/reference record."""

    cite_id: str            # Original HTML id (e.g. "cite_note-1")
    display_name: str       # Display letter/number (e.g. "a" or "1")
    is_note: bool           # True = Notes group, False = References group
    text: str               # Citation content text (cleaned)
    ref_count: int = 0      # How many times it's referenced in the body


@dataclass
class CitationResult:
    """Result of citation processing."""

    notes: list[Citation] = field(default_factory=list)
    references: list[Citation] = field(default_factory=list)

    @property
    def all_citations(self) -> list[Citation]:
        return self.notes + self.references


class CitationMapper:
    """Map Wiki citations to Obsidian footnotes."""

    def __init__(
        self,
        config: "CitationConfig",
        collector: WarningCollector | None = None,
    ):
        self.config = config
        self.collector = collector or WarningCollector()
        # Compile patterns
        self._cite_href_re = re.compile(config.cite_href_pattern)
        self._notes_re = re.compile(config.notes_pattern) if config.notes_pattern else None
        self._refs_re = re.compile(config.refs_pattern) if config.refs_pattern else None

    # ------------------------------------------------------------------
    # Phase 1: Collect bottom references
    # ------------------------------------------------------------------

    def collect_bottom_references(self, soup: Tag) -> dict[str, Citation]:
        """Scan the bottom references section and build a cite_id → Citation map.

        Args:
            soup: The full page BeautifulSoup object.

        Returns:
            Dict mapping cite_id to Citation object.
        """
        citations: dict[str, Citation] = {}

        # Use select (not select_one) because there may be multiple
        # containers: one for Notes, one for References.
        containers = soup.select(self.config.references_container_selector)
        if not containers:
            self.collector.warn(
                f"References container not found with selector: "
                f"'{self.config.references_container_selector}'"
            )
            return citations

        for container in containers:

            items = container.select(self.config.reference_item_selector)
            for item in items:
                citation = self._parse_reference_item(item)
                if citation:
                    citations[citation.cite_id] = citation

        return citations

    def _parse_reference_item(self, item: Tag) -> Citation | None:
        """Parse a single reference <li> into a Citation object."""
        # Get the cite_id from the item's id attribute
        raw_id = item.get(self.config.reference_item_id_attr, "")
        if not raw_id:
            return None

        # Strip prefix if configured
        cite_id = raw_id
        prefixes = [self.config.reference_item_id_prefix]
        if self.config.reference_item_id_prefixes:
            prefixes.extend(self.config.reference_item_id_prefixes)

        for prefix in prefixes:
            if prefix and raw_id.startswith(prefix):
                cite_id = raw_id[len(prefix):]
                break

        # Determine display name (letter or number)
        display_name = self._extract_display_name(item, cite_id)

        # Classify as Note or Reference
        is_note = self._classify_citation(display_name)

        # Extract text content
        text = self._extract_citation_text(item)

        return Citation(
            cite_id=cite_id,
            display_name=display_name,
            is_note=is_note,
            text=text,
        )

    def _extract_display_name(self, item: Tag, cite_id: str) -> str:
        """Extract the display name (letter/number) from a reference item.

        Strategy:
        1. Check for a specific attribute (e.g. Wikipedia's data-mw-footnote-number).
        2. Parse from the backlink span text (e.g. Fandom's [1] brackets).
        3. Fall back: use the cite_id suffix.
        """
        # Method 1: Named attribute (Wikipedia)
        if self.config.display_number_attr:
            attr_val = item.get(self.config.display_number_attr)
            if attr_val:
                return str(attr_val)

        # Method 2: Parse from backlink/cite-bracket text
        # Look for <span class="cite-bracket"> or similar backlink pattern
        backlinks = item.find_all("a", href=re.compile(r"#cite_ref"))
        if backlinks:
            text = backlinks[0].get_text(strip=True)
            # Filter out non-meaningful values: arrows, carets, empty
            if text and not re.match(r"^[↑^↓↩↪↵]+$", text):
                # Skip single lowercase letters — these are occurrence
                # markers (a, b, c...) used by Fandom/ZeldaWiki backlinks,
                # not actual citation display numbers. Fall through to
                # Method 3 which extracts the real number from cite_id.
                if not re.match(r"^[a-z]$", text):
                    return text

        # Method 3: Last resort - use suffix of cite_id
        parts = cite_id.rsplit("-", 1)
        if len(parts) == 2 and parts[1]:
            return sanitize_footnote_id(parts[1])

        return sanitize_footnote_id(cite_id)

    def _classify_citation(self, display_name: str) -> bool:
        """Determine if a citation is a Note (True) or Reference (False).

        Classification uses the strategy's notes_pattern and refs_pattern.
        - If display_name matches notes_pattern → Note
        - If display_name matches refs_pattern → Reference
        - If neither matches → default to Reference
        """
        if self._notes_re and self._notes_re.match(display_name):
            return True
        if self._refs_re and self._refs_re.match(display_name):
            return False
        # Default: numbers → Reference, letters → Note
        return bool(re.match(r"^[a-zA-Z]$", display_name))

    def _extract_citation_text(self, item: Tag) -> str:
        """Extract clean text from a citation <li> element.

        Removes backlinks (^ a b c links), leaving only the citation content.
        External links in citation text are preserved as Markdown [text](url).
        """
        # Work on a copy to avoid mutating the original
        clone = copy_for_text(item)
        if clone is None:
            return ""

        # Remove backlink <a> elements (the ^ links that jump back to body)
        for backlink in clone.find_all("a", href=re.compile(r"#cite_ref")):
            backlink.decompose()

        # Also remove jump-to links
        for jumplink in clone.find_all("a", class_="mw-jump-link"):
            jumplink.decompose()

        # Convert remaining <a> tags to Markdown [text](url) format
        # before get_text() strips all HTML. This preserves external
        # links inside citation text (e.g. IGN articles, news sources).
        for link in clone.find_all("a"):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if href and text:
                link.replace_with(f"[{text}]({href})")
            elif text:
                link.replace_with(text)

        text = clone.get_text(separator=" ", strip=True)
        return clean_inline_html(text)


    # ------------------------------------------------------------------
    # Phase 2: Replace superscripts in body
    # ------------------------------------------------------------------

    def replace_superscripts(
        self,
        soup: Tag,
        citations: dict[str, Citation],
    ) -> dict[str, Citation]:
        """Replace all citation <sup> elements with [^footnote_id] markers.

        Scans the body for <sup> elements matching the strategy's selector,
        extracts the cite_id from the <a href>, looks up the Citation,
        and replaces the <sup> with an [^ref_N] or [^note_X] string.

        Args:
            soup: The full page BeautifulSoup object.
            citations: cite_id → Citation map from collect_bottom_references.

        Returns:
            Dict of footnote_id → Citation for citations actually used,
            in the order they appear in the body.
        """
        used: dict[str, Citation] = {}
        used_order: list[str] = []  # footnote_ids in order of first appearance

        sups = soup.select(self.config.superscript_selector)
        for sup in sups:
            # Find the <a> tag inside the sup
            link = sup.find("a")
            if link is None:
                self.collector.warn(
                    "Superscript element has no <a> child, skipping", sup
                )
                sup.decompose()
                continue

            href = link.get("href", "")
            match = self._cite_href_re.search(href)
            if not match:
                self.collector.warn(
                    f"Cannot extract cite_id from href '{href}', skipping", sup
                )
                sup.decompose()
                continue

            cite_id = match.group(1)

            # Look up the citation
            citation = citations.get(cite_id)
            if citation is None:
                # Try with prefix if the reference items have a prefix
                # (e.g. href="#cite_note-1" but item id="cite_note-1")
                citation = citations.get(cite_id)
                if citation is None:
                    self.collector.warn(
                        f"Citation '{cite_id}' not found in bottom references", sup
                    )
                    sup.decompose()
                    continue

            citation.ref_count += 1

            if citation.is_note:
                # Letter notes: replace with plain text [a], [b], etc.
                # No footnote jump — just display the letter
                marker = f"[{citation.display_name}]"
                sup.replace_with(marker)
                # Notes are NOT added to used — they stay as plain text
            else:
                # Number references: replace with [^ref_N] footnote
                footnote_id = make_footnote_ref(
                    citation.display_name, citation.is_note
                )

                # Track usage
                if footnote_id not in used:
                    used[footnote_id] = citation
                    used_order.append(footnote_id)

                marker = format_footnote_ref_marker(footnote_id)
                sup.replace_with(marker)

        # Return used citations in order of first appearance
        return {fid: used[fid] for fid in used_order if fid in used}

    # ------------------------------------------------------------------
    # Phase 2b: Remove original References DOM elements
    # ------------------------------------------------------------------

    def remove_references_dom_elements(self, soup: Tag) -> None:
        """Remove original References list from the DOM, keeping Notes.

        After superscripts have been replaced, the original bottom
        References list is redundant (we generate our own footnotes).
        But Notes lists should stay — they show the letter-note content
        which is now plain text [a] [b] in the body.

        Strategy: find all <ol> elements inside references wrappers.
        If the <ol> has data-mw-group="lower-alpha" (Notes), keep it.
        Otherwise, remove the ol and its .mw-references-wrap wrapper.
        Also remove the parent <h2 id="References"> if present.
        """

        ol_elements = soup.select("ol.mw-references, ol.references")
        removed_wrappers = set()

        for ol in list(ol_elements):
            ol_group = ol.get("data-mw-group", "")
            parent = ol.parent
            parent_data = parent.get("data-mw", "") if parent else ""
            is_notes = ol_group == "lower-alpha" or "lower-alpha" in parent_data

            if not is_notes:
                # Find and remove the .mw-references-wrap wrapper
                wrapper = ol.parent
                while wrapper and wrapper.name not in ("body", "[document]"):
                    if "mw-references-wrap" in wrapper.get("class", []):
                        removed_wrappers.add(id(wrapper))
                        wrapper.decompose()
                        break
                    wrapper = wrapper.parent

        # Remove <h2 id="References"> if its following content is gone
        for h2 in soup.find_all("h2"):
            if h2.get("id") != "References":
                continue
            next_el = h2.find_next_sibling()
            if next_el is None or (next_el.name == "div"
                    and "mw-references-wrap" in next_el.get("class", [])
                    and id(next_el) in removed_wrappers):
                h2.decompose()

    # ------------------------------------------------------------------
    # Phase 3: Generate footnote definitions
    # ------------------------------------------------------------------

    def generate_footnote_definitions(
        self, used_citations: dict[str, Citation]
    ) -> tuple[str, str]:
        """Generate the Notes and References footnote definition blocks.

        Args:
            used_citations: footnote_id → Citation map from replace_superscripts.

        Returns:
            (notes_section_md, references_section_md) tuple.
            Each is a complete Markdown section string, or empty string.
        """
        notes_defs: list[str] = []
        refs_defs: list[str] = []

        for footnote_id, citation in used_citations.items():
            definition = format_footnote_definition(footnote_id, citation.text)
            if citation.is_note:
                notes_defs.append(definition)
            else:
                refs_defs.append(definition)

        # Sort: Notes by letter, References by numeric
        notes_defs.sort(key=_sort_key)
        refs_defs.sort(key=_sort_key)

        notes_section = format_notes_section(notes_defs)
        refs_section = format_references_section(refs_defs)

        return notes_section, refs_section

    # ------------------------------------------------------------------
    # Convenience: run all phases
    # ------------------------------------------------------------------

    def process(self, soup: Tag) -> CitationResult:
        """Run all phases of citation processing.

        Args:
            soup: The full page BeautifulSoup object.

        Returns:
            CitationResult with notes and references lists.
        """
        bottom_citations = self.collect_bottom_references(soup)
        used = self.replace_superscripts(soup, bottom_citations)
        # Remove original References DOM elements (keep Notes)
        self.remove_references_dom_elements(soup)

        # Include ALL bottom citations, not just those referenced in body.
        # This preserves unreferenced entries so users can manually fix
        # citation mapping issues without losing data. Citations that were
        # referenced have their ref_count already incremented by
        # replace_superscripts (they are the same Python objects).
        all_citations = list(bottom_citations.values())
        notes = [c for c in all_citations if c.is_note]
        refs = [c for c in all_citations if not c.is_note]

        return CitationResult(notes=notes, references=refs)


def _sort_key(definition: str) -> tuple[int, str]:
    """Sort key for footnote definitions: numeric first, then alphabetical."""
    import re as _re
    match = _re.match(r"\[\^(\w+)_(\d+)", definition)
    if match:
        return (0, match.group(2).zfill(10))
    match = _re.match(r"\[\^(\w+)_([a-zA-Z]+)", definition)
    if match:
        return (1, match.group(2).lower())
    return (2, definition)


def copy_for_text(tag: Tag) -> Tag | None:
    """Create a copy of a Tag suitable for text extraction."""
    try:
        from copy import copy
        return copy(tag)
    except Exception:
        return None
