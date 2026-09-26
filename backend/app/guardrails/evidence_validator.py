"""
Groundedness check: is each claim in an answer supported by the evidence it
cites? (Phase 11)

Citation checking (Phase 7) makes sure every [n] points at a real evidence
block. It cannot tell whether the sentence *says what the block says*. A
model can cite [2] and still write "90 days" when [2] says "60 days". This
module checks each answer sentence against the text of the blocks it cites:

    numbers   every number, amount, percentage or year in the sentence must
              appear in the cited text (digits compared without separators,
              so "10,000" matches "10000"). A wrong number is the most
              damaging error in a contract answer, and the easiest to check.
    overlap   at least MIN_OVERLAP of the sentence's content words must
              appear in the cited text (a paraphrase shares its key terms)
    cited     a factual sentence with no valid citation is unsupported

Short connective sentences ("In summary:") are not claims and are skipped.

The result is a score (supported claims / claims) and the unsupported
sentences. What happens next is policy (GROUNDING_MODE):

    flag     (default) the answer is returned with `groundedness` and
             `unsupported_claims`, so the UI can warn; nothing is removed
    enforce  an answer below GROUNDING_MIN_SCORE, or with a number that is
             not in its evidence, is replaced by an "insufficient evidence"
             reply rather than shown

This is a lexical check: fast, deterministic and free, but it can miss a
subtle contradiction and can doubt a heavy paraphrase. That is why the
default only flags; Phase 12's evaluation set is where the threshold (and
the choice of mode) should be calibrated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.rag.types import EvidenceBlock

MIN_OVERLAP = 0.3
MIN_CLAIM_WORDS = 4

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_MARKER = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")
_WORD = re.compile(r"[a-z][a-z'-]{3,}")
_STOPWORDS = frozenset(
    """
    about above after again against also although among another because been before
    being below between both cannot could does doing down during each either else
    ever every from further have having here hers herself himself however into itself
    just like made make many more most much must neither never nothing only other
    otherwise over same shall should since some such than that their theirs them
    themselves then there therefore these they this those though through under until
    upon very were what when where whether which while whom whose will with within
    without would your yours agreement contract party parties clause section
    """.split()
)


@dataclass
class ClaimCheck:
    sentence: str
    cited: list[int]
    supported: bool
    reason: str | None = None  # why not: "uncited", "number 90 not in evidence", ...


@dataclass
class GroundingReport:
    score: float  # supported claims / claims; 1.0 when there are no claims
    claims: list[ClaimCheck] = field(default_factory=list)

    @property
    def unsupported(self) -> list[ClaimCheck]:
        return [c for c in self.claims if not c.supported]

    @property
    def has_wrong_number(self) -> bool:
        return any((c.reason or "").startswith("number") for c in self.unsupported)


UNVERIFIED_MESSAGE = (
    "I found passages related to this question but could not verify an answer against "
    "them, so none is shown. The relevant passages are listed below; please check them "
    "directly or rephrase the question."
)


def should_withhold(report: GroundingReport | None, *, mode: str, min_score: float) -> bool:
    """GROUNDING_MODE=enforce: withhold answers that are mostly unsupported or
    state a number their evidence doesn't contain. `flag` never withholds."""
    if mode != "enforce" or report is None:
        return False
    return report.score < min_score or report.has_wrong_number


def check_grounding(answer: str, blocks: list[EvidenceBlock]) -> GroundingReport:
    """Check `answer` (with the model's own [n] numbering) against `blocks`."""
    by_number = {b.number: b for b in blocks}
    claims: list[ClaimCheck] = []
    for sentence in _SENTENCE.split(answer.strip()):
        text = _MARKER.sub("", sentence).strip()
        words = _content_words(text)
        numbers = _numbers(text)
        if len(words) < MIN_CLAIM_WORDS and not numbers:
            continue  # connective or heading, not a claim
        cited = [
            n
            for match in _MARKER.finditer(sentence)
            for n in (int(x) for x in re.split(r"\s*,\s*", match.group(1)))
            if n in by_number
        ]
        claims.append(_check(text, words, numbers, cited, by_number))
    supported = sum(c.supported for c in claims)
    score = round(supported / len(claims), 2) if claims else 1.0
    return GroundingReport(score=score, claims=claims)


def _check(
    text: str,
    words: set[str],
    numbers: set[str],
    cited: list[int],
    by_number: dict[int, EvidenceBlock],
) -> ClaimCheck:
    if not cited:
        return ClaimCheck(text, cited, False, "uncited")
    # The heading carries the clause number, pages and version label
    # ("8 TERMINATION > 8.3 Notice | version v2 | page 12"), which answers
    # legitimately mention even when the clause body doesn't repeat them.
    evidence = " ".join(f"{by_number[n].heading}\n{by_number[n].text}" for n in cited)
    evidence_numbers = _numbers(evidence)
    missing = sorted(numbers - evidence_numbers)
    if missing:
        return ClaimCheck(text, cited, False, f"number {missing[0]} not in evidence")
    if words:
        overlap = len(words & _content_words(evidence)) / len(words)
        if overlap < MIN_OVERLAP:
            return ClaimCheck(text, cited, False, f"low overlap ({overlap:.0%})")
    return ClaimCheck(text, cited, True)


def _numbers(text: str) -> set[str]:
    """Numbers without thousands separators or trailing periods: '10,000.' -> '10000'."""
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUMBER.finditer(text)}


def _content_words(text: str) -> set[str]:
    """Lower-cased words of 4+ letters, minus stopwords, crudely de-pluralised
    so 'days'/'day' and 'notices'/'notice' match."""
    words = set()
    for word in _WORD.findall(text.lower()):
        word = word.strip("'-")
        if word in _STOPWORDS:
            continue
        words.add(word[:-1] if word.endswith("s") and len(word) > 4 else word)
    return words
