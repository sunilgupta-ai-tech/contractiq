"""
End-to-end contract analysis (Phase 10) against real PostgreSQL, Redis and
Qdrant: clause extraction (cached), summary, comparison of two versions,
risk analysis, portfolio summary, and tenant isolation.

The embedding model and the LLM are deterministic fakes; the LLM "reads"
the excerpts it is shown, so extracted facts really come from each version.

    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import copy
import json
import os
import re
import uuid

import anyio
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.database import Database
from app.db.models import ContractType, Document, DocumentStatus, DocumentVersion
from app.llm.base import LLMResult
from app.main import create_app
from app.services.chunking_service import ChunkingOptions, chunk_document
from app.vectorstore.indexing import (
    IndexTarget,
    build_points,
    mark_current_version,
    upsert_version,
)
from app.vectorstore.qdrant import create_qdrant
from tests.fake_embeddings import FakeEmbeddings, vector_for
from tests.integration.conftest import auth, register
from tests.unit.test_chunking import CONTRACT

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)
_EXCERPT = re.compile(r'cite="(\d+)">\n(.*?)\n</untrusted_document_', re.DOTALL)
_DAYS = {"thirty": 30, "ninety": 90}


class ReadingLLM:
    """Finds the termination-for-convenience clause in the excerpts it is
    given and reports its notice period; says "not found" for other topics."""

    name, model = "fake", "reading-llm"

    def __init__(self):
        self.calls = 0

    async def generate(self, messages, *, temperature=0.0, max_tokens=1024):
        self.calls += 1
        prompt = messages[-1].content
        if prompt.startswith("Contract:"):
            reply = {
                "overview": "The customer may terminate for convenience [1].",
                "obligations": [],
            }
        elif prompt.startswith("Topic: Termination for convenience"):
            reply = {"found": False}
            for number, text in _EXCERPT.findall(prompt):
                sentence = next(
                    (s for s in text.splitlines() if "terminate for convenience" in s), None
                )
                if sentence:
                    days = next(v for word, v in _DAYS.items() if word in sentence)
                    reply = {
                        "found": True,
                        "excerpt": int(number),
                        "quote": sentence,
                        "attributes": {"permitted": True, "notice_days": days},
                    }
                    break
        else:
            reply = {"found": False}
        return LLMResult(text=json.dumps(reply), model=self.model)

    async def aclose(self):
        return None


def _version_doc(notice_word: str):
    doc = copy.deepcopy(CONTRACT)
    for block in doc.pages[0].blocks:
        block.text = block.text.replace("ninety", notice_word)
    return doc


@pytest.fixture
def stack():
    settings = Settings(qdrant_collection=f"test_analysis_{uuid.uuid4().hex[:10]}")
    app = create_app(settings)
    llm = ReadingLLM()
    with TestClient(app) as client:
        resources = app.state.resources
        resources._embeddings = FakeEmbeddings(768)
        resources._llm = llm
        yield client, settings, llm

    async def drop():
        qdrant = create_qdrant(settings)
        await qdrant.delete_collection(settings.qdrant_collection)
        await qdrant.close()

    anyio.run(drop)


def _seed(settings: Settings, tenant_id: str) -> dict[str, str]:
    """A processed document with v1 (30 days' notice) and v2 (90 days, current),
    both indexed, plus a second document still processing."""
    ids = {k: str(uuid.uuid4()) for k in ("doc", "v1", "v2", "busy_doc", "busy_v")}

    async def run():
        db = Database(settings)
        async with db.session_factory() as s:
            tenant = uuid.UUID(tenant_id)
            s.add(
                Document(
                    id=uuid.UUID(ids["doc"]),
                    organization_id=tenant,
                    title="Acme MSA",
                    contract_type=ContractType.MSA,
                    status=DocumentStatus.COMPLETED,
                    current_version_id=uuid.UUID(ids["v2"]),
                )
            )
            s.add(
                Document(
                    id=uuid.UUID(ids["busy_doc"]),
                    organization_id=tenant,
                    title="Beta NDA",
                    status=DocumentStatus.CHUNKING,
                    current_version_id=uuid.UUID(ids["busy_v"]),
                )
            )
            await s.flush()
            for number, (key, doc_key, status) in enumerate(
                [
                    ("v1", "doc", DocumentStatus.COMPLETED),
                    ("v2", "doc", DocumentStatus.COMPLETED),
                    ("busy_v", "busy_doc", DocumentStatus.CHUNKING),
                ],
                start=1,
            ):
                s.add(
                    DocumentVersion(
                        id=uuid.UUID(ids[key]),
                        organization_id=tenant,
                        document_id=uuid.UUID(ids[doc_key]),
                        version_number=number,
                        label=key,
                        original_filename="c.pdf",
                        storage_key=f"tenants/{tenant_id}/x/{key}.pdf",
                        mime_type="application/pdf",
                        size_bytes=1,
                        sha256=f"{number}" * 64,
                        status=status,
                    )
                )
            await s.commit()
        await db.dispose()

        qdrant = create_qdrant(settings)
        for key, word in (("v1", "thirty"), ("v2", "ninety")):
            result = chunk_document(
                _version_doc(word),
                version_id=ids[key],
                document_title="Acme MSA",
                options=ChunkingOptions(),
            )
            target = IndexTarget(
                tenant_id=tenant_id,
                document_id=ids["doc"],
                version_id=ids[key],
                version_label=key,
                document_title="Acme MSA",
                contract_type="MSA",
                is_current=key == "v2",
                embedding_model="fake:hash-embed:768",
                chunker_version=2,
            )
            vectors = [vector_for(c.embedding_text) for c in result.children]
            points = build_points(result.children, vectors, result.parents, target)
            await upsert_version(qdrant, settings.qdrant_collection, target, points)
        await mark_current_version(
            qdrant,
            settings.qdrant_collection,
            tenant_id=tenant_id,
            document_id=ids["doc"],
            version_id=ids["v2"],
        )
        await qdrant.close()

    anyio.run(run)
    return ids


def _poster(client: TestClient, tokens: dict):
    def post(path: str, body: dict):
        return client.post(f"/api/v1/contracts/{path}", headers=auth(tokens), json=body)

    return post


def _tenant_of(client: TestClient, tokens: dict) -> str:
    return client.get("/api/v1/users/me", headers=auth(tokens)).json()["data"]["organization_id"]


def test_analysis_end_to_end(stack, cleanup):
    client, settings, llm = stack
    tokens, _ = register(client, cleanup, "Analysis Org")
    ids = _seed(settings, _tenant_of(client, tokens))
    post = _poster(client, tokens)

    # Extraction reads the current version (v2) and is cached.
    response = post("extract-clauses", {"document_id": ids["doc"]})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["version"]["version_label"] == "v2" and data["cached"] is False
    termination = next(c for c in data["clauses"] if c["topic"] == "termination_convenience")
    assert termination["found"] and termination["verified"]
    assert termination["attributes"]["notice_days"] == 90
    assert termination["evidence"]["page"] == 1 and termination["evidence"]["regions"]
    calls = llm.calls
    again = post("extract-clauses", {"document_id": ids["doc"]}).json()["data"]
    assert again["cached"] is True and llm.calls == calls

    # Summary: cited overview and computed key terms.
    summary = post("summarize", {"document_id": ids["doc"]}).json()["data"]
    assert summary["overview"].endswith("[1].") and summary["citations"][0]["page"] == 1
    assert {"label": "Termination notice", "value": "90 days"}.items() <= summary["key_terms"][
        0
    ].items()

    # Comparison v1 -> v2: the notice change is found and carries the long-notice risk.
    compare = post("compare", {"left_version_id": ids["v1"], "right_version_id": ids["v2"]})
    assert compare.status_code == 200, compare.text
    rows = {r["topic"]: r for r in compare.json()["data"]["rows"]}
    row = rows["termination_convenience"]
    assert row["diff"] == "changed" and row["note"] == "Notice days: 30 → 90."
    assert row["risk"] == "medium"

    # Risk analysis over the tenant's processed documents; the busy one is pending.
    risk = post("risk-analysis", {}).json()["data"]
    assert risk["documents_analyzed"] == 1
    rules = {f["rule"] for f in risk["findings"]}
    assert "long_termination_notice" in rules and "no_liability_cap" in rules
    notice = next(f for f in risk["findings"] if f["rule"] == "long_termination_notice")
    assert notice["version_label"] == "v2" and notice["page"] == 1 and notice["excerpt"]
    assert risk["disclaimer"]
    assert post("risk-analysis", {"document_ids": [ids["busy_doc"]]}).json()["data"][
        "pending_document_ids"
    ] == [ids["busy_doc"]]

    portfolio = post("portfolio-summary", {}).json()["data"]
    assert [d["version"]["document_id"] for d in portfolio["documents"]] == [ids["doc"]]
    assert portfolio["risk_totals"]["high"] >= 1

    # Not processed yet -> 409; same version twice -> 422.
    assert post("summarize", {"document_id": ids["busy_doc"]}).status_code == 409
    same = post("compare", {"left_version_id": ids["v1"], "right_version_id": ids["v1"]})
    assert same.status_code == 422


def test_other_tenants_documents_are_not_found(stack, cleanup):
    client, settings, _ = stack
    owner, _ = register(client, cleanup, "Owner Org")
    ids = _seed(settings, _tenant_of(client, owner))
    other, _ = register(client, cleanup, "Other Org")
    post = _poster(client, other)

    assert post("extract-clauses", {"document_id": ids["doc"]}).status_code == 404
    assert (
        post("summarize", {"document_id": ids["doc"], "version_id": ids["v1"]}).status_code == 404
    )
    assert (
        post("compare", {"left_version_id": ids["v1"], "right_version_id": ids["v2"]}).status_code
        == 404
    )
    assert post("risk-analysis", {"document_ids": [ids["doc"]]}).status_code == 404
    assert post("risk-analysis", {"version_id": ids["v2"]}).status_code == 404
    # With no ids, the other tenant simply has nothing to analyse.
    empty = post("risk-analysis", {}).json()["data"]
    assert empty["findings"] == [] and empty["documents_analyzed"] == 0
