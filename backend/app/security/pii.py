"""
Personal-data detection (Phase 24).

Contracts, registers and scans often carry personal data. The worker counts
what each version contains, so people can see it on the document and treat
it accordingly:

    aadhaar  12 digits (first 2-9), optionally grouped 4-4-4; must pass the
             Verhoeff check digit, so an arbitrary 12-digit number rarely matches
    pan      Indian PAN, AAAAA9999A with a valid holder-type letter (P, C, F…)
    card     13-19 digit payment card with a known prefix; must pass Luhn
    email    e-mail address
    phone    Indian mobile (+91 / 0 optional, starts 6-9), or +<country code>
             international numbers

Only the number of *distinct* values per type is recorded, never the values
themselves: the flag must not become a second copy of the data. The data
stays protected like any document content: access control (Phase 20),
encryption at rest and in transit, and the audit trail.

`mask_pii` hides Aadhaar and card numbers in AI answers when
PII_MASK_ANSWERS is on (the last 4 digits stay, enough to tell them apart).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

# Verhoeff tables (dihedral group D5), used by Aadhaar's check digit.
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_valid(digits: str) -> bool:
    check = 0
    for i, ch in enumerate(reversed(digits)):
        check = _D[check][_P[i % 8][int(ch)]]
    return check == 0


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


_AADHAAR = re.compile(r"(?<![\d-])[2-9]\d{3}([ -]?)\d{4}\1\d{4}(?![\d-])")
_PAN = re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b")
_CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
_CARD_PREFIX = re.compile(r"^(?:4|5[1-5]|2[2-7]|3[47]|6(?:011|5|4[4-9]|0|2))")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_PHONE_IN = re.compile(r"(?<![\w+])(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)")
_PHONE_INTL = re.compile(r"(?<![\w+])\+[1-9]\d{0,2}(?:[ -]?\d{2,5}){2,4}(?!\d)")


def _aadhaar(match: re.Match[str]) -> str | None:
    digits = _digits(match.group())
    return digits if verhoeff_valid(digits) else None


def _card(match: re.Match[str]) -> str | None:
    digits = _digits(match.group())
    if 13 <= len(digits) <= 19 and _CARD_PREFIX.match(digits) and luhn_valid(digits):
        return digits
    return None


def _phone(match: re.Match[str]) -> str | None:
    digits = _digits(match.group())
    return digits[-10:] if 8 <= len(digits) <= 15 else None


@dataclass(frozen=True)
class _Detector:
    kind: str
    pattern: re.Pattern[str]
    normalize: Callable[[re.Match[str]], str | None]


# Order matters: each match is blanked out before the next detector runs,
# so a card number is not also counted as a phone number.
DETECTORS = (
    _Detector("card", _CARD, _card),
    _Detector("aadhaar", _AADHAAR, _aadhaar),
    _Detector("pan", _PAN, lambda m: m.group()),
    _Detector("email", _EMAIL, lambda m: m.group().lower()),
    _Detector("phone", _PHONE_IN, _phone),
    _Detector("phone", _PHONE_INTL, _phone),
)


def find_pii(text: str) -> dict[str, set[str]]:
    """Distinct normalized values per kind (kept in memory only)."""
    found: dict[str, set[str]] = {}
    for detector in DETECTORS:

        def blank(match: re.Match[str], detector: _Detector = detector) -> str:
            value = detector.normalize(match)
            if value is None:
                return match.group()
            found.setdefault(detector.kind, set()).add(value)
            return " " * len(match.group())

        text = detector.pattern.sub(blank, text)
    return found


def pii_report(texts: Iterable[str]) -> dict[str, object]:
    """Counts of distinct values per kind across a document's chunks (which
    overlap, hence distinct). Stored in the version's extraction metadata."""
    values: dict[str, set[str]] = {}
    for text in texts:
        for kind, found in find_pii(text).items():
            values.setdefault(kind, set()).update(found)
    counts = {kind: len(v) for kind, v in sorted(values.items())}
    return {"types": counts, "total": sum(counts.values())}


def mask_pii(text: str) -> str:
    """Aadhaar and card numbers → masked, keeping the last 4 digits."""

    def mask(detector: _Detector) -> Callable[[re.Match[str]], str]:
        def replace(match: re.Match[str]) -> str:
            value = detector.normalize(match)
            if value is None:
                return match.group()
            return "XXXX XXXX " + value[-4:] if detector.kind == "aadhaar" else "•••• " + value[-4:]

        return replace

    for detector in DETECTORS[:2]:
        text = detector.pattern.sub(mask(detector), text)
    return text
