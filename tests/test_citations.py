"""Tests for the citation mapping system."""

import pytest
from bs4 import BeautifulSoup

from html2md.citations import Citation, CitationMapper
from html2md.errors import WarningCollector
from html2md.obsidian import (
    format_footnote_definition,
    format_footnote_ref_marker,
    make_footnote_ref,
)
from html2md.strategy import CitationConfig


class TestCitationMapper:
    """Test the CitationMapper with Wikipedia-style HTML."""

    @pytest.fixture
    def config(self):
        return CitationConfig(
            superscript_selector="sup.reference",
            cite_href_pattern=r"#cite_note-(.+)",
            display_number_attr="data-mw-footnote-number",
            notes_pattern=r"^[a-z]$",
            refs_pattern=r"^\d+$",
            references_container_selector=".mw-references-wrap ol.references",
            reference_item_selector="li",
            reference_item_id_attr="id",
            reference_item_id_prefix="cite_note-",
        )

    @pytest.fixture
    def mapper(self, config):
        return CitationMapper(config)

    def test_collect_bottom_references(self, mapper):
        html = """
        <html><body>
        <div class="mw-references-wrap">
        <ol class="mw-references references">
        <li id="cite_note-1" data-mw-footnote-number="a">Note A content</li>
        <li id="cite_note-2" data-mw-footnote-number="b">Note B content</li>
        <li id="cite_note-3" data-mw-footnote-number="1">Reference 1 content</li>
        <li id="cite_note-4" data-mw-footnote-number="2">Reference 2 content</li>
        </ol></div>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")

        citations = mapper.collect_bottom_references(soup)

        assert len(citations) == 4
        assert citations["1"].display_name == "a"
        assert citations["1"].is_note is True
        assert citations["2"].display_name == "b"
        assert citations["2"].is_note is True
        assert citations["3"].display_name == "1"
        assert citations["3"].is_note is False
        assert citations["4"].display_name == "2"
        assert citations["4"].is_note is False

    def test_collect_empty(self, mapper):
        html = "<html><body></body></html>"
        soup = BeautifulSoup(html, "lxml")
        citations = mapper.collect_bottom_references(soup)
        assert len(citations) == 0

    def test_replace_superscripts(self, mapper):
        soup = BeautifulSoup("""
        <html><body>
        <p>Some text<sup class="reference"><a href="#cite_note-5">[1]</a></sup> more text.</p>
        <div class="mw-references-wrap">
        <ol class="mw-references references">
        <li id="cite_note-5" data-mw-footnote-number="1">Citation text here</li>
        </ol></div>
        </body></html>
        """, "lxml")

        citations = mapper.collect_bottom_references(soup)
        used = mapper.replace_superscripts(soup, citations)

        body_text = soup.body.get_text()
        assert "[^ref_1]" in body_text
        assert "ref_1" in used
        assert used["ref_1"].text == "Citation text here"

    def test_replace_letter_notes(self, mapper):
        soup = BeautifulSoup("""
        <html><body>
        <p>Some text<sup class="reference"><a href="#cite_note-1">[a]</a></sup>.</p>
        <div class="mw-references-wrap">
        <ol class="mw-references references">
        <li id="cite_note-1" data-mw-footnote-number="a">Note content</li>
        </ol></div>
        </body></html>
        """, "lxml")

        citations = mapper.collect_bottom_references(soup)
        used = mapper.replace_superscripts(soup, citations)

        # Letter notes: plain text [a], NOT in used dict
        assert "[a]" in soup.body.get_text()
        assert "note_a" not in used
        assert len(used) == 0

    def test_duplicate_references(self, mapper):
        """Same citation used twice should get same footnote ID."""
        soup = BeautifulSoup("""
        <html><body>
        <p>First<sup class="reference"><a href="#cite_note-1">[1]</a></sup> and
        second<sup class="reference"><a href="#cite_note-1">[1]</a></sup> use.</p>
        <div class="mw-references-wrap">
        <ol class="mw-references references">
        <li id="cite_note-1" data-mw-footnote-number="1">Shared reference</li>
        </ol></div>
        </body></html>
        """, "lxml")

        citations = mapper.collect_bottom_references(soup)
        used = mapper.replace_superscripts(soup, citations)

        # Both superscripts should be replaced with [^ref_1]
        body_text = soup.body.get_text()
        assert body_text.count("[^ref_1]") == 2
        # But only one entry in used dict
        assert len(used) == 1
        assert used["ref_1"].ref_count == 2

    def test_generate_footnotes(self, mapper):
        soup = BeautifulSoup("""
        <html><body>
        <p>Text<sup class="reference"><a href="#cite_note-1">[a]</a></sup>
        and<sup class="reference"><a href="#cite_note-2">[1]</a></sup>.</p>
        <div class="mw-references-wrap">
        <ol class="mw-references references">
        <li id="cite_note-1" data-mw-footnote-number="a">Note text</li>
        <li id="cite_note-2" data-mw-footnote-number="1">Ref text</li>
        </ol></div>
        </body></html>
        """, "lxml")

        citations = mapper.collect_bottom_references(soup)
        used = mapper.replace_superscripts(soup, citations)
        notes_md, refs_md = mapper.generate_footnote_definitions(used)

        # Notes are now plain text — no generated Notes section
        assert notes_md == ""
        # References still get generated
        assert "## References" in refs_md
        assert "[^ref_1]" in refs_md
        assert "Ref text" in refs_md
        # Note is NOT in used dict
        assert "note_a" not in used


class TestObsidianFormatting:
    """Test Obsidian footnote formatting helpers."""

    def test_make_footnote_ref_note(self):
        assert make_footnote_ref("a", is_note=True) == "note_a"
        assert make_footnote_ref("b", is_note=True) == "note_b"

    def test_make_footnote_ref_reference(self):
        assert make_footnote_ref("1", is_note=False) == "ref_1"
        assert make_footnote_ref("42", is_note=False) == "ref_42"

    def test_format_footnote_ref_marker(self):
        assert format_footnote_ref_marker("ref_1") == "[^ref_1]"
        assert format_footnote_ref_marker("note_a") == "[^note_a]"

    def test_format_footnote_definition(self):
        result = format_footnote_definition("ref_1", "Test content")
        assert result == "[^ref_1]: Test content"

    def test_make_footnote_ref_sanitizes_special_chars(self):
        # Special characters should be sanitized
        ref_id = make_footnote_ref("VR/Special-7", is_note=False)
        assert "/" not in ref_id
        assert ref_id.startswith("ref_")

    def test_empty_notes_section(self):
        from html2md.obsidian import format_notes_section
        assert format_notes_section([]) == ""

    def test_empty_refs_section(self):
        from html2md.obsidian import format_references_section
        assert format_references_section([]) == ""
