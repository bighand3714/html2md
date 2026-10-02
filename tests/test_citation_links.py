"""脚注里的站内相对链接必须绝对化，否则到了 Obsidian 里是断链。"""

from bs4 import BeautifulSoup

from html2md.citations import CitationMapper
from html2md.strategy import CitationConfig

REF_HTML = """
<div class="mw-references-wrap"><ol class="references">
<li id="cite_note-1"><a href="#cite_ref-1">^</a>
  <a href="/wiki/The_Legend_of_Zelda:_Encyclopedia">Encyclopedia</a>,
  Dark Horse Books, pg. 7.</li>
<li id="cite_note-2"><a href="#cite_ref-2">^</a>
  <a href="https://example.com/outside">Outside source</a>, 2024.</li>
</ol></div>
"""


def _text_of(mapper: CitationMapper, html: str) -> str:
    soup = BeautifulSoup(f"<html><body>{html}</body></html>", "lxml")
    refs = mapper.collect_bottom_references(soup)
    return " ".join(c.text for c in refs.values())


class TestCitationRelativeLinks:
    def test_relative_href_absolutized(self):
        mapper = CitationMapper(
            CitationConfig(
                references_container_selector=".mw-references-wrap ol.references",
                reference_item_id_prefix="cite_note-",
            ),
            base_url="https://zeldawiki.wiki",
        )
        text = _text_of(mapper, REF_HTML)
        assert "[Encyclopedia](https://zeldawiki.wiki/wiki/The_Legend_of_Zelda:_Encyclopedia)" in text

    def test_absolute_href_untouched(self):
        mapper = CitationMapper(
            CitationConfig(
                references_container_selector=".mw-references-wrap ol.references",
                reference_item_id_prefix="cite_note-",
            ),
            base_url="https://zeldawiki.wiki",
        )
        text = _text_of(mapper, REF_HTML)
        assert "[Outside source](https://example.com/outside)" in text

    def test_no_base_url_leaves_relative(self):
        """没配 base_url 时不该乱猜（保持原样）。"""
        mapper = CitationMapper(
            CitationConfig(
                references_container_selector=".mw-references-wrap ol.references",
                reference_item_id_prefix="cite_note-",
            )
        )
        text = _text_of(mapper, REF_HTML)
        assert "[Encyclopedia](/wiki/The_Legend_of_Zelda:_Encyclopedia)" in text

    def test_protocol_relative_href_gets_scheme(self):
        """`//host/path` 在 Obsidian 里会被当成相对路径，必须补上 https:。"""
        mapper = CitationMapper(
            CitationConfig(
                references_container_selector=".mw-references-wrap ol.references",
                reference_item_id_prefix="cite_note-",
            ),
            base_url="https://en.wikipedia.org",
        )
        html = REF_HTML.replace(
            "https://example.com/outside",
            "//archive.org/details/Total_Issue_002",
        )
        text = _text_of(mapper, html)
        assert "[Outside source](https://archive.org/details/Total_Issue_002)" in text
        assert "](//archive.org" not in text
