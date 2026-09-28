"""Image/caption layout: a picture and its caption must not share one line.

Wikipedia renders the same thumbnail in two different DOM shapes:

* ``<figure typeof="mw:File/Thumb">`` with a sibling ``<figcaption>``
  (Parsoid markup) — handled by ``Converter._figure_to_md``;
* the classic ``div.thumb > div.thumbinner > .thumbimage + .thumbcaption``
  markup, plus the ``{{multiple image}}`` variant (``div.thumb.tmulti`` with
  ``.trow``/``.tsingle``). Those ``<div>``s are transparent to the converter,
  so the whole block used to collapse into a single run-on paragraph::

      Maps of [Hyrule](…)![map](…)Map of Hyrule, as seen in *Ocarina of Time*…

Infoboxes add a third shape: the caption is a *block* child of the image's
``<td>`` (``<div class="infobox-caption">``), which glued onto the image inside
the Markdown table row.

These tests pin the fixed behaviour — and, just as importantly, pin that
*inline* images (a flag icon followed by a date) keep their text on the same
line. The fragments below keep the whitespace-free markup of real Wikipedia
HTML, because stray newlines inside ``<a>`` also influence the output.
"""

from pathlib import Path

from bs4 import BeautifulSoup

from html2md.converter import Converter
from html2md.errors import WarningCollector
from html2md.strategy import resolve_strategy


def _converter(strategy_name: str = "wikipedia_en") -> Converter:
    """Build a Converter with an explicit site strategy.

    Bare HTML fragments carry no site metadata, so detection cannot run.
    """
    strategy = resolve_strategy(html="<html></html>", strategy_name=strategy_name)
    return Converter(strategy, Path("."), WarningCollector())


