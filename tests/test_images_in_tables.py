"""Tests for images rendered inside Markdown tables.

An Obsidian width constraint (``![alt|250](src)``) contains a pipe. When the
image lands in a Markdown table cell, that pipe must be backslash-escaped
(``![alt\\|250](src)``) or the table parser reads it as a column separator and
the row is torn apart.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup

from html2md.converter import Converter
from html2md.errors import WarningCollector
from html2md.strategy import resolve_strategy


def _converter(strategy_name: str = "zeldawiki") -> Converter:
    """Build a Converter with an explicit site strategy.

    Bare HTML fragments carry no site metadata, so detection cannot run.
    """
    strategy = resolve_strategy(html="<html></html>", strategy_name=strategy_name)
    return Converter(strategy, Path("."), WarningCollector())


def _convert_fragment(html: str) -> str:
    """Convert a single element from an HTML fragment to Markdown."""
    soup = BeautifulSoup(html, "lxml")
    return _converter().convert(soup.find(True))


def _unescaped_cell_pipes(row: str) -> int:
    """Count pipes that act as table column separators."""
    return len(re.findall(r"(?<!\\)\|", row))


class TestImagePipeEscapingInTables:
    """Image pipes must be escaped wherever Markdown output is a table."""

    def test_img_in_real_table_escapes_pipe(self):
        md = _convert_fragment(
            '<table><tr><td><img src="a.png" width="20" alt="Flag"></td>'
            "<td>x</td></tr></table>"
        )
        assert "![Flag\\|20](" in md
        assert "![Flag|20](" not in md

    def test_img_in_portable_infobox_escapes_pipe(self):
        """The whole portable infobox becomes a Markdown table.

        Its images have no <table> ancestor, so the escape must also trigger
        from .pi-data / .portable-infobox context.
        """
        md = _convert_fragment(
            '<aside class="portable-infobox">'
            '<div class="pi-item pi-data">'
            '<div class="pi-data-label">Release</div>'
            '<div class="pi-data-value">'
            '<img src="flag.png" width="20" alt="Japan">'
            "</div></div></aside>"
        )
        assert "![Japan\\|20](" in md
        assert "![Japan|20](" not in md

    def test_img_inside_nested_li_in_pi_data_escapes_pipe(self):
        """ZeldaWiki renders flags inside <li> nested in .pi-data-value."""
        md = _convert_fragment(
            '<aside class="portable-infobox">'
            '<div class="pi-item pi-data">'
            '<div class="pi-data-label">Release</div>'
            '<div class="pi-data-value"><ul><li>'
            '<img src="flag.png" width="20" alt="Japan">Japan'
            "</li></ul></div></div></aside>"
        )
        assert "![Japan\\|20](" in md
        assert "![Japan|20](" not in md

    def test_img_outside_table_keeps_plain_pipe(self):
        """A normal paragraph image keeps Obsidian's unescaped syntax."""
        md = _convert_fragment('<p><img src="a.png" width="256" alt="Shot"></p>')
        assert "![Shot|256](" in md
        assert "![Shot\\|256](" not in md

    def test_escaped_pipe_in_alt_is_not_double_escaped(self):
        """alt="\\|250" must not become alt="\\\\|250"."""
        md = _convert_fragment(
            '<table><tr><td><img src="a.png" width="250" alt="\\|250">'
            "</td></tr></table>"
        )
        assert "\\\\|250" not in md
        assert "![|250\\|250](" in md

    def test_nested_image_link_in_table_escapes_pipe(self):
        """Width must survive inside a linked image: [![alt\\|20](src)](href)."""
        md = _convert_fragment(
            '<table><tr><td><a href="https://x/wiki/File:Japan.png">'
            '<img src="japan.png" width="20" alt="Japan"></a></td></tr></table>'
        )
        assert "[![Japan\\|20](" in md
        assert "![Japan|20](" not in md

    def test_width_recovered_when_width_attr_missing(self):
        """SingleFile sometimes leaves the width only in the alt text."""
        md = _convert_fragment(
            '<table><tr><td><img src="a.png" alt="\\|250"></td></tr></table>'
        )
        assert md.count("250") >= 1


class TestTableRowIntegrity:
    """Every row in a converted infobox table must have the header's width."""

    INFOBOX = """
    <html><body><div class="mw-parser-output">
    <aside class="portable-infobox">
      <h2 class="pi-title">The Legend of Zelda</h2>
      <div class="pi-item pi-data">
        <div class="pi-data-label">Developer(s)</div>
        <div class="pi-data-value">Nintendo R&amp;D 4</div>
      </div>
      <div class="pi-item pi-data">
        <div class="pi-data-label">Release date(s)</div>
        <div class="pi-data-value">
          <ul class="plainlist">
            <li><img src="japan.png" width="20" alt="Japan">Japan February 21, 1986</li>
            <li><img src="usa.png" width="20" alt="United States of America">United States August 22, 1987</li>
          </ul>
        </div>
      </div>
    </aside>
    </div></body></html>
    """

    def test_infobox_rows_all_have_equal_column_count(self):
        soup = BeautifulSoup(self.INFOBOX, "lxml")
        md = _converter().convert(soup.select_one(".mw-parser-output"))

        rows = [ln for ln in md.split("\n") if ln.startswith("|")]
        assert rows, "expected a Markdown table"

        widths = {_unescaped_cell_pipes(r) for r in rows}
        assert len(widths) == 1, (
            "rows disagree on column count: "
            + repr({r: _unescaped_cell_pipes(r) for r in rows})
        )

    def test_rows_still_contain_both_flags(self):
        soup = BeautifulSoup(self.INFOBOX, "lxml")
        md = _converter().convert(soup.select_one(".mw-parser-output"))
        assert "Japan" in md
        assert "United States of America" in md
