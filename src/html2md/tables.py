"""Table conversion: merged cell splitting and HTML-to-MD table conversion."""

from __future__ import annotations

import copy

from bs4 import NavigableString, Tag

from .errors import WarningCollector


class TableConverter:
    """Convert HTML tables to Markdown, handling merged cells.

    Merged cells (rowspan/colspan) are split into individual cells.
    Content is placed in the top-left cell of the original span;
    all other cells are left empty.
    """

    def __init__(self, collector: WarningCollector | None = None):
        self.collector = collector or WarningCollector()

    def split_merged_cells(self, element: Tag) -> Tag:
        """Split merged cells in all tables within the element.

        Operates on a copy of the element so the original is not mutated.

        Args:
            element: A BeautifulSoup Tag containing one or more tables.

        Returns:
            The element with all tables having their merged cells split.
        """
        tables = element.find_all("table")
        for table in tables:
            self._split_table(table)
        return element

    def _split_table(self, table: Tag) -> None:
        """Split all merged cells in a single table (in-place)."""
        rows = table.find_all("tr")
        if not rows:
            return

        # Track how many cells each row has and pending rowspan fillers
        max_cols = self._calculate_max_cols(rows)

        for row_idx, row in enumerate(rows):
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells:
                continue

            # Process colspan and track pending rowspan fillers for future rows
            new_cells = []
            for cell in cells:
                colspan = int(cell.get("colspan", 1))
                rowspan = int(cell.get("rowspan", 1))

                # Remove span attributes from current cell
                if "rowspan" in cell.attrs:
                    del cell["rowspan"]
                if "colspan" in cell.attrs:
                    del cell["colspan"]

                # Keep the original cell as the first (top-left) cell
                new_cells.append(cell)

                # For colspan > 1: insert empty cells in the current row
                for _ in range(colspan - 1):
                    empty_td = Tag(name=cell.name)
                    new_cells.append(empty_td)

                # For rowspan > 1: insert empty cells in subsequent rows
                for offset in range(1, rowspan):
                    target_row_idx = row_idx + offset
                    if target_row_idx >= len(rows):
                        break
                    target_row = rows[target_row_idx]

                    # Calculate position: count cells before this one
                    # (minus the colspan expansion)
                    position = len(new_cells) - 1 - (colspan - 1)
                    target_cells = list(target_row.find_all(
                        ["td", "th"], recursive=False
                    ))

                    # Create empty cell and insert at correct position
                    empty_td = Tag(name=cell.name)
                    if position < len(target_cells):
                        target_cells[position].insert_before(empty_td)
                    else:
                        # Append to end of row
                        target_row.append(empty_td)

            # Replace the row's cells with new_cells (which includes
            # colspan filler cells)
            # First, remove all existing td/th from the row
            for old_cell in row.find_all(["td", "th"], recursive=False):
                old_cell.extract()
            # Then append the new cells in order
            for new_cell in new_cells:
                row.append(new_cell)

    def _calculate_max_cols(self, rows: list[Tag]) -> int:
        """Calculate the maximum number of columns across all rows."""
        max_cols = 0
        for row in rows:
            cols = 0
            for cell in row.find_all(["td", "th"], recursive=False):
                colspan = int(cell.get("colspan", 1))
                cols += colspan
            max_cols = max(max_cols, cols)
        return max_cols

    def convert(self, table: Tag, is_infobox: bool = False) -> str:
        """Convert a single HTML table to Markdown format.

        Args:
            table: The <table> Tag to convert.
            is_infobox: If True, the table is treated as an infobox.

        Returns:
            Markdown table string.
        """
        rows = table.find_all("tr")
        if not rows:
            return ""

        # Build the grid
        grid: list[list[str]] = []
        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells:
                # Skip rows with only <th> inside <thead> but no data
                continue
            row_data: list[str] = []
            for cell in cells:
                row_data.append(self._cell_to_text(cell))
            if row_data:
                grid.append(row_data)

        if not grid:
            return ""

        # Normalize row lengths
        max_cols = max(len(row) for row in grid)
        for row in grid:
            while len(row) < max_cols:
                row.append("")

        # Build Markdown table
        lines: list[str] = []
        for i, row in enumerate(grid):
            lines.append("| " + " | ".join(row) + " |")
            if i == 0:
                # Separator row
                lines.append("| " + " | ".join(["---"] * max_cols) + " |")

        return "\n".join(lines)

    def _cell_to_text(self, cell: Tag) -> str:
        """Extract plain text from a table cell, handling line breaks."""
        # Convert <br> to line breaks
        text_parts = []
        for child in cell.children:
            if isinstance(child, NavigableString):
                text_parts.append(str(child))
            elif child.name == "br":
                text_parts.append("<br>")
            else:
                text_parts.append(child.get_text(strip=True))

        text = "".join(text_parts).strip()
        # Replace <br> markers with actual line breaks
        text = text.replace("<br>", "<br>")
        return text
