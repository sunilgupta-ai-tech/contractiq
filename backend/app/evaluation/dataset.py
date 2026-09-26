"""
Golden dataset: questions with known answers over known contracts.

Format (JSON; see datasets/sample_msa.json):

    {"name": "sample-msa", "version": 1,
     "documents": {"msa": {"title": "...", "contract_type": "MSA",
                           "builder": "sample_msa" | "path": "contracts/x.pdf"}},
     "examples": [{"id": "renewal-notice", "document": "msa",
                   "question": "How much notice stops automatic renewal?",
                   "answerable": true,
                   "expected_answer": "At least 90 days before the end of the term.",
                   "facts": ["90|ninety"],
                   "evidence": [{"clause": "3.1"}],
                   "tags": ["renewal", "dates"]}]}

Evidence is located, not pinned
-------------------------------
Relevant chunks are described by *where the answer is* — a clause number,
a page, and/or a text snippet — never by chunk IDs. Chunk IDs change
whenever chunking rules or documents change; "clause 3.1" and "the text
contains 'ninety (90) days'" do not. Within one spec, every given field
must match (AND); an example is answered by any of its specs (OR).

Facts
-----
Each fact is a short string the answer must contain; alternatives are
separated by "|" ("90|ninety"). Matching ignores case, whitespace and
thousands separators, and a numeric fact must match a whole number ("5"
does not match "15" or "25").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATASETS_DIR = Path(__file__).parent / "datasets"


@dataclass(frozen=True)
class EvidenceSpec:
    clause: str | None = None
    page: int | None = None
    text: str | None = None

    def matches(
        self, *, text: str, clause: str | None, clauses: list[str], page_start: int, page_end: int
    ) -> bool:
        if self.clause is not None and self.clause != clause and self.clause not in clauses:
            return False
        if self.page is not None and not page_start <= self.page <= page_end:
            return False
        return self.text is None or _norm(self.text) in _norm(text)


@dataclass(frozen=True)
class GoldenExample:
    id: str
    document: str  # key into GoldenDataset.documents
    question: str
    answerable: bool = True
    expected_answer: str = ""
    facts: tuple[str, ...] = ()
    evidence: tuple[EvidenceSpec, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentSource:
    key: str
    title: str
    contract_type: str = "OTHER"
    builder: str | None = None  # name in sample_contract.BUILDERS
    path: str | None = None  # PDF path, relative to the dataset file

    def load(self, base: Path) -> bytes:
        if self.builder is not None:
            from app.evaluation.sample_contract import BUILDERS

            return BUILDERS[self.builder]()
        assert self.path is not None
        return (base / self.path).read_bytes()


@dataclass
class GoldenDataset:
    name: str
    version: int
    documents: dict[str, DocumentSource]
    examples: list[GoldenExample]
    description: str = ""
    base_dir: Path = field(default=DATASETS_DIR)

    @classmethod
    def load(cls, path: str | Path) -> GoldenDataset:
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text()), base_dir=path.parent)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, base_dir: Path = DATASETS_DIR) -> GoldenDataset:
        documents = {
            key: DocumentSource(
                key=key,
                title=doc["title"],
                contract_type=doc.get("contract_type", "OTHER"),
                builder=doc.get("builder"),
                path=doc.get("path"),
            )
            for key, doc in data["documents"].items()
        }
        examples = [
            GoldenExample(
                id=ex["id"],
                document=ex["document"],
                question=ex["question"],
                answerable=ex.get("answerable", True),
                expected_answer=ex.get("expected_answer", ""),
                facts=tuple(ex.get("facts", ())),
                evidence=tuple(EvidenceSpec(**spec) for spec in ex.get("evidence", ())),
                tags=tuple(ex.get("tags", ())),
            )
            for ex in data["examples"]
        ]
        dataset = cls(
            name=data["name"],
            version=data.get("version", 1),
            documents=documents,
            examples=examples,
            description=data.get("description", ""),
            base_dir=base_dir,
        )
        dataset.validate()
        return dataset

    def validate(self) -> None:
        """Fail fast on a malformed dataset rather than report odd metrics."""
        ids = [ex.id for ex in self.examples]
        if len(ids) != len(set(ids)):
            raise ValueError("example ids must be unique")
        for doc in self.documents.values():
            if (doc.builder is None) == (doc.path is None):
                raise ValueError(f"document {doc.key!r} needs exactly one of builder/path")
        for ex in self.examples:
            if ex.document not in self.documents:
                raise ValueError(f"{ex.id}: unknown document {ex.document!r}")
            if ex.answerable and not (ex.facts and ex.evidence):
                raise ValueError(f"{ex.id}: answerable examples need facts and evidence")
            if not ex.answerable and (ex.facts or ex.evidence):
                raise ValueError(f"{ex.id}: unanswerable examples have no facts or evidence")


# --- Fact matching -----------------------------------------------------------------------

_SPACE = re.compile(r"\s+")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").lower()
    return _SPACE.sub(" ", _THOUSANDS.sub("", text)).strip()


def fact_found(fact: str, answer: str) -> bool:
    """True if any "|"-separated alternative of `fact` appears in `answer`."""
    haystack = _norm(answer)
    for alternative in fact.split("|"):
        needle = _norm(alternative)
        if not needle:
            continue
        if re.fullmatch(r"[\d.%]+", needle):
            # Whole-number match: "5" must not match "15", "25" or "5.5".
            if re.search(rf"(?<![\d.]){re.escape(needle)}(?![\d]|\.\d)", haystack):
                return True
        elif needle in haystack:
            return True
    return False
