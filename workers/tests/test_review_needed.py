"""Phase 21: when a processed document should be checked by a person."""

from dataclasses import replace

from worker.services.pipeline import review_needed

from app.document_processing.parser import ParsedDocument, ParsedPage, TextBlock


def test_review_is_required_for_weak_or_empty_scans_and_recovered_pdfs():
    def page(n, *, scanned, conf=None, text="words " * 20):
        blocks = [TextBlock(text, (0, 0, 1, 1))] if text else []
        return ParsedPage(n, 600, 800, blocks=blocks, is_scanned=scanned, ocr_confidence=conf)

    doc = ParsedDocument(
        pages=[
            page(1, scanned=False),
            page(2, scanned=True, conf=92.0),
            page(3, scanned=True, conf=40.0),
            page(4, scanned=True, text=""),
            page(5, scanned=True, conf=30.0),  # transcribed: fine
        ]
    )
    review = review_needed(doc, transcribed={5}, min_confidence=70)
    assert review == {
        "required": True,
        "reasons": ["low_ocr_confidence", "no_text_found"],
        "pages": [3, 4],
    }
    clean = ParsedDocument(pages=[page(1, scanned=False)])
    assert review_needed(clean, transcribed=set(), min_confidence=70)["required"] is False
    recovered = replace(clean, metadata={"parser": "pdfplumber-fallback"})
    assert review_needed(recovered, transcribed=set(), min_confidence=70)["reasons"] == [
        "damaged_pdf_recovered"
    ]
