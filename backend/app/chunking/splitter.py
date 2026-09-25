"""
Split a segment that is too long for one chunk into windows.

Boundaries are chosen in order of preference, so text is cut where a human
editor would cut it:

    1. between paragraphs (source blocks)
    2. between sentences, for a paragraph that alone exceeds the limit
    3. between words, for a single sentence that alone exceeds the limit
       (rare: run-on definitions or lists written as one sentence)

Consecutive windows of the same segment overlap by up to `overlap_tokens` of
trailing sentences, so a statement cut at a boundary ("... unless the
Customer") still appears with its continuation in at least one chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.chunking.structure import Piece
from app.chunking.tokens import estimate_tokens

# Abbreviations common in contracts that end with a full stop but do not end
# a sentence. Without this list "Acme Ltd. shall pay" would split after "Ltd."
_ABBREVIATIONS = {
    "e.g", "i.e", "etc", "no", "nos", "art", "arts", "sec", "cl", "para", "pp", "p",
    "ltd", "inc", "co", "corp", "plc", "llc", "llp", "mr", "mrs", "ms", "dr", "st",
    "vs", "v", "approx", "incl", "min", "max", "jan", "feb", "mar", "apr", "jun",
    "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}  # fmt: skip
# Candidate sentence ends: . ; ? ! followed by whitespace and a capital letter,
# digit, quote or opening bracket.
_SENTENCE_END = re.compile(r"(?<=[.;?!])\s+(?=[A-Z0-9(\"“'])")


@dataclass
class Window:
    """A chunk-sized piece of a segment, plus the pieces it drew text from."""

    text: str
    source_indexes: list[int]  # indexes into the segment's pieces


@dataclass
class _Unit:
    text: str
    piece: int  # which source piece the unit came from
    tokens: int


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        candidate = text[start : match.start()]
        last_word = candidate.rsplit(None, 1)[-1].rstrip(".").lower() if candidate else ""
        if last_word in _ABBREVIATIONS or re.fullmatch(r"[a-z]", last_word):
            continue  # "Ltd.", "e.g.", "Schedule A." — not a sentence end
        parts.append(candidate.strip())
        start = match.end()
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def _word_windows(sentence: str, max_tokens: int) -> list[str]:
    """Last resort for a single over-long sentence: cut between words."""
    out: list[str] = []
    current: list[str] = []
    words = sentence.split()
    for word in words:
        if current and estimate_tokens(" ".join([*current, word])) > max_tokens:
            out.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        out.append(" ".join(current))
    return out


def _units(pieces: list[Piece], max_tokens: int) -> list[_Unit]:
    """Break pieces into the largest units that each fit in one window."""
    units: list[_Unit] = []
    for index, piece in enumerate(pieces):
        if estimate_tokens(piece.text) <= max_tokens:
            units.append(_Unit(piece.text, index, estimate_tokens(piece.text)))
            continue
        for sentence in split_sentences(piece.text):
            parts = (
                [sentence]
                if estimate_tokens(sentence) <= max_tokens
                else _word_windows(sentence, max_tokens)
            )
            units += [_Unit(p, index, estimate_tokens(p)) for p in parts]
    return units


def _join(units: list[_Unit]) -> str:
    """Units from the same paragraph join with a space; paragraphs with a blank line."""
    text = ""
    for i, unit in enumerate(units):
        if i == 0:
            text = unit.text
        elif unit.piece == units[i - 1].piece:
            text += " " + unit.text
        else:
            text += "\n\n" + unit.text
    return text


def split_pieces(pieces: list[Piece], *, max_tokens: int, overlap_tokens: int) -> list[Window]:
    """Pack pieces into windows of at most `max_tokens` (estimated)."""
    units = _units(pieces, max_tokens)
    windows: list[Window] = []
    current: list[_Unit] = []

    def emit() -> None:
        windows.append(Window(_join(current), sorted({u.piece for u in current})))

    for unit in units:
        # +2 tokens covers the joining separator between units.
        size = sum(u.tokens + 2 for u in current)
        if current and size + unit.tokens > max_tokens:
            emit()
            # Carry trailing units into the next window as overlap, but never
            # so many that the overlap alone would fill it.
            carry: list[_Unit] = []
            for prev in reversed(current):
                if sum(u.tokens for u in carry) + prev.tokens > overlap_tokens:
                    break
                carry.insert(0, prev)
            if carry and sum(u.tokens for u in carry) + unit.tokens > max_tokens:
                carry = []
            current = carry
        current.append(unit)
    if current:
        emit()
    return windows
