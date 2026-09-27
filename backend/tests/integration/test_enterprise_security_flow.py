"""Phase 24: complete document deletion and malware scanning, end to end.
No model is called: documents are created directly, and scanned uploads
use a stand-in clamd that answers like ClamAV (EICAR → FOUND)."""

import os
import socketserver
import struct
import threading
import uuid
from types import SimpleNamespace

import pytest
from arq.jobs import Job
from arq.jobs import JobStatus as ArqJobStatus
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import Settings
from app.db.database import Database
from app.db.models import (
    AuditLog,
    Conversation,
    Document,
    DocumentStatus,
    DocumentVersion,
    FileType,
    Message,
    MessageRole,
    User,
)
from app.main import create_app
from app.queue import QUEUE_NAME, create_queue
from app.services.document_service import REMOVED_ANSWER
from app.services.erasure import erase_document_data
from app.storage import create_storage, document_prefix
from tests.integration.conftest import auth, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

API = "/api/v1"
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


async def _org_of(email: str, db: Database) -> tuple[uuid.UUID, uuid.UUID]:
    async with db.session_factory() as s:
        user = await s.scalar(select(User).where(User.email == email))
        return user.organization_id, user.id


async def _document(db: Database, org_id: uuid.UUID, status: DocumentStatus) -> uuid.UUID:
    async with db.session_factory() as s:
        document = Document(
            organization_id=org_id, title="Lease", file_type=FileType.PDF, status=status
        )
        s.add(document)
        await s.flush()
        s.add(
            DocumentVersion(
                organization_id=org_id,
                document_id=document.id,
                version_number=1,
                label="v1",
                original_filename="lease.pdf",
                storage_key=f"{document_prefix(str(org_id), str(document.id))}v1/original.pdf",
                mime_type="application/pdf",
                size_bytes=4,
                sha256=uuid.uuid4().hex * 2,
                status=status,
            )
        )
        await s.commit()
        return document.id


async def test_deleting_a_document_removes_answers_citing_it_and_queues_the_purge(api, cleanup):
    settings = Settings()
    db = Database(settings)
    tokens, email = register(api, cleanup, "Erase Co")
    org_id, user_id = await _org_of(email, db)
    doomed = await _document(db, org_id, DocumentStatus.EMBEDDING)  # still processing
    kept = await _document(db, org_id, DocumentStatus.COMPLETED)

    async with db.session_factory() as s:
        conversation = Conversation(
            organization_id=org_id, user_id=user_id, document_ids=[str(doomed), str(kept)]
        )
        s.add(conversation)
        await s.flush()
        cite = lambda doc: [{"document_id": str(doc), "quote": "rent is 5,00,000"}]  # noqa: E731
        question = Message(
            organization_id=org_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="What is the rent?",
            citations=[],
        )
        citing = Message(
            organization_id=org_id,
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="The rent is 5,00,000 [1].",
            citations=cite(doomed),
        )
        other = Message(
            organization_id=org_id,
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="The term is 3 years [1].",
            citations=cite(kept),
        )
        s.add_all([question, citing, other])
        await s.commit()
        ids = (conversation.id, question.id, citing.id, other.id)

    response = api.delete(f"{API}/documents/{doomed}", headers=auth(tokens))
    assert response.status_code in (200, 204), response.text

    async with db.session_factory() as s:
        conversation = await s.get(Conversation, ids[0])
        question, citing, other = [await s.get(Message, i) for i in ids[1:]]
        assert conversation.document_ids == [str(kept)]
        assert question.content == "What is the rent?"  # the user's own words stay
        assert (citing.content, citing.citations) == (REMOVED_ANSWER, [])
        assert other.content == "The term is 3 years [1]."
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.organization_id == org_id, AuditLog.action == "document.delete"
            )
        )
        assert audit.metadata_["answers_removed"] == 1

    # Purge queued now, and again after in-flight work could have finished.
    queue = create_queue(settings)
    now = Job(f"purge-doc:{doomed}", queue, _queue_name=QUEUE_NAME)
    later = Job(
        f"purge-doc:{doomed}:deferred-{settings.job_stale_running_s}", queue, _queue_name=QUEUE_NAME
    )
    assert await now.status() is not ArqJobStatus.not_found
    assert await later.status() is ArqJobStatus.deferred
    await queue.zrem(QUEUE_NAME, later.job_id)
    await queue.delete(f"arq:job:{later.job_id}")
    await queue.aclose()
    await queue.connection_pool.disconnect()
    await db.dispose()


