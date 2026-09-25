"""
Layout analysis: label every text block as a heading, paragraph, list item,
table text, or repeated page header/footer.

Why this matters
----------------
Phase 5 chunks contracts by section and clause ("8. TERMINATION" ->
"8.3 Notice Period"), not by a fixed number of tokens, because legal meaning
follows the document's structure. That only works if headings are known.
Removing running headers/footers ("ACME CONFIDENTIAL", "Page 4 of 40") stops
them from being repeated inside every chunk, and marking table text stops a
table's cells from appearing twice (once as text, once as the Table).

The rules are deliberately simple, explainable heuristics that work on both
text-layer and OCR text. They run once per document, after OCR, because
header/footer detection needs to see every page.
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import median

from app.document_processing.parser import BBox, BlockKind, ParsedPage, TextBlock

# Blocks within this share of the page height from the top/bottom edge are
# candidates for running headers/footers.
MARGIN_SHARE = 0.08
# A margin text must appear on at least this share of pages (and on at least
# MIN_REPEAT_PAGES pages) to count as a running header/footer.
REPEAT_SHARE = 0.5
MIN_REPEAT_PAGES = 3
# A block is "table text" when this much of its area lies inside a table.
TABLE_OVERLAP = 0.6
# Headings are short. Anything longer is a paragraph, even if bold.
HEADING_MAX_CHARS = 120
HEADING_MAX_WORDS = 15
# Font this much larger than the body text reads as a heading.
HEADING_SIZE_RATIO = 1.15

# "8.", "8.3", "8.3.1", "12" followed by a capitalised word
_NUMBERED = re.compile(r"^\d{1,2}(\.\d{1,2}){0,3}\.?\s+[A-Z]")
# "ARTICLE 5", "Article IV", "SECTION 2", "Schedule 1", "Annex B", "Exhibit A"
_NAMED = re.compile(
    r"^(article|section|schedule|annex|appendix|exhibit)\s+([0-9]+|[ivxlc]+|[a-z])\b",
    re.IGNORECASE,
)
# "(a)", "(iv)", "a)", "1)", "•", "-", "–"
_LIST_ITEM = re.compile(r"^(\(?[a-z0-9]{1,4}\)|[•\-–·▪])\s+", re.IGNORECASE)
# Page-number footers: "3", "- 3 -", "Page 3", "Page 3 of 40", "3/40"
_PAGE_NUMBER = re.compile(r"^[-–\s]*(page\s+)?\d+(\s*(of|/)\s*\d+)?[-–\s]*$", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")


def classify_blocks(pages: list[ParsedPage]) -> None:
    """Set `kind` on every block of every page, in place."""
    body_size = _body_font_size(pages)
    repeated = _repeated_margin_texts(pages)
    for page in pages:
        for block in page.blocks:
            block.kind = _classify(block, page, body_size, repeated)


def _classify(
    block: TextBlock, page: ParsedPage, body_size: float | None, repeated: set[str]
) -> BlockKind:
    zone = _margin_zone(block.bbox, page.height)
    if zone and (_normalise(block.text) in repeated or _PAGE_NUMBER.match(block.text)):
        return BlockKind.HEADER if zone == "top" else BlockKind.FOOTER
    if any(_overlap(block.bbox, table.bbox) >= TABLE_OVERLAP for table in page.tables):
        return BlockKind.TABLE_TEXT
    if is_heading(block, body_size):
        return BlockKind.HEADING
    if _LIST_ITEM.match(block.text):
        return BlockKind.LIST_ITEM
    return BlockKind.PARAGRAPH


def is_heading(block: TextBlock, body_size: float | None) -> bool:
    """A block is a heading when it is short AND looks like one.

    "Looks like one" means any of:
      * a larger font than the body text, or bold;
      * a numbered/named heading pattern ("8.3 Notice Period", "ARTICLE 5")
        written in capitals, bold or larger font; or
      * a short line entirely in capitals ("TERMINATION").
    Numbering alone is not enough: "8.3 The Supplier shall ..." is a numbered
    clause *sentence*, which is body text. OCR blocks have no font data, so for
    them the capitals/numbering rules do the work.
    """
    text = block.text.strip()
    if not text or len(text) > HEADING_MAX_CHARS or len(text.split()) > HEADING_MAX_WORDS:
        return False
    # Sentences end with a full stop; headings don't ("8." alone is fine).
    if text.endswith((".", ";", ",")) and not re.fullmatch(r"\d+(\.\d+)*\.", text):
        return False
    larger = bool(
        block.font_size and body_size and block.font_size >= body_size * HEADING_SIZE_RATIO
    )
    letters = [c for c in text if c.isalpha()]
    all_caps = len(letters) >= 3 and all(c.isupper() for c in letters)
    patterned = bool(_NUMBERED.match(text) or _NAMED.match(text))
    return larger or block.is_bold or all_caps or (patterned and _title_like(text))


def _title_like(text: str) -> bool:
    """'8.3 Notice Period' (most words capitalised) vs '8.3 The notice is due'."""
    words = [w for w in re.sub(r"^[\d.()]+\s*", "", text).split() if w[:1].isalpha()]
    small = {"and", "or", "of", "the", "to", "for", "in", "on", "a", "an", "by", "with"}
    significant = [w for w in words if w.lower() not in small]
    return bool(significant) and all(w[0].isupper() for w in significant)


def _body_font_size(pages: list[ParsedPage]) -> float | None:
    """The font size used by most of the document's text, weighted by length.

    A median weighted by characters, so the body size wins even if there are
    many short headings in a larger font.
    """
    weights: Counter[float] = Counter()
    for page in pages:
        for block in page.blocks:
            if block.font_size:
                weights[block.font_size] += len(block.text)
    if not weights:
        return None
    expanded = [size for size, n in weights.items() for _ in range(min(n, 10_000))]
    return float(median(expanded))


def _repeated_margin_texts(pages: list[ParsedPage]) -> set[str]:
    """Normalised texts that recur in the top/bottom margin across pages."""
    if len(pages) < MIN_REPEAT_PAGES:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        seen = {_normalise(b.text) for b in page.blocks if _margin_zone(b.bbox, page.height)}
        counts.update(seen)  # count each text once per page
    threshold = max(MIN_REPEAT_PAGES, int(len(pages) * REPEAT_SHARE))
    return {text for text, n in counts.items() if n >= threshold and text}


def _normalise(text: str) -> str:
    """Digits -> '#', so 'Page 3 of 40' and 'Page 4 of 40' count as the same text."""
    return _DIGITS.sub("#", " ".join(text.lower().split()))


def _margin_zone(bbox: BBox, page_height: float) -> str | None:
    if page_height <= 0:
        return None
    if bbox[3] <= page_height * MARGIN_SHARE:
        return "top"
    if bbox[1] >= page_height * (1 - MARGIN_SHARE):
        return "bottom"
    return None


def _overlap(inner: BBox, outer: BBox) -> float:
    """Share of `inner`'s area that lies inside `outer` (0.0-1.0)."""
    width = min(inner[2], outer[2]) - max(inner[0], outer[0])
    height = min(inner[3], outer[3]) - max(inner[1], outer[1])
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    if width <= 0 or height <= 0 or area <= 0:
        return 0.0
    return (width * height) / area
