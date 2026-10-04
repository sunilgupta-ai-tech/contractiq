"""Phase 25: choosing evidence when several documents hold the same text."""

from app.rag.selection import adds_nothing, select_evidence
from app.rag.types import EvidenceBlock, RetrievedChunk
from app.services.citation_service import resolve_citations


def chunk(
    n: int, doc: str = "d1", text: str | None = None, score: float | None = None, uploaded=None
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{n}",
        parent_id=None,
        document_id=doc,
        document_title=f"Title {doc}",
        version_id=f"v-{doc}",
        version_label="v1",
        text=text or f"Distinct passage number {n} about topic {n}.",
        heading_path=[],
        section=None,
        section_title=None,
        clause=None,
        clause_title=None,
        page=1,
        page_end=1,
        chunk_type="text",
        score=0.0,
        rerank_score=score if score is not None else 10.0 - n,
        uploaded_at=uploaded,
    )


def ids(chunks):
    return [c.chunk_id for c in chunks]


DEFINITION = "Python is a high-level, general-purpose programming language."


def test_one_document_without_repeats_keeps_the_rerankers_top_n():
    ranked = [chunk(i) for i in range(10)]
    top, merged = select_evidence(ranked, 6, max_per_document=3)
    assert ids(top) == ids(ranked[:6])
    assert merged == 0


def test_text_copied_into_several_documents_takes_one_slot():
    ranked = [
        chunk(0, "handbook", DEFINITION),
        chunk(1, "training", "  python is a High-Level general-purpose programming language "),
        chunk(2, "it-policy", DEFINITION),
        chunk(3, "handbook"),
    ]
    top, merged = select_evidence(ranked, 6, max_per_document=3)
    assert ids(top) == ["c0", "c3"]
    assert merged == 2
    assert [d["document_id"] for d in top[0].also_found_in] == ["training", "it-policy"]


def test_a_passage_wholly_inside_a_kept_one_adds_nothing():
    longer = f"Introduction. {DEFINITION} It was created by Guido van Rossum."
    top, _ = select_evidence(
        [chunk(0, "a", longer), chunk(1, "b", DEFINITION)], 6, max_per_document=3
    )
    assert ids(top) == ["c0"]
    # A lower-ranked passage that says more takes the shorter one's slot.
    shorter, copy = chunk(0, "a", DEFINITION), chunk(2, "c", DEFINITION)
    top, merged = select_evidence([shorter, chunk(1, "b", longer), copy], 6, max_per_document=3)
    assert ids(top) == ["c1"]
    assert merged == 2
    assert [d["document_id"] for d in top[0].also_found_in] == ["a", "c"]


def test_finance_same_template_different_amounts_are_both_kept():
    a = "INVOICE NO. 4471 Vendor: Sharma Traders Amount due: Rs 18,500 Due date: 15 November 2026"
    b = "INVOICE NO. 4471 Vendor: Sharma Traders Amount due: Rs 18,600 Due date: 15 November 2026"
    top, merged = select_evidence(
        [chunk(0, "inv-a", a), chunk(1, "inv-b", b)], 6, max_per_document=3
    )
    assert ids(top) == ["c0", "c1"]
    assert merged == 0


def test_education_same_syllabus_different_course_or_word_are_both_kept():
    base = "Course CS101 covers variables, loops and functions. Attendance is mandatory."
    other_code = base.replace("CS101", "CS102")
    negated = base.replace("is mandatory", "is not mandatory")
    for variant in (other_code, negated):
        top, merged = select_evidence(
            [chunk(0, "syllabus-a", base), chunk(1, "syllabus-b", variant)], 6, max_per_document=3
        )
        assert ids(top) == ["c0", "c1"]
        assert merged == 0
    assert not adds_nothing(negated, base)
    assert not adds_nothing("", base)


def test_one_document_cannot_crowd_out_the_others():
    ranked = [chunk(i, "long-guide") for i in range(5)] + [chunk(5, "policy"), chunk(6, "faq")]
    top, _ = select_evidence(ranked, 6, max_per_document=3)
    assert ids(top) == ["c0", "c1", "c2", "c3", "c5", "c6"]
    assert sum(1 for c in top if c.document_id == "long-guide") == 4  # 3 + one free slot


def test_with_nothing_else_one_document_fills_every_slot():
    ranked = [chunk(i, "only") for i in range(8)]
    top, _ = select_evidence(ranked, 6, max_per_document=3)
    assert ids(top) == ids(ranked[:6])


def test_exact_ties_go_to_the_newest_upload_and_nothing_else_moves():
    older = chunk(0, "old", score=5.0, uploaded="2026-01-01T00:00:00")
    newer = chunk(1, "new", score=5.0, uploaded="2026-09-01T00:00:00")
    best = chunk(2, "x", score=9.0, uploaded="2025-01-01T00:00:00")
    top, _ = select_evidence([best, older, newer], 6, max_per_document=3)
    assert ids(top) == ["c2", "c1", "c0"]
    # Chunks indexed before uploaded_at existed keep their order.
    a, b = chunk(3, "a", score=5.0), chunk(4, "b", score=5.0)
    assert ids(select_evidence([a, b], 6, max_per_document=3)[0]) == ["c3", "c4"]


def test_citations_list_the_other_documents_once():
    kept = chunk(0, "handbook", DEFINITION)
    kept.also_found_in = [
        {"document_id": "training", "document_title": "Training"},
        {"document_id": "handbook", "document_title": "Handbook"},  # its own document
    ]
    block = EvidenceBlock(number=1, text=DEFINITION, heading="", matches=[kept])
    cited = resolve_citations("Python is a programming language [1].", [block])
    assert cited.citations[0].also_found_in == [
        {"document_id": "training", "document_title": "Training"}
    ]
