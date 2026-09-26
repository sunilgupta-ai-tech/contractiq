# File formats (Phase 16)

DocuNexa AI accepts PDF (digital or scanned), JPG, PNG, Word (.docx) and Excel (.xlsx). Every format becomes the same `ParsedDocument` that PDF processing produces ([pdf-processing.md](pdf-processing.md)), so chunking, embeddings, search, citations and the Assistant work the same way for all of them.

| Format | How it is read | "Page" in citations |
|---|---|---|
| PDF | Text layer, tables and images (PyMuPDF, pdfplumber); OCR for scanned pages | PDF page |
| JPG / PNG | Wrapped in a one-page PDF and handled like a scan: OCR, layout, a caption of the image | 1 |
| Word (.docx) | Paragraph styles give headings (Title, Heading 1–9), list items and body text; tables in place; embedded pictures captioned | Word's own page breaks (explicit and `lastRenderedPageBreak`); 1 if the file has none |
| Excel (.xlsx) | Each visible sheet opens a section `N. <sheet name>`; rows become tables of ~1,400 characters that each repeat the header row | Sheet number |

## Upload checks

The extension says what the user claims; the bytes decide ([`formats.py`](../backend/app/document_processing/formats.py)).

- **PDF:** `%PDF-` signature.
- **JPG / PNG:** matching signature, a decode check, and a cap of 80 megapixels.
- **.docx / .xlsx:** a ZIP containing `[Content_Types].xml` and `word/document.xml` / `xl/workbook.xml`.
- **Refused, with a message that says what to do:**
  - legacy `.doc` / `.xls`, and password-protected Office files (both are OLE containers): "save it as .docx/.xlsx";
  - macro-enabled `.docm` / `.xlsm`, and any file carrying `vbaProject.bin`;
  - ZIPs over 10,000 entries or 512 MB uncompressed;
  - declared types such as `text/html`.
- **Storage:** the original is stored as `original.<ext>` (never under the client's name).
- **New versions:** a new version must be the same kind of file as the document.

## Word

- **Headings** come from paragraph styles, so a heading like "8. Termination" becomes section 8 exactly as in a PDF.
- **Tables** keep their rows; merged cells appear once.
- **Pictures** at least 150 px on the short side are saved and captioned (Phase 9). Vector art (EMF/WMF) is skipped.
- **Not read:** headers, footers, comments and tracked deletions.

## Excel

- **Values** are Excel's last calculated values; formulas are not re-evaluated.
- **Formatting:** dates are written as ISO dates and whole numbers without `.0`.
- **Skipped:** empty rows, trailing empty columns, hidden sheets and chart sheets.
- **Cell limit:** `MAX_SPREADSHEET_CELLS` (default 200,000) bounds a huge workbook. Anything left out is listed in the version's warnings.
- **Model cost:** only the first table of each sheet gets a model summary. Continuation tables describe themselves ("Sheet 'Invoices', data rows 41-80 (continued)"), so a 10,000-row sheet costs one summary call, not 250.

## Images, handwriting and registers

- **Preparation:** photos are turned upright (EXIF orientation) and scaled to at most `MAX_IMAGE_SIDE_PX` (4,000) on the long side, then OCR'd at `OCR_DPI`. The image is also captioned, which answers "what is this?" (a receipt, a stamp, a whiteboard).
- **Weak OCR triggers transcription:** Tesseract reads print, not handwriting. A scanned page (from a photo or a scanned PDF) whose OCR is weak is sent to the vision model for transcription. Weak means mean confidence below `TRANSCRIBE_BELOW_OCR_CONFIDENCE` (70) or fewer than 8 words.
- **What comes back:** the model returns the text in reading order. Tables, registers and ledgers come back as Markdown tables, which become real tables, so a register's rows and columns stay aligned in chunks and answers. Unreadable words are marked `[illegible]` rather than guessed.
- **Cost limits:**
  - Clean print never triggers a transcription call.
  - `MAX_TRANSCRIBED_PAGES_PER_DOCUMENT` (20) caps one document.
  - Results are cached per tenant by image hash.
  - `HANDWRITING_TRANSCRIPTION_ENABLED=false` turns the feature off.
- **Failure handling:** a failed transcription keeps the page's OCR text, and the document is still indexed. The outcome is recorded in `extraction_metadata`:
  - `format`
  - `transcribed_pages`
  - `transcription`
  - `warnings`

## Contract analysis

Clause extraction and risk review (Phase 10) run for PDF and Word documents only. Photos and spreadsheets are searchable in the Assistant, but "missing indemnity clause" findings about an invoice list would be noise, and they would cost model calls.