def _convert_fragment(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return _converter().convert(soup.find(True)).strip()


class TestInfoboxCaption:
    """The infobox caption is a block child of the image's table cell."""

    HTML = (
        '<table class="infobox"><tbody><tr>'
        '<td class="infobox-image" colspan="2">'
        '<span class="mw-default-size" typeof="mw:File/Frameless">'
        '<a class="mw-file-description" '
        'href="https://en.wikipedia.org/wiki/File:Zelda_2017.svg">'
        '<img src="https://upload.wikimedia.org/zelda.svg.png" width="290"/></a>'
        "</span>"
        '<div class="infobox-caption">Logo since 1991</div>'
        "</td></tr></tbody></table>"
    )

    def test_caption_starts_a_new_row_line(self):
        md = _convert_fragment(self.HTML)
        assert md == (
            "| [![\\|290](https://upload.wikimedia.org/zelda.svg.png)]"
            "(https://en.wikipedia.org/wiki/File:Zelda_2017.svg)"
            "<br>Logo since 1991 |\n"
            "| --- |"
        )

    def test_caption_does_not_glue_onto_the_image(self):
        assert "svg)Logo since 1991" not in _convert_fragment(self.HTML)


class TestInlineImageInCell:
    """An inline icon (flag) followed by text must stay on one line."""

    HTML = (
        '<table class="infobox"><tbody><tr><th>発売日</th><td>'
        '<span style="white-space:nowrap;"><small><sup>'
        '<span class="flagicon"><span class="mw-image-border" typeof="mw:File">'
        '<a href="https://ja.wikipedia.org/wiki/日本" title="日本">'
        '<img src="https://upload.wikimedia.org/flag.svg.png" width="25" alt="日本"/>'
        "</a></span></span> </sup></small>"
        '<span style="display:none">19860221</span>1986年2月21日'
        "</span></td></tr></tbody></table>"
    )

    def test_no_break_is_inserted_before_the_text(self):
        md = _convert_fragment(self.HTML)
        assert md == (
            "| 発売日 | [![日本\\|25](https://upload.wikimedia.org/flag.svg.png)]"
            "(https://ja.wikipedia.org/wiki/日本) 1986年2月21日 |\n"
            "| --- | --- |"
        )

    def test_nothing_glues_and_nothing_breaks(self):
        md = _convert_fragment(self.HTML)
        assert "<br>" not in md


class TestClassicThumbBlock:
    """div.thumb markup: picture and caption are sibling divs."""

    HTML = (
        '<div class="thumb tright"><div class="thumbinner" style="width:222px">'
        '<a class="image" '
        'href="https://en.wikipedia.org/wiki/File:Legend_of_Zelda_NES.PNG">'
        '<img src="https://upload.wikimedia.org/zelda_nes.png" width="250" '
        'alt="NES screenshot"/></a>'
        '<div class="thumbcaption">The original <i>The Legend of Zelda</i>, '
        "released in 1986.</div>"
        "</div></div>"
    )

    def test_image_and_caption_are_separate_blocks(self):
        assert _convert_fragment(self.HTML) == (
            "[![NES screenshot|250](https://upload.wikimedia.org/zelda_nes.png)]"
            "(https://en.wikipedia.org/wiki/File:Legend_of_Zelda_NES.PNG)\n\n"
            "The original *The Legend of Zelda*, released in 1986."
        )


class TestMultipleImageBlock:
    """{{multiple image}}: a group header plus two pictures with captions."""

    HTML = (
        '<div class="thumb tmulti floatright">'
        '<div class="thumbinner multiimageinner" style="width:204px">'
        '<div class="trow"><div class="theader">Maps of '
        '<a href="https://en.wikipedia.org/wiki/Hyrule">Hyrule</a></div></div>'
        '<div class="trow"><div class="tsingle" style="width:202px">'
        '<div class="thumbimage"><span typeof="mw:File">'
        '<a href="https://en.wikipedia.org/wiki/File:Hyrule_Ocarina_of_Time.svg">'
        '<img src="https://upload.wikimedia.org/oot.png" width="200"/></a>'
        "</span></div>"
        '<div class="thumbcaption">Map of Hyrule, as seen in '
        '<i><a href="https://en.wikipedia.org/wiki/Ocarina_of_Time">'
        "Ocarina of Time</a></i></div>"
        "</div></div>"
        '<div class="trow"><div class="tsingle" style="width:202px">'
        '<div class="thumbimage"><span typeof="mw:File">'
        '<a href="https://en.wikipedia.org/wiki/File:BotW_Map.jpg">'
        '<img src="https://upload.wikimedia.org/botw.jpg" width="200"/></a>'
        "</span></div>"
        '<div class="thumbcaption">Map of Hyrule, as seen in '
        '<i><a href="https://en.wikipedia.org/wiki/Breath_of_the_Wild">'
        "Breath of the Wild</a></i></div>"
        "</div></div>"
        "</div></div>"
    )

    def test_every_pane_is_its_own_block(self):
        assert _convert_fragment(self.HTML) == (
            "Maps of [Hyrule](https://en.wikipedia.org/wiki/Hyrule)\n\n"
            "[![|200](https://upload.wikimedia.org/oot.png)]"
            "(https://en.wikipedia.org/wiki/File:Hyrule_Ocarina_of_Time.svg)\n\n"
            "Map of Hyrule, as seen in "
            "*[Ocarina of Time](https://en.wikipedia.org/wiki/Ocarina_of_Time)*\n\n"
            "[![|200](https://upload.wikimedia.org/botw.jpg)]"
            "(https://en.wikipedia.org/wiki/File:BotW_Map.jpg)\n\n"
            "Map of Hyrule, as seen in "
            "*[Breath of the Wild](https://en.wikipedia.org/wiki/Breath_of_the_Wild)*"
        )

    def test_no_run_on_line_remains(self):
        md = _convert_fragment(self.HTML)
        assert "Hyrule)[![|200]" not in md
        assert "Ocarina of Time)*[![|200]" not in md
        assert "svg.png)](" not in md.replace("svg)](", "")


class TestFigureMarkupUnchanged:
    """Parsoid <figure> markup keeps its existing (already correct) layout."""

    HTML = (
        '<figure typeof="mw:File/Thumb">'
        '<a href="https://en.wikipedia.org/wiki/File:Rubin.png">'
        '<img src="https://upload.wikimedia.org/rubin.png" width="250" '
        'alt="Rupees"/></a>'
        "<figcaption>Rupees, the fictional currency in the series</figcaption>"
        "</figure>"
    )

    def test_image_then_caption(self):
        assert _convert_fragment(self.HTML) == (
            "[![Rupees|250](https://upload.wikimedia.org/rubin.png)]"
            "(https://en.wikipedia.org/wiki/File:Rubin.png)\n\n"
            "Rupees, the fictional currency in the series"
        )


class TestThumbInsideListItem:
    """A thumbnail that *is* a list item's content must stay in the item.

    The picture and its caption are separate blocks, so the item spans several
    lines. Without indenting the continuation the picture lands beside the
    bullet, leaving an empty "- " behind and a stray paragraph after the list.
    """

    HTML = (
        "<ul><li>"
        '<div class="thumb tright"><div class="thumbinner">'
        '<a href="https://en.wikipedia.org/wiki/File:Famicom.png">'
        '<img src="https://upload.wikimedia.org/famicom.png" width="120"/></a>'
        '<div class="thumbcaption">Family Computer</div>'
        "</div></div></li>"
        "<li>Second item</li></ul>"
    )

    def test_item_keeps_its_content(self):
        assert _convert_fragment(self.HTML) == (
            "- [![|120](https://upload.wikimedia.org/famicom.png)]"
            "(https://en.wikipedia.org/wiki/File:Famicom.png)\n\n"
            "    Family Computer\n"
            "- Second item"
        )

    def test_no_empty_bullet_is_left_behind(self):
        md = _convert_fragment(self.HTML)
        assert "- \n" not in md
        assert not md.startswith("- \n")


class TestNestedListIndentation:
    """A nested list stays nested under the item that contains it."""

    def test_nested_list_is_indented(self):
        md = _convert_fragment(
            "<ul><li>parent<ul><li>x</li><li>y</li></ul></li>"
            "<li>sibling</li></ul>"
        )
        assert md == "- parent\n\n    - x\n    - y\n- sibling"

    def test_flat_list_items_are_untouched(self):
        assert _convert_fragment(
            "<ul><li>alpha</li><li>beta</li></ul>"
        ) == "- alpha\n- beta"
