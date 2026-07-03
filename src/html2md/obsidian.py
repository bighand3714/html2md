"""Obsidian-specific Markdown formatting utilities."""

from __future__ import annotations

import re


def sanitize_footnote_id(raw: str) -> str:
    """Sanitize a raw ID for use as an Obsidian footnote identifier.

    Obsidian footnote IDs must be valid for the [^id] syntax.
    Allowed: alphanumeric, underscores, hyphens, dots.
    """
    return re.sub(r"[^a-zA-Z0-9_.\-]", "_", raw)


def make_footnote_ref(display_name: str, is_note: bool) -> str:
    """Create an Obsidian footnote reference marker.

    Args:
        display_name: The display name (e.g. '1', 'a', 'GSreview').
        is_note: True for Notes group (note_ prefix), False for References (ref_ prefix).

    Returns:
        A footnote reference like 'ref_1' or 'note_a'.
    """
    prefix = "note" if is_note else "ref"
    sanitized = sanitize_footnote_id(display_name)
    return f"{prefix}_{sanitized}"


def format_footnote_ref_marker(ref_id: str) -> str:
    """Format an inline footnote reference in Obsidian syntax.

    Returns: '[^ref_1]' style marker.
    """
    return f"[^{ref_id}]"


def format_footnote_definition(ref_id: str, content: str) -> str:
    """Format a footnote definition line.

    Args:
        ref_id: The footnote ID (e.g. 'ref_1').
        content: The citation text.

    Returns:
        A footnote definition like '[^ref_1]: Citation text here...'
    """
    # Clean up content: normalize whitespace, remove newlines within a single citation
    cleaned = " ".join(content.split())
    return f"[^{ref_id}]: {cleaned}"


def format_notes_section(definitions: list[str]) -> str:
    """Format the Notes section with footnote definitions.

    Args:
        definitions: List of formatted footnote definition strings.

    Returns:
        Markdown string for the Notes section, or empty string if no definitions.
    """
    if not definitions:
        return ""
    return "## Notes\n\n" + "\n\n".join(definitions) + "\n"


def format_references_section(definitions: list[str]) -> str:
    """Format the References section with footnote definitions.

    Args:
        definitions: List of formatted footnote definition strings.

    Returns:
        Markdown string for the References section, or empty string if no definitions.
    """
    if not definitions:
        return ""
    return "## References\n\n" + "\n\n".join(definitions) + "\n"


# Mapping of common HTML entities to Unicode for footnote content
_ENTITY_MAP = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&nbsp;": " ",
}


def clean_inline_html(text: str) -> str:
    """Clean up HTML tags and entities from citation text.

    Strips basic inline formatting tags (b, i, a, span) while preserving
    the text content. Also decodes common HTML entities.
    """
    # Decode entities first
    for entity, char in _ENTITY_MAP.items():
        text = text.replace(entity, char)

    # Remove common inline tags but keep their text content
    text = re.sub(r"</?(?:b|i|em|strong|span|code|tt)[^>]*>", "", text)

    # Replace <a> tags with their text content
    text = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", text)

    # Remove any remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Collapse whitespace
    text = " ".join(text.split())

    return text
