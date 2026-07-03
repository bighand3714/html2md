"""Tests for table conversion and merged cell splitting."""

from bs4 import BeautifulSoup

from html2md.tables import TableConverter


class TestTableConverter:
    """Test TableConverter merged cell splitting and MD conversion."""

    def test_split_rowspan(self):
        html = """
        <table>
        <tr><td rowspan="2">A</td><td>B</td></tr>
        <tr><td>C</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        converter = TableConverter()
        converter.split_merged_cells(soup)

        rows = soup.find_all("tr")
        assert len(rows) == 2
        # First row: A and B (A no longer has rowspan)
        row1_cells = rows[0].find_all("td")
        assert len(row1_cells) == 2
        assert row1_cells[0].get_text(strip=True) == "A"
        assert row1_cells[0].get("rowspan") is None
        # Second row: empty td (from split) and C
        row2_cells = rows[1].find_all("td")
        assert len(row2_cells) >= 2

    def test_split_colspan(self):
        html = """
        <table>
        <tr><td colspan="2">A</td><td>B</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        converter = TableConverter()
        converter.split_merged_cells(soup)

        row1_cells = soup.find_all("td")
        # After split: A (original, colspan removed) + empty + B
        assert len(row1_cells) == 3
        assert row1_cells[0].get_text(strip=True) == "A"
        assert row1_cells[0].get("colspan") is None
        # The second cell should be empty (created from colspan split)
        assert row1_cells[1].get_text(strip=True) == ""

    def test_convert_simple_table(self):
        html = """
        <table>
        <tr><th>Name</th><th>Value</th></tr>
        <tr><td>X</td><td>10</td></tr>
        <tr><td>Y</td><td>20</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table_tag = soup.find("table")
        converter = TableConverter()
        result = converter.convert(table_tag)

        assert "| Name | Value |" in result
        assert "| --- | --- |" in result
        assert "| X | 10 |" in result
        assert "| Y | 20 |" in result
