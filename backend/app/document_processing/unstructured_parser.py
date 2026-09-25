"""
Unstructured (unstructured.io) — intentionally NOT used yet.

Decision (Phase 4)
------------------
The original plan listed Unstructured for "complex layouts". It is left out
of the default pipeline because:

* `unstructured[pdf]` pulls in PyTorch, layout-detection models and ONNX
  runtimes — several GB added to the worker image, and slow cold starts.
* For typical contracts (single-column text, ruled tables, occasional scans)
  PyMuPDF + pdfplumber + Tesseract already cover text, tables and OCR, with
  each step small and explainable (see pdf_service.py).

When to revisit: if evaluation (Phase 12) shows poor extraction on
multi-column or heavily designed documents (brochure-style order forms,
two-column regulatory text). The integration point would be a third parser
in `pdf_service.parse_pdf` that returns the same `ParsedPage` objects, used
only for pages flagged as complex — no downstream code would change.
"""
