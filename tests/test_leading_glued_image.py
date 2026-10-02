"""段首图片粘字：`<p><img>文字</p>` 必须补换行；图标+标签/多图并排不能动。"""

from bs4 import BeautifulSoup

from html2md.converter import Converter, split_leading_glued_image
from html2md.strategy import SiteStrategy


def _convert(fragment: str) -> str:
    html = f'<div class="mw-parser-output">{fragment}</div>'
    strategy = SiteStrategy(
        name="t",
        site_id="t",
        content=type(SiteStrategy().content)(
            main_selector=".mw-parser-output", title_selector="h1"
        ),
    )
    soup = BeautifulSoup(html, "lxml")
    return Converter(strategy).convert(soup.select_one(".mw-parser-output")).strip()


class TestGluedLeadingImageGetsNewline:
    def test_unit_plain_image(self):
        assert split_leading_glued_image("![](candle.png)Once you enter") == (
            "![](candle.png)\n\nOnce you enter"
        )

    def test_unit_linked_image(self):
        assert split_leading_glued_image("[![](a.png)](a.png)Night falls.") == (
            "[![](a.png)](a.png)\n\nNight falls."
        )

    def test_unit_cjk_text(self):
        assert split_leading_glued_image("![](a.png)点亮房间") == "![](a.png)\n\n点亮房间"

    def test_paragraph_renders_with_blank_line(self):
        md = _convert('<p><img src="candle.png" align="right">Once you enter.</p>')
        assert md == "![](candle.png)\n\nOnce you enter."

    def test_paragraph_cjk(self):
        md = _convert('<p><img src="key.png">拿取钥匙。</p>')
        assert md == "![](key.png)\n\n拿取钥匙。"

    def test_already_separated_is_untouched(self):
        md = _convert('<p><img src="a.png"> <br>下文</p>')
        assert "![](" in md and "下文" in md


class TestDeliberatelyUntouched:
    """这些相邻是有意为之。"""

    def test_icon_then_link_label(self):
        """ZeldaWiki 快捷导航：可点图标 + 标签。"""
        md = _convert(
            '<p><a href="/wiki/Items"><img src="icon.png"></a>[Items](/wiki/Items)</p>'
        )
        assert md == "[![](icon.png)](/wiki/Items)[Items](/wiki/Items)"

    def test_multiple_images_in_a_row(self):
        md = _convert('<p><img src="a.png"><img src="b.png"></p>')
        assert md == "![](a.png)![](b.png)"

    def test_inline_icon_mid_sentence(self):
        md = _convert('<p>按 <img src="key.png"> 键继续</p>')
        assert "按键继续" in md.replace(" ", "") or "按" in md

    def test_inline_icon_in_table_cell(self):
        md = _convert(
            "<table><tr><td>"
            '<a href="/wiki/日本"><img src="flag.png"></a> 1986年2月21日'
            "</td></tr></table>"
        )
        assert "<br>" not in md
