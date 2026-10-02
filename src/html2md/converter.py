"""HTML to Markdown core converter.

Recursively walks the BeautifulSoup DOM tree and emits Markdown.
Handles headings, paragraphs, lists, links, images, tables,
emphasis, and inline formatting.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import Comment, NavigableString, Tag

from .errors import WarningCollector
from .obsidian import separated_inline_text
from .strategy import SiteStrategy


_IMG_MD = r"!\[[^\]]*\]\([^)]*\)"
_LINKED_IMG_MD = r"\[" + _IMG_MD + r"\]\([^)]*\)"
# 段首图片后紧跟字母/汉字。刻意排除 `[` 与 `!`：前者是"可点图标 + 标签"
# （ZeldaWiki 快捷导航、姊妹项目框），后者是"多图并排"，两者都该保持相邻。
_LEADING_GLUED_IMAGE = re.compile(
    rf"^(?:{_LINKED_IMG_MD}|{_IMG_MD})(?=[A-Za-z\u4e00-\u9fff])"
)


def split_leading_glued_image(text: str) -> str:
    """段首图片与紧随其后的正文粘在一起时，在两者之间补一个空行。

    源页常见 `<p><img src="candle.png" align="right">文字…</p>`：小图标在段首、
    后面直接接正文。图片在 Markdown 里是行内元素，不补换行就会粘在第一个字上，
    渲染成 `![](icon.png)文字`。

    只在"图片位于段首 **且** 紧跟字母或汉字"时生效，因此：
      - `[![](icon)](file)[标签](url)` 图标 + 标签 → 不动
      - `![](a.png)![](b.png)` 多图并排 → 不动
      - 正文中间的行内图标（图片不在段首）→ 不动
    """
    m = _LEADING_GLUED_IMAGE.match(text)
    if not m:
        return text
    return f"{m.group(0)}\n\n{text[m.end():]}"


class Converter:
    """Convert cleaned HTML DOM to Markdown text."""

    # Tags treated as block-level (force surrounding newlines)
    BLOCK_TAGS = {
        "p", "div", "section", "article", "header", "footer",
        "blockquote", "pre", "hr", "figure", "figcaption",
        "ul", "ol", "dl", "table",
    }

    # Tags treated as inline (no extra newlines)
    INLINE_TAGS = {
        "span", "a", "b", "strong", "i", "em", "u", "s", "del",
        "code", "tt", "kbd", "sub", "sup", "small", "mark",
        "abbr", "cite", "q", "br",
    }

    # Tags to skip entirely (their children are processed inline)
    SKIP_TAGS = {"span", "div", "ruby"}

    # Block-level tags that occupy their own line inside a table cell. A block
    # child must be separated from whatever precedes it in the cell, otherwise
    # Wikipedia's infobox caption glues onto the image above it:
    #   "[![](cover.jpg)](File:cover.jpg)North American cover art"
    CELL_BLOCK_TAGS = {
        "div", "p", "figcaption", "figure", "section", "aside", "blockquote",
    }

    # MediaWiki thumbnail wrappers: both the classic "thumb" markup and the
    # multiple-image template ({{multiple image}}) nest the media in <div>s,
    # with the image in .thumbimage and its caption in a sibling .thumbcaption.
    THUMB_BLOCK_CLASSES = {"thumb", "tmulti", "thumbinner", "multiimageinner"}
    THUMB_CONTAINER_CLASSES = THUMB_BLOCK_CLASSES | {"trow", "tsingle"}
    THUMB_CAPTION_CLASSES = {"thumbcaption", "theader"}

    def __init__(
        self,
        strategy: SiteStrategy,
        output_dir: Path | None = None,
        collector: WarningCollector | None = None,
    ):
        self.strategy = strategy
        self.output_dir = output_dir or Path(".")
        self.collector = collector or WarningCollector()
        self._heading_offset = strategy.elements.heading_offset
        self._base_url = strategy.links.base_url

    def convert(self, element: Tag) -> str:
        """Convert an HTML element and its children to Markdown.

        Args:
            element: A BeautifulSoup Tag to convert.

        Returns:
            Markdown string.
        """
        return self._convert_element(element)

    def _convert_element(self, element: Tag | NavigableString) -> str:
        """Recursively convert any node to Markdown."""
        if isinstance(element, Comment):
            return ""
        if isinstance(element, NavigableString):
            return self._text_to_md(str(element))

        tag_name = element.name.lower() if element.name else ""

        # Skip hidden elements
        if element.get("hidden") or "display:none" in element.get("style", ""):
            return ""

        # Dispatch by tag name
        handlers = {
            "h1": self._heading_to_md,
            "h2": self._heading_to_md,
            "h3": self._heading_to_md,
            "h4": self._heading_to_md,
            "h5": self._heading_to_md,
            "h6": self._heading_to_md,
            "p": self._para_to_md,
            "br": self._br_to_md,
            "hr": self._hr_to_md,
            "ul": self._list_to_md,
            "ol": self._list_to_md,
            "li": self._li_to_md,
            "a": self._link_to_md,
            "img": self._image_to_md,
            "b": lambda e: f"**{self._children_text(e)}**",
            "strong": lambda e: f"**{self._children_text(e)}**",
            "i": lambda e: f"*{self._children_text(e)}*",
            "em": lambda e: f"*{self._children_text(e)}*",
            "s": lambda e: f"~~{self._children_text(e)}~~",
            "del": lambda e: f"~~{self._children_text(e)}~~",
            "code": self._code_to_md,
            "pre": self._pre_to_md,
            "blockquote": self._blockquote_to_md,
            "figure": self._figure_to_md,
            "figcaption": lambda e: f"\n*{self._children_text(e)}*\n",
            "table": self._table_to_md,
            "aside": self._infobox_to_md,
            "rt": lambda e: "" if "katakana-terminator-rt" in e.get("class", []) or not e.get_text(strip=True) else f"({self._children_text(e)})",
            "rp": lambda e: "",
        }

        # Check for dialogue boxes (e.g. Nintendo interview / Iwata Asks)
        if tag_name == "div" and "int-box" in element.get("class", []):
            return self._int_box_to_md(element)

        # Check for MediaWiki thumbnail blocks (classic "thumb" markup and the
        # multiple-image template) — their images and captions must become
        # separate lines instead of one run-on paragraph.
        if tag_name == "div" and self._is_thumb_block(element):
            return self._thumb_to_md(element)

        handler = handlers.get(tag_name)
        if handler:
            return handler(element)

        # Unknown tags: recurse children
        if tag_name in self.SKIP_TAGS:
            return self._children_text(element)
        return self._children_text(element)

    # ------------------------------------------------------------------
    # Heading
    # ------------------------------------------------------------------

    def _heading_to_md(self, element: Tag) -> str:
        """Convert h1-h6 to Markdown heading with level offset."""
        level = int(element.name[1]) + self._heading_offset
        level = min(level, 6)  # Markdown only supports h1-h6
        img = element.find("img")
        if img and not element.get_text(strip=True):
            alt = img.get("alt", "").strip()
            if alt:
                return f"\n\n{'#' * level} {alt}\n\n"
        text = " ".join(self._children_text(element).split())
        return f"\n\n{'#' * level} {text}\n\n"

    def _int_box_to_md(self, element: Tag) -> str:
        """Convert an interview dialogue box (<div class='int-box'>) to Markdown."""
        name_div = element.find("div", class_="int-name")
        text_div = element.find("div", class_="int-text")
        speaker = name_div.get_text(strip=True) if name_div else ""

        notes = []
        if text_div:
            for nb in text_div.find_all("div", class_="notes-box"):
                num_tag = nb.find("div", class_="notes-num")
                txt_tag = nb.find("div", class_="notes-text")
                num = num_tag.get_text(strip=True) if num_tag else ""
                txt = self._children_text(txt_tag).strip() if txt_tag else ""
                notes.append(f"*{num} {txt}*")
                nb.decompose()

        speech = self._children_text(text_div).strip() if text_div else ""
        speech = re.sub(r'[ \t]*\n[ \t]*', '\n', speech)
        speech = re.sub(r'\n{2,}', '\n', speech)

        res = []
        if speaker and speech:
            res.append(f"**{speaker}：** {speech}")
        elif speech:
            res.append(speech)

        for n in notes:
            res.append(n)

        if not res:
            return ""
        return "\n\n" + "\n\n".join(res) + "\n\n"

    # ------------------------------------------------------------------
    # Paragraph
    # ------------------------------------------------------------------

    def _para_to_md(self, element: Tag) -> str:
        """Convert <p> to Markdown paragraph."""
        text = self._children_text(element)
        # Normalize horizontal whitespace (spaces, tabs) but preserve
        # newlines from <br> elements so line breaks survive inside
        # paragraphs (important for infobox table cells).
        text = re.sub(r'[ \t\f\r]+', ' ', text)
        # Remove spaces around newlines
        text = re.sub(r' *\n *', '\n', text)
        # Collapse multiple newlines into one
        text = re.sub(r'\n{2,}', '\n', text)
        text = text.strip()
        if not text:
            return ""
        # 段首图片若与紧随其后的正文粘在一起，补一个换行（必须放在上面的
        # 空白规整之后，否则 \n\n 又会被折叠掉）
        text = split_leading_glued_image(text)
        return f"\n\n{text}\n\n"

    # ------------------------------------------------------------------
    # Line breaks and horizontal rules
    # ------------------------------------------------------------------

    def _br_to_md(self, element: Tag) -> str:
        if self._in_table(element):
            return "<br>"
        return "\n"

    def _hr_to_md(self, element: Tag) -> str:
        return "\n\n---\n\n"

    # ------------------------------------------------------------------
    # Lists
    # ------------------------------------------------------------------

    def _list_to_md(self, element: Tag) -> str:
        """Convert <ul>/<ol> to Markdown list."""
        items = element.find_all("li", recursive=False)
        if not items:
            return ""

        is_ordered = element.name == "ol"
        lines: list[str] = []

        # Check for Notes group (lower-alpha) — use letter labels
        group = element.get("data-mw-group", "")
        is_notes_list = group == "lower-alpha"

        for i, li in enumerate(items):
            if is_notes_list:
                # Letter labels: a, b, c, ...
                letter = chr(ord("a") + i) if i < 26 else str(i)
                prefix = f"{letter}. "
            elif is_ordered:
                prefix = f"{i + 1}. "
            else:
                prefix = "- "
            text = self._indent_item_content(self._children_text(li), len(prefix))
            lines.append(f"{prefix}{text}")

        return "\n\n" + "\n".join(lines) + "\n\n"

    @staticmethod
    def _indent_item_content(text: str, prefix_width: int) -> str:
        """Keep a list item's block content *inside* the item.

        An <li> can hold block content: a thumbnail block (picture +
        caption), a nested list, a second paragraph. Markdown only keeps such
        content inside the item when every following line is indented to the
        item's content column. Indented wrongly, the picture lands *beside* the
        bullet — leaving an empty "- " behind and a stray paragraph after the
        list.
        """
        lines = text.strip("\n").split("\n")
        if len(lines) == 1:
            return lines[0].strip()
        pad = " " * (prefix_width + 2)
        continuation = [pad + line if line.strip() else "" for line in lines[1:]]
        return "\n".join([lines[0].strip(), *continuation])

    def _li_to_md(self, element: Tag) -> str:
        """Convert <li> text (used when li is processed via _list_to_md)."""
        return self._children_text(element)

    # ------------------------------------------------------------------
    # Links and images
    # ------------------------------------------------------------------

    def _link_to_md(self, element: Tag) -> str:
        """Convert <a> to [text](url). Handles image links."""
        href = element.get("href", "")
        if not href:
            return self._children_text(element)

        # Resolve relative URLs
        if self._base_url and not href.startswith(("http://", "https://", "#", "mailto:")):
            href = urljoin(self._base_url, href)

        # Check if this link contains an image
        img = element.find("img")
        if img and len(list(element.children)) == 1:
            # Single image link: [![](src)](href)
            src = img.get("src", "")
            alt = img.get("alt", "")
            # Resolve relative URLs for images inside links
            if self._base_url and src and not src.startswith(("http://", "https://", "data:", "img/")):
                src = urljoin(self._base_url, src)
            img_md = self._render_img_markdown(img, src, alt)
            return f"[{img_md}]({href})"

        text = self._children_text(element)
        if not text:
            text = href

        # Strip surrounding brackets from link text
        # (Fandom wraps "[source]" links in literal brackets)
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]

        return f"[{text}]({href})"

    def _infer_image_width(self, element: Tag, src: str) -> str:
        """Infer an appropriate display width for an image in Obsidian syntax.

        Sources of width information:
        1. Explicit HTML width attribute on <img> (e.g. Wikipedia/Wiki pages).
        2. Table cells (e.g. Damage_4.gif heart icons) -> 16px.
        3. CSS grid / column container classes from walkthrough cards:
           - .scrn.cols-2 or .outwrap -> 360px (side-by-side screenshots)
           - .md-4, .sm-8 in .wt-row -> 320px (room step screenshots)
           - .md-2, .sm-4 in .wt-row:
               - Item icon -> 40px
               - Mini-map -> 100px
               - Default -> 80px
           - .sm-3 in .wt-row -> 60px (enemy sprite icons)
           - Large map banners -> 680px
        """
        # 1. Direct width attribute
        width = element.get("width", "")
        if width:
            clean_w = str(width).replace("px", "").strip()
            if clean_w.isdigit():
                return clean_w

        # 2. Heart icon in table or anywhere
        if "Damage_4" in src or element.find_parent("td") or element.find_parent("th"):
            return "16"

        # 3. Contextual inferencing from parent layout classes
        p = element.parent
        parent_classes: list[str] = []
        depth = 0
        while p and p.name not in ("body", "[document]") and depth < 6:
            cls = p.get("class", [])
            if isinstance(cls, list):
                parent_classes.extend(cls)
            elif isinstance(cls, str):
                parent_classes.extend(cls.split())
            p = p.parent
            depth += 1

        p_classes_set = set(parent_classes)

        # Side-by-side screenshots (e.g. .scrn.cols-2 or .outwrap)
        if "cols-2" in p_classes_set or "outwrap" in p_classes_set:
            return "360"

        # Room step screenshots (inside .md-4 or .sm-8 in .wt-row)
        if any(c in p_classes_set for c in ("md-4", "sm-8")):
            return "320"

        # Left column in step card: mini-maps or item icons (.md-2 or .sm-4)
        if any(c in p_classes_set for c in ("md-2", "sm-4")):
            if "Item" in src or "Items" in src:
                return "40"
            if "Map" in src or "EagleMap" in src or "DMMap" in src:
                return "100"
            return "80"

        # Enemy icons list in step card (.sm-3)
        if "sm-3" in p_classes_set:
            return "60"

        # Large map banners
        if any(k in src for k in ("Map-1", "Eagle-Map", "Death-Mountain-Map")):
            return "680"

        return ""

    def _render_img_markdown(self, img_tag: Tag, src: str, alt: str) -> str:
        """Render image markdown with appropriate width constraint.

        Inside a Markdown table cell the width pipe must be backslash-escaped
        (``\\|``), otherwise the table parser reads it as a column separator
        and the row is ripped apart. "Inside a table" means the image ends up
        in a Markdown table, which covers three sources:

        1. a real ``<table>``,
        2. a ``.pi-data`` cell of a portable infobox,
        3. anything inside an ``aside.portable-infobox`` — the whole infobox
           is emitted as Markdown tables, so even non-``.pi-data`` images
           inside it need escaping.
        """
        width = self._clean_width(self._infer_image_width(img_tag, src))
        in_table = self._renders_into_table(img_tag)
        pipe = "\\|" if in_table else "|"

        # An escaped pipe in the alt text would double-escape to "\\|", which
        # leaks a literal backslash into the rendered image label.
        alt = alt.replace("\\|", "|")

        if width:
            return f"![{alt}{pipe}{width}]({src})"
        return f"![{alt}]({src})"

    @staticmethod
    def _clean_width(width: str) -> str:
        """Return the width constraint, recovering it from the alt text.

        SingleFile saves put image widths in a ``\\|``-joined alt attribute
        (e.g. ``alt="\\|250"``) alongside a ``width="250"`` attribute. If the
        alt is all that survived, use it so Obsidian still sizes the image.
        """
        w = str(width).strip()
        if w.isdigit() and w != "0":
            return w
        return ""

    @staticmethod
    def _renders_into_table(element: Tag) -> bool:
        """Whether this element's Markdown lands inside a Markdown table."""
        p = element.parent
        while p is not None:
            if p.name == "table":
                return True
            classes = p.get("class") or []
            if "pi-data" in classes or "portable-infobox" in classes:
                return True
            p = p.parent
        return False

    def _image_to_md(self, element: Tag) -> str:
        """Convert <img> to ![](url).

        Applies width constraints using Obsidian's |WIDTH syntax.
        Image markdown is inline by nature; block-level spacing is
        handled by the parent handler (_figure_to_md, _para_to_md).
        """
        src = element.get("src", "")
        alt = element.get("alt", "")

        if not src:
            return ""

        # Resolve relative URLs for images
        if self._base_url and not src.startswith(("http://", "https://", "data:", "img/")):
            src = urljoin(self._base_url, src)

        return self._render_img_markdown(element, src, alt)

    # ------------------------------------------------------------------
    # Code blocks
    # ------------------------------------------------------------------

    def _code_to_md(self, element: Tag) -> str:
        text = element.get_text()
        return f"`{text}`"

    def _pre_to_md(self, element: Tag) -> str:
        code = element.find("code")
        lang = code.get("class", [""])[0].replace("language-", "") if code else ""
        text = element.get_text()
        return f"\n\n```{lang}\n{text}\n```\n\n"

    # ------------------------------------------------------------------
    # Blockquote
    # ------------------------------------------------------------------

    def _blockquote_to_md(self, element: Tag) -> str:
        lines = self._children_text(element).strip().split("\n")
        quoted = "\n".join(f"> {line}" for line in lines)
        return f"\n\n{quoted}\n\n"

    # ------------------------------------------------------------------
    # Figure
    # ------------------------------------------------------------------

    def _figure_to_md(self, element: Tag) -> str:
        """Convert <figure> containing <img> and <figcaption>.

        Figures without an <img> (audio players, video, metadata)
        are skipped — they have no meaningful Markdown equivalent.
        """
        if not element.find("img"):
            return ""
        parts: list[str] = []
        for child in element.children:
            if isinstance(child, Tag) and child.name == "img":
                parts.append(self._image_to_md(child))
            elif isinstance(child, Tag) and child.name == "figcaption":
                parts.append(self._figcaption_to_md(child))
            else:
                result = self._convert_element(child)
                if result.strip():
                    parts.append(result)
        return "\n\n" + "\n\n".join(parts) + "\n\n"

    def _figcaption_to_md(self, element: Tag) -> str:
        # Remove Fandom info-icon links (file page icons) — decorative,
        # the parent figure image already links to the full-size CDN URL.
        for icon in element.select("a.info-icon"):
            icon.decompose()
        return self._children_text(element).strip()

    # ------------------------------------------------------------------
    # Thumbnails (classic "thumb" markup, multiple-image template)
    # ------------------------------------------------------------------

    def _is_thumb_block(self, element: Tag) -> bool:
        """Whether a <div> is the wrapper of a thumbnail/multi-image block."""
        classes = element.get("class") or []
        return bool(self.THUMB_BLOCK_CLASSES.intersection(classes))

    def _thumb_to_md(self, element: Tag) -> str:
        """Convert a thumbnail block so image and caption get their own lines.

        <figure typeof="mw:File/Thumb"> is handled by _figure_to_md, but pages
        rendered without Parsoid (and the {{multiple image}} template) nest the
        media one level deeper::

            div.thumb[.tmulti] > div.thumbinner > div.trow > div.tsingle
                > div.thumbimage   (the picture)
                > div.thumbcaption (its caption, a sibling <div>)

        Those <div>s are transparent to this converter, so the whole block used
        to collapse into a single run-on paragraph::

            Maps of [Hyrule](…)![map](…)Map of Hyrule, as seen in *Ocarina of
            Time*![map2](…)Map of Hyrule, as seen in *Breath of the Wild* (…)

        Emitting every pane (group header, picture, caption) as its own block
        restores the layout, matching _figure_to_md's output.
        """
        parts = self._thumb_parts(element)
        if not parts:
            return ""
        return "\n\n" + "\n\n".join(parts) + "\n\n"

    def _thumb_parts(self, element: Tag) -> list[str]:
        """Collect, in document order, the visual blocks of a thumbnail.

        Structural wrappers (.thumb, .tmulti, .thumbinner, .trow, .tsingle)
        are descended into; everything else — .thumbimage, .thumbcaption,
        .theader, or an unexpected element — becomes one block of its own.
        """
        parts: list[str] = []
        for child in element.children:
            if not isinstance(child, Tag) or isinstance(child, Comment):
                continue
            if child.name == "br":
                continue

            classes = set(child.get("class") or [])
            if classes & self.THUMB_CAPTION_CLASSES:
                caption = self._figcaption_to_md(child)
                if caption:
                    parts.append(caption)
                continue
            if classes & self.THUMB_CONTAINER_CLASSES:
                parts.extend(self._thumb_parts(child))
                continue

            rendered = self._convert_element(child).strip()
            if rendered:
                parts.append(rendered)
        return parts

    # ------------------------------------------------------------------
    # Tables (delegates to TableConverter)
    # ------------------------------------------------------------------

    def _table_to_md(self, element: Tag) -> str:
        """Convert <table> to Markdown table.

        Delegates to TableConverter for complex processing.
        For simple fallback, generates a basic Markdown table.
        """
        # Check if this table has already been processed by TableConverter
        # (merged cells split). If not, do a basic conversion.
        rows = element.find_all("tr")
        if not rows:
            return ""

        grid: list[list[str]] = []
        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_data = [self._table_cell_text(cell) for cell in cells]
            grid.append(row_data)

        if not grid:
            return ""

        # Normalize columns
        max_cols = max(len(r) for r in grid)
        for r in grid:
            while len(r) < max_cols:
                r.append("")

        lines: list[str] = []
        for i, r in enumerate(grid):
            lines.append("| " + " | ".join(r) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")

        return "\n\n" + "\n".join(lines) + "\n\n"

    # ------------------------------------------------------------------
    # Table cell text (preserves <br> for inline line breaks)
    # ------------------------------------------------------------------

    def _table_cell_text(self, element: Tag) -> str:
        """Extract cell content, converting <br> and nested newlines
        to MD-compatible inline line breaks."""
        parts: list[str] = []
        has_content = False
        for child in element.children:
            if isinstance(child, NavigableString):
                chunk = str(child)
            elif child.name == "br":
                chunk = "<br>"
            else:
                chunk = self._convert_element(child)
                # A block-level child (Wikipedia's <div class="infobox-caption">,
                # <p>, <figcaption>, ...) is its own line inside the cell. Emit a
                # break before it, or it runs into the image above:
                #   "[![](cover.jpg)](File:cover.jpg)North American cover art"
                # Children that already open with a blank line (figure, list)
                # bring their own break, so they are left untouched.
                if (
                    chunk.strip()
                    and has_content
                    and child.name in self.CELL_BLOCK_TAGS
                    and not chunk.startswith("\n")
                ):
                    parts.append("<br>")
            parts.append(chunk)
            if chunk.strip():
                has_content = True
        text = "".join(parts).strip()
        # Convert newlines from nested elements (ul/li etc.) to <br>
        text = text.replace("\n", "<br>")
        # Collapse whitespace but preserve <br> tags
        text = " ".join(text.split())
        # Clean up whitespace around <br> tags
        text = text.replace(" <br>", "<br>").replace("<br> ", "<br>")
        return text

    # ------------------------------------------------------------------
    # Infobox (Fandom/ZeldaWiki portable infobox)
    # ------------------------------------------------------------------

    def _infobox_to_md(self, element: Tag) -> str:
        """Convert aside.portable-infobox to Markdown tables.

        Fandom's infobox is an <aside> containing a title, tabbed image
        gallery, and groups of key-value rows. Each group becomes a
        small table; images are extracted inline.
        """
        if "portable-infobox" not in (element.get("class") or []):
            return self._children_text(element)

        parts: list[str] = []

        # Extract all tab images as linked Markdown.
        # Base64 placeholders are replaced with CDN thumbnail URLs
        # derived from the parent <a> href.
        for img in element.select("img.pi-image-thumbnail"):
            alt = img.get("alt", "")
            parent_a = img.find_parent("a")
            if parent_a and parent_a.get("href"):
                href = parent_a["href"]
                # Derive CDN thumbnail URL from full image URL
                parts.append(
                    f"[![{alt}]({self._thumbnail_url(href)})]({href})"
                )
            else:
                parts.append(f"![{alt}]({img.get('src', '')})")

        # Top-level key-value rows (not inside a .pi-group)
        direct_rows: list[tuple[str, str]] = []
        for data in element.select(":scope > .pi-data"):
            label_el = data.select_one(".pi-data-label")
            value_el = data.select_one(".pi-data-value")
            label = separated_inline_text(label_el) if label_el else ""
            value = self._table_cell_text(value_el).strip() if value_el else ""
            if label or value:
                direct_rows.append((label, value))
        if direct_rows:
            parts.append(self._infobox_table(None, direct_rows))

        # Grouped key-value rows
        for group in element.select(".pi-group"):
            header = group.select_one(".pi-header")
            header_text = separated_inline_text(header) if header else ""

            rows: list[tuple[str, str]] = []
            for data in group.select(".pi-data"):
                label_el = data.select_one(".pi-data-label")
                value_el = data.select_one(".pi-data-value")
                label = separated_inline_text(label_el) if label_el else ""
                value = self._table_cell_text(value_el).strip() if value_el else ""
                if label or value:
                    rows.append((label, value))

            if rows:
                parts.append(self._infobox_table(header_text, rows))

        return "".join(parts)

    def _infobox_table(
        self, header: str | None, rows: list[tuple[str, str]]
    ) -> str:
        """Build a Markdown table for an infobox section."""
        lines: list[str] = []
        if header:
            lines.append(f"| **{header}** | |")
        else:
            lines.append("| | |")
        lines.append("|---|---|")
        for label, value in rows:
            lines.append(f"| {label} | {value} |")
        return "\n\n" + "\n".join(lines) + "\n\n"

    @staticmethod
    def _thumbnail_url(full_url: str, width: int = 250) -> str:
        """Derive a Fandom CDN thumbnail URL from a full image URL.

        Inserts /scale-to-width-down/{width} before the query string.
        E.g. .../revision/latest?cb=... → .../revision/latest/scale-to-width-down/250?cb=...
        """
        if "static.wikia.nocookie.net" not in full_url:
            return full_url
        if "/revision/latest" in full_url:
            return full_url.replace(
                "/revision/latest",
                f"/revision/latest/scale-to-width-down/{width}",
            )
        return full_url

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _in_table(element: Tag) -> bool:
        """Check if an element is inside a table cell (<td>, <th>,
        or Fandom infobox .pi-data)."""
        p = element.parent
        while p:
            if p.name in ("td", "th"):
                return True
            if "pi-data" in (p.get("class") or []):
                return True
            p = p.parent
        return False

    def _children_text(self, element: Tag) -> str:
        """Recursively convert all children to Markdown and join."""
        parts: list[str] = []
        for child in element.children:
            result = self._convert_element(child)
            parts.append(result)
        # Join and normalize: single-space between words, preserve
        # exactly one space across element boundaries
        joined = "".join(parts)
        return joined

    def _text_to_md(self, text: str) -> str:
        """Keep text as-is for inline context; block-level handlers
        do their own whitespace normalization."""
        return text
