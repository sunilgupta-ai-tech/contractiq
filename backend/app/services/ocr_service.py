"""
OCR for the pages `parse_pdf` flagged as scanned.

Only scanned pages are OCR'd. Running OCR on pages that already have a text
layer would be slower (seconds per page) and *less* accurate than the text
the PDF already contains.

Error handling
--------------
* A page that times out gets a warning and stays empty; the rest of the
  document is still processed and indexed.
* Tesseract missing, or a language pack missing, is a deployment problem,
  not a problem with the file. Those errors are raised so the job fails
  loudly (and is retried after the deployment is fixed) instead of silently
  producing documents with empty scanned pages.
* OCR disabled by configuration: scanned pages stay empty, with a warning
  that tells the user why their scanned pages are not searchable.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.document_processing.ocr import ocr_page
from app.document_processing.parser import ParsedDocument
from app.document_processing.pymupdf_parser import open_pdf
from app.services.pdf_service import PdfOptions

logger = get_logger(__name__)


def ocr_scanned_pages(data: bytes, document: ParsedDocument, options: PdfOptions) -> list[str]:
    """Fill in text for scanned pages, in place. Returns warnings."""
    scanned = document.scanned_page_numbers
    if not scanned:
        return []
    if not options.ocr_enabled:
        return [f"OCR is disabled; {len(scanned)} scanned page(s) have no searchable text."]

    warnings: list[str] = []
    with open_pdf(data) as doc:
        for number in scanned:
            page = document.pages[number - 1]
            try:
                result = ocr_page(
                    doc[number - 1],
                    dpi=options.ocr_dpi,
                    languages=options.ocr_languages,
                    timeout_s=options.ocr_timeout_s,
                )
            except RuntimeError as exc:
                # pytesseract signals a timeout with a RuntimeError whose
                # message mentions "timeout"; every other Tesseract error
                # (missing binary, missing language) is re-raised — see above.
                if "timeout" not in str(exc).lower():
                    raise
                logger.warning("ocr_timeout", extra={"page": number})
                warnings.append(f"OCR timed out on page {number}; that page has no text.")
                continue
            page.blocks = result.blocks
            page.ocr_confidence = result.mean_confidence
            if not result.blocks:
                warnings.append(f"No text was recognised on scanned page {number}.")
    return warnings
