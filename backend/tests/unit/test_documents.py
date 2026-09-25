import io
import uuid

import pytest
from fastapi import UploadFile
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.exceptions import FileTooLargeError, InvalidFileError
from app.core.security import Role, create_token
from app.main import create_app
from app.services.document_service import (
    clean_filename,
    default_title,
    read_limited,
    validate_pdf,
)

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


# --- Validation ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\ada\\Contracts\\MSA v2.pdf", "MSA v2.pdf"),
        ("ev\x00il\x1b[31m.pdf", "evil[31m.pdf"),
        ("", "document.pdf"),
        (None, "document.pdf"),
        ("a" * 300 + ".pdf", "a" * 255),
    ],
)
def test_clean_filename_strips_paths_and_control_chars(raw, expected):
    assert clean_filename(raw) == expected


@pytest.mark.parametrize("content_type", ["application/pdf", "application/octet-stream", None])
def test_valid_pdf_accepted(content_type):
    validate_pdf("MSA.PDF", content_type, PDF)


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "message"),
    [
        ("contract.docx", "application/pdf", PDF, "Only PDF"),
        ("contract.pdf", "text/html", PDF, "Only PDF"),
        ("contract.pdf", "application/pdf", b"", "empty"),
        ("contract.pdf", "application/pdf", b"MZ\x90\x00 not a pdf", "not a valid PDF"),
    ],
)
def test_invalid_uploads_rejected(filename, content_type, data, message):
    with pytest.raises(InvalidFileError, match=message):
        validate_pdf(filename, content_type, data)


async def test_read_limited_stops_at_the_limit():
    upload = UploadFile(io.BytesIO(b"x" * 3000), filename="big.pdf")
    with pytest.raises(FileTooLargeError):
        await read_limited(upload, max_bytes=2048)
    ok = UploadFile(io.BytesIO(PDF), filename="ok.pdf")
    assert await read_limited(ok, max_bytes=2048) == PDF


def test_default_title_from_filename():
    assert default_title("Master_Services  Agreement.PDF") == "Master Services Agreement"
    assert default_title(".pdf") == "Untitled contract"


# --- HTTP layer --------------------------------------------------------------------


def _auth(settings, role):
    token = create_token(
        settings, subject=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), role=role
    )
    return {"Authorization": f"Bearer {token}"}


async def test_oversized_request_rejected_before_body_is_read():
    app = create_app(Settings(app_env="development", max_upload_size_mb=1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post("/api/v1/documents/upload", content=b"x" * (3 * 1024 * 1024))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/documents"),
        ("GET", f"/api/v1/documents/{uuid.uuid4()}"),
        ("GET", f"/api/v1/documents/{uuid.uuid4()}/status"),
        ("DELETE", f"/api/v1/documents/{uuid.uuid4()}"),
        ("GET", f"/api/v1/jobs/{uuid.uuid4()}"),
    ],
)
async def test_document_routes_require_a_token(client, method, path):
    assert (await client.request(method, path)).status_code == 401


async def test_viewers_cannot_upload(client, settings):
    response = await client.post(
        "/api/v1/documents/upload",
        headers=_auth(settings, Role.VIEWER),
        files={"file": ("msa.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.VIEWER, Role.ANALYST])
async def test_only_managers_and_admins_delete(client, settings, role):
    response = await client.delete(
        f"/api/v1/documents/{uuid.uuid4()}", headers=_auth(settings, role)
    )
    assert response.status_code == 403
