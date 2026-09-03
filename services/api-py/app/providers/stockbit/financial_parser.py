"""High-speed parser for Stockbit financial report HTML tables into structured JSON."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

_RE_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_RE_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_RE_STRIP = re.compile(r"<[^>]+>")


class FinancialTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("td", "th"):
            self.in_cell = True
            self.current_cell = []
        elif tag == "tr":
            self.current_row = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self.in_cell = False
            self.current_row.append(" ".join(self.current_cell).strip())
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            text = data.strip()
            if text:
                self.current_cell.append(text)


def parse_financial_statement_html(html_report: str) -> dict[str, Any]:
    """Parse Stockbit html_report table into structured periods and line-item rows."""
    if not html_report:
        return {"periods": [], "line_items": []}

    rows_match = _RE_ROW.findall(html_report)
    if not rows_match:
        parser = FinancialTableParser()
        parser.feed(html_report)
        rows = parser.rows
    else:
        rows = []
        for r in rows_match:
            cells = [_RE_STRIP.sub("", c).strip() for c in _RE_CELL.findall(r)]
            if cells:
                rows.append(cells)

    if not rows:
        return {"periods": [], "line_items": []}

    # First row contains headers / period names e.g. ['In Million', 'Q1 2024', 'Q2 2024', ...]
    header_row = rows[0]
    unit_label = header_row[0] if header_row else "In Million"
    periods = header_row[1:] if len(header_row) > 1 else []

    line_items: list[dict[str, Any]] = []
    for r in rows[1:]:
        if not r:
            continue
        item_name = r[0]
        # Clean null characters or trailing dots
        item_name = item_name.replace("\x00", "").replace("...", "").strip()
        if not item_name:
            continue
        values = r[1:] if len(r) > 1 else []
        line_items.append(
            {
                "name": item_name,
                "values": values,
            }
        )

    return {
        "unit": unit_label,
        "periods": periods,
        "line_items": line_items,
    }