async def test_erasing_a_document_clears_its_files_and_derived_caches_only(tmp_path):
    settings = Settings(local_storage_path=str(tmp_path))
    storage = create_storage(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    tenant, other_tenant, doc = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await storage.put(f"{document_prefix(tenant, doc)}v1/parsed.json", b"{}", "application/json")
    keys = {ns: f"ciq:{tenant}:{ns}:k" for ns in ("answer", "mm", "emb", "rl")}
    foreign = f"ciq:{other_tenant}:answer:k"
    for key in [*keys.values(), foreign]:
        await redis.set(key, "x", ex=60)

    class _Qdrant:
        deleted = []

        async def delete(self, collection, points_selector, wait):
            self.deleted.append(points_selector)

    resources = SimpleNamespace(settings=settings, storage=storage, redis=redis, qdrant=_Qdrant())
    result = await erase_document_data(resources, tenant, doc)  # type: ignore[arg-type]

    assert result["cache_keys"] == 3
    assert not await storage.exists(f"{document_prefix(tenant, doc)}v1/parsed.json")
    assert [bool(await redis.exists(keys[ns])) for ns in ("answer", "mm", "emb")] == [0, 0, 0]
    assert await redis.exists(keys["rl"])  # rate-limit windows are not document content
    assert await redis.exists(foreign)  # another organization is untouched
    assert len(_Qdrant.deleted) == 1
    await redis.delete(keys["rl"], foreign)
    await redis.aclose()


class _FakeClamd(socketserver.BaseRequestHandler):
    def handle(self):
        assert self.request.recv(10) == b"zINSTREAM\0"
        body, stream = b"", self.request.makefile("rb")
        while size := struct.unpack(">I", stream.read(4))[0]:
            body += stream.read(size)
        verdict = "Eicar-Test-Signature FOUND" if b"EICAR" in body else "OK"
        self.request.sendall(f"stream: {verdict}\0".encode())


@pytest.fixture
def clamd():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _FakeClamd)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def _upload(client, tokens, data: bytes):
    return client.post(
        f"{API}/documents/upload",
        headers=auth(tokens),
        files={"file": ("contract.pdf", data, "application/pdf")},
    )


async def test_an_infected_upload_is_refused_audited_and_never_stored(api, cleanup, clamd):
    tokens, email = register(api, cleanup, "Scan Co")
    settings = Settings(malware_scan="clamav", clamav_host="127.0.0.1", clamav_port=clamd)
    with TestClient(create_app(settings)) as client:
        infected = b"%PDF-1.7\n% " + EICAR + b"\ntrailer<<>>\n%%EOF\n"
        response = _upload(client, tokens, infected)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "MALWARE_DETECTED"

    db = Database(Settings())
    org_id, _ = await _org_of(email, db)
    async with db.session_factory() as s:
        assert await s.scalar(select(Document).where(Document.organization_id == org_id)) is None
        blocked = await s.scalar(
            select(AuditLog).where(
                AuditLog.organization_id == org_id, AuditLog.action == "document.upload_blocked"
            )
        )
        assert blocked.metadata_["signature"] == "Eicar-Test-Signature"
    await db.dispose()


async def test_uploads_fail_closed_when_the_scanner_is_down(api, cleanup):
    tokens, email = register(api, cleanup, "Closed Co")
    settings = Settings(malware_scan="clamav", clamav_host="127.0.0.1", clamav_port=1)
    with TestClient(create_app(settings)) as client:
        response = _upload(client, tokens, b"%PDF-1.7\n%clean\ntrailer<<>>\n%%EOF\n")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    db = Database(Settings())
    org_id, _ = await _org_of(email, db)
    async with db.session_factory() as s:
        assert await s.scalar(select(Document).where(Document.organization_id == org_id)) is None
    await db.dispose()
