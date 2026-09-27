"""
Upload formats (Phase 16): which files are accepted, and how each is
recognised from its *bytes*, not its name.

    PDF, scanned PDF   .pdf           %PDF- header
    Images             .jpg .jpeg .png JPEG / PNG signature, decodable
    Word               .docx          ZIP (OOXML) with word/document.xml
    Excel              .xlsx          ZIP (OOXML) with xl/workbook.xml

The extension says what the user *claims*; the signature says what the file
*is*. Both must agree, so a renamed executable or a PDF saved as .docx is
refused before it is stored.

Refused on purpose, with a message that says what to do instead:
  * legacy .doc / .xls (and password-protected Office files, which use the
    same OLE container): converting them needs LibreOffice in the worker;
  * macro-enabled .docm / .xlsm, and OOXML files carrying a VBA project;
  * ZIP archives that would expand far beyond their size (zip bombs).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.core.exceptions import InvalidFileError
from app.db.models import FileType

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"

# An OOXML document expands a lot (XML compresses well), but not without
# bound: more than this is treated as a zip bomb.
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
# Pillow's decompression-bomb guard is ~89 MP; a phone photo is 12-50 MP.
MAX_IMAGE_PIXELS = 80_000_000

SUPPORTED_HINT = "Supported files: PDF, JPG, PNG, Word (.docx) and Excel (.xlsx)."


@dataclass(frozen=True)
class UploadFormat:
    file_type: FileType
    extension: str  # stored as original.<extension>
    mime_type: str

    @property
    def stored_filename(self) -> str:
        return f"original.{self.extension}"


_BY_EXTENSION: dict[str, UploadFormat] = {
    "pdf": UploadFormat(FileType.PDF, "pdf", PDF_MIME),
    "png": UploadFormat(FileType.IMAGE, "png", PNG_MIME),
    "jpg": UploadFormat(FileType.IMAGE, "jpg", JPEG_MIME),
    "jpeg": UploadFormat(FileType.IMAGE, "jpg", JPEG_MIME),
    "docx": UploadFormat(FileType.WORD, "docx", DOCX_MIME),
    "xlsx": UploadFormat(FileType.EXCEL, "xlsx", XLSX_MIME),
}

_LEGACY = {
    "doc": "Old Word files (.doc) are not supported. Open it in Word and save it as .docx.",
    "xls": "Old Excel files (.xls) are not supported. Open it in Excel and save it as .xlsx.",
    "docm": "Macro-enabled Word files are not accepted. Save it as a regular .docx.",
    "xlsm": "Macro-enabled Excel files are not accepted. Save it as a regular .xlsx.",
}

ACCEPTED_EXTENSIONS = tuple(sorted(_BY_EXTENSION))


def extension_of(filename: str) -> str:
    _, dot, ext = filename.rpartition(".")
    return ext.lower() if dot else ""


def format_for_storage_key(storage_key: str) -> UploadFormat:
    """The format of a stored original (tenants/.../original.<ext>).
    Versions stored before Phase 16 are all original.pdf."""
    return _BY_EXTENSION.get(extension_of(storage_key), _BY_EXTENSION["pdf"])


def _source(data: bytes | Path) -> tuple[bytes, int, Any]:
    """(first bytes, size, something zipfile/Pillow can open) for bytes or a
    file on disk — large uploads are checked without loading them (Phase 21)."""
    if isinstance(data, Path):
        with data.open("rb") as handle:
            head = handle.read(16)
        return head, data.stat().st_size, data
    return data[:16], len(data), io.BytesIO(data)


def detect_format(filename: str, data: bytes | Path) -> UploadFormat:
    """The upload's format, checked against its content (bytes, or the
    path of the spooled upload).

    Raises InvalidFileError with a message the user can act on."""
    head, size, source = _source(data)
    ext = extension_of(filename)
    if ext in _LEGACY:
        raise InvalidFileError(_LEGACY[ext])
    fmt = _BY_EXTENSION.get(ext)
    if fmt is None:
        raise InvalidFileError(f"This file type is not supported. {SUPPORTED_HINT}")
    if not size:
        raise InvalidFileError("The file is empty.")
    if head.startswith(_OLE_MAGIC):
        # Legacy Office binaries and password-protected .docx/.xlsx both
        # use the OLE container; neither can be read without the password
        # or a converter.
        raise InvalidFileError(
            "This Office file is password-protected or in an old format. "
            "Remove the password and save it as .docx or .xlsx."
        )

    if fmt.file_type is FileType.PDF:
        if not head.startswith(b"%PDF-"):
            raise InvalidFileError("The file is not a valid PDF.")
    elif fmt.file_type is FileType.IMAGE:
        _check_image(head, source, fmt)
    else:
        _check_ooxml(head, source, fmt)
    return fmt


def _check_image(head: bytes, source: Any, fmt: UploadFormat) -> None:
    expected = {"png": b"\x89PNG\r\n\x1a\n", "jpg": b"\xff\xd8\xff"}[fmt.extension]
    if not head.startswith(expected):
        raise InvalidFileError(f"The file is not a valid {fmt.extension.upper()} image.")
    try:
        with Image.open(source) as image:
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise InvalidFileError("The image is too large (more than 80 megapixels).")
            image.verify()  # structure check without decoding every pixel
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise InvalidFileError("The image is damaged or could not be read.") from exc


def _check_ooxml(head: bytes, source: Any, fmt: UploadFormat) -> None:
    label = "Word" if fmt.file_type is FileType.WORD else "Excel"
    if not head.startswith(_ZIP_MAGIC):
        raise InvalidFileError(f"The file is not a valid {label} (.{fmt.extension}) document.")
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise InvalidFileError(f"The {label} file is damaged.") from exc
    names = {e.filename for e in entries}
    main_part = "word/document.xml" if fmt.file_type is FileType.WORD else "xl/workbook.xml"
    if "[Content_Types].xml" not in names or main_part not in names:
        raise InvalidFileError(f"The file is not a valid {label} (.{fmt.extension}) document.")
    if any(name.endswith("vbaProject.bin") for name in names):
        raise InvalidFileError(f"{label} files with macros are not accepted.")
    if len(entries) > MAX_ZIP_ENTRIES or sum(e.file_size for e in entries) > MAX_UNCOMPRESSED_BYTES:
        raise InvalidFileError(f"The {label} file is too large to process.")
