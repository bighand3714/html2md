"""Tests for content extraction, cleaning, and collapsible content handling."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from html2md.converter import Converter
from html2md.errors import WarningCollector
from html2md.extractor import Extractor
from html2md.strategy import resolve_strategy


WIKIPEDIA_HTML = """
<!DOCTYPE html><html><head>
<meta property="og:site_name" content="Wikipedia">
<link rel="canonical" href="https://en.wikipedia.org/wiki/Test">
</head><body>
<h1 id="firstHeading"><i>The Legend of Zelda</i> (video game)</h1>
<div id="siteSub">From Wikipedia, the free encyclopedia</div>
<div class="mw-parser-output">
  <table class="infobox ib-video-game">
    <tr><th>Release</th>
      <td>
        <div class="collapsible-list mw-collapsible mw-collapsed">
          <div><a href="#" class="mw-collapsible-toggle">show</a></div>
          <ul class="mw-collapsible-content" hidden="until-found">
            <li>JP: February 21, 1986</li>
            <li>PAL: November 15, 1987</li>
          </ul>
        </div>
      </td>
    </tr>
  </table>
  <p>Body text that is always visible.</p>
  <div hidden="until-found"><p>Collapsed section text.</p></div>
</div>
</body></html>
"""


@pytest.fixture
def strategy():
    return resolve_strategy(html=WIKIPEDIA_HTML)


@pytest.fixture
def extracted(tmp_path, strategy):
    html_path = tmp_path / "page.html"
    html_path.write_text(WIKIPEDIA_HTML, encoding="utf-8")
    return Extractor(strategy, WarningCollector()).extract(html_path)


class TestTitleExtraction:
    """Page titles must keep spaces that separate an inline tag from text."""

    def test_title_keeps_space_before_parenthesis(self, extracted):
        assert extracted.title == "The Legend of Zelda (video game)"

    def test_subtitle_extracted(self, extracted):
        assert extracted.subtitle == "From Wikipedia, the free encyclopedia"


class TestCollapsibleContent:
    """hidden="until-found" is rendered content and must be converted."""

    def test_unhide_collapsible_content_removes_attribute(self, extracted):
        soup = extracted.body_soup
        assert soup.find_all(hidden="until-found")

        removed = Extractor.unhide_collapsible_content(soup)

        assert removed >= 2
        assert soup.find_all(hidden="until-found") == []

    def test_genuinely_hidden_elements_are_left_alone(self, extracted):
        """A bare `hidden` attribute still means hidden."""
        soup = extracted.body_soup
        soup.select_one(".mw-parser-output").append(
            BeautifulSoup('<div hidden=""><p>truly hidden</p></div>', "lxml").div
        )

        Extractor.unhide_collapsible_content(soup)

        assert soup.find("div", hidden="") is not None

    def test_collapsed_rows_survive_conversion(self, extracted, strategy):
        soup = extracted.body_soup
        Extractor.unhide_collapsible_content(soup)
        main = Extractor(strategy, WarningCollector()).get_main_content(soup)

        md = Converter(strategy, Path("."), WarningCollector()).convert(main)

        assert "PAL: November 15, 1987" in md
        assert "JP: February 21, 1986" in md
        assert "Collapsed section text." in md

    def test_collapsed_rows_dropped_without_unhide(self, extracted, strategy):
        """Documents the behaviour the unhide step exists to prevent."""
        soup = extracted.body_soup
        main = Extractor(strategy, WarningCollector()).get_main_content(soup)

        md = Converter(strategy, Path("."), WarningCollector()).convert(main)

        assert "PAL: November 15, 1987" not in md
