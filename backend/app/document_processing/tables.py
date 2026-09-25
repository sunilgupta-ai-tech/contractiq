"""
Table cleanup shared by every table extractor.

Raw extractor output is noisy: cells are None for merged cells, contain
hard line breaks from wrapped text, and whole rows/columns can be empty
where the extractor over-detected ruling lines. These helpers turn that into
a compact grid of strings, and reject "tables" that are really just a boxed
paragraph (a single cell or a single column).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_WHITESPACE = re.compile(r"\s+")


def clean_cell(value: object) -> str:
    """None -> "", and collapse wrapped lines/extra spaces into single spaces."""
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", str(value)).strip()


def clean_rows(raw: Sequence[Sequence[object]]) -> list[list[str]]:
    """Clean every cell, then drop rows and columns that are entirely empty."""
    rows = [[clean_cell(c) for c in row] for row in raw]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [col for col in range(width) if any(r[col] for r in rows)]
    return [[r[col] for col in keep] for r in rows]


def is_real_table(rows: list[list[str]]) -> bool:
    """A table needs at least 2 rows and 2 columns. Anything smaller is
    almost always a bordered text box, which should stay ordinary text."""
    return len(rows) >= 2 and max((len(r) for r in rows), default=0) >= 2
