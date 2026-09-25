"""
End-to-end POST /query against real PostgreSQL, Redis and Qdrant.

The embedding model and the LLM are replaced by deterministic fakes (no API
key or network needed); everything else is the production path: auth,
tenant-scoped hybrid search in a throwaway Qdrant collection, reranking,
small-to-big context, citation checking and conversation persistence.

    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import os
import uuid

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.database import Database
from app.db.models import Message
from app.llm.base import LLMResult
from app.main import create_app
from app.services.chunking_service import ChunkingOptions, chunk_document
from app.vectorstore.indexing import IndexTarget, build_points, upsert_version
from app.vectorstore.qdrant import create_qdrant
from tests.fake_embeddings import FakeEmbeddings, vector_for
from tests.integration.conftest import PASSWORD, auth, new_email, register
from tests.unit.test_chunking import CONTRACT

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)
QUESTION = "What does clause 8.3 say about how notices must be given?"


class ScriptedLLM:
    """Answers citing block [1], plus an invented [9] that must be removed."""

    name, model = "fake", "scripted-llm"

    def __init__(self):
        self.calls = []

    async def generate(self, messages, *, temperature=0.0, max_tokens=1024):
        self.calls.append(messages)
        return LLMResult(
            text="Notices must be given in writing [1]. This is well settled [9].",
            model=self.model,
            prompt_tokens=100,
            completion_tokens=12,
        )

    async def aclose(self):
        return None


@pytest.fixture
def stack():
    """App on a throwaway collection, with fake embeddings + LLM injected."""
    settings = Settings(qdrant_collection=f"test_query_{uuid.uuid4().hex[:10]}")
    app = create_app(settings)
    llm = ScriptedLLM()
    with TestClient(app) as client:  # startup creates the collection
        resources = app.state.resources
        resources._embeddings = FakeEmbeddings(768)
        resources._llm = llm
        yield client, settings, llm
        # Delete the throwaway collection with a fresh client (the app's own
        # client belongs to the TestClient's event loop).

    async def drop():
        qdrant = create_qdrant(settings)
        await qdrant.delete_collection(settings.qdrant_collection)
        await qdrant.close()

    anyio.run(drop)


def _index_contract(settings: Settings, tenant_id: str) -> str:
    """Index the sample contract for a tenant, as the worker would."""
    document_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    result = chunk_document(
        CONTRACT, version_id=version_id, document_title="Acme MSA", options=ChunkingOptions()
    )
    target = IndexTarget(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        version_label="v1",
        document_title="Acme MSA",
        contract_type="MSA",
        is_current=True,
        embedding_model="fake:hash-embed:768",
        chunker_version=1,
    )
    vectors = [vector_for(c.embedding_text) for c in result.children]

    async def run():
        qdrant = create_qdrant(settings)
        points = build_points(result.children, vectors, result.parents, target)
        await upsert_version(qdrant, settings.qdrant_collection, target, points)
        await qdrant.close()

    anyio.run(run)
    return document_id


def _tenant_of(client: TestClient, tokens: dict) -> str:
    return client.get("/api/v1/users/me", headers=auth(tokens)).json()["data"]["organization_id"]


def test_answer_is_cited_scoped_and_persisted(stack, cleanup):
    client, settings, llm = stack
    tokens, _ = register(client, cleanup, "Query Org A")
    document_id = _index_contract(settings, _tenant_of(client, tokens))

    response = client.post("/api/v1/query", headers=auth(tokens), json={"question": QUESTION})
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    # Invented citation [9] removed; [1] resolved to the clause that was asked about.
    assert data["answer"] == "Notices must be given in writing [1]. This is well settled."
    citation = data["citations"][0]
    assert (citation["index"], citation["document_id"]) == (1, document_id)
    # The sample's short clauses 8.1-8.3 share one chunk; the citation lists them all.
    assert "8.3" in citation["clauses"] and citation["section"] == "8"
    assert citation["quote"] and citation["page"] >= 1
    assert data["insufficient_evidence"] is False and data["model"] == "scripted-llm"
    # Agent mode (default): a standalone question needs no planning call.
    assert data["mode"] == "agent" and data["agent"]["queries"] == [QUESTION]
    assert [s["key"] for s in data["steps"]] == [
        "understand", "retrieve", "rerank", "validate", "context", "generate", "cite",
    ]  # fmt: skip
    assert len(llm.calls) == 1

    # The LLM read the whole section (small-to-big), inside the data delimiters.
    prompt = llm.calls[0][-1].content
    assert "untrusted_document_" in prompt and "8.1 Either party" in prompt

    # Question + answer stored in the new conversation.
    async def count_messages():
        db = Database(Settings())
        async with db.session_factory() as session:
            n = await session.scalar(
                select(func.count()).where(Message.conversation_id == data["conversation_id"])
            )
        await db.dispose()
        return n

    assert anyio.run(count_messages) == 2


def test_other_tenants_contracts_are_never_searched(stack, cleanup):
    client, settings, llm = stack
    owner, _ = register(client, cleanup, "Query Owner")
    _index_contract(settings, _tenant_of(client, owner))
    stranger, _ = register(client, cleanup, "Query Stranger")

    data = client.post("/api/v1/query", headers=auth(stranger), json={"question": QUESTION}).json()[
        "data"
    ]
    assert data["insufficient_evidence"] is True and data["citations"] == []
    assert llm.calls == []  # nothing found -> the model was never called


def test_scope_and_conversation_ownership_are_enforced(stack, cleanup):
    client, settings, llm = stack
    admin, _ = register(client, cleanup, "Query Org C")
    _index_contract(settings, _tenant_of(client, admin))

    unknown_doc = client.post(
        "/api/v1/query",
        headers=auth(admin),
        json={"question": QUESTION, "document_ids": [str(uuid.uuid4())]},
    )
    assert unknown_doc.status_code == 404

    first = client.post("/api/v1/query", headers=auth(admin), json={"question": QUESTION})
    conversation_id = first.json()["data"]["conversation_id"]

    # Follow-up in the same conversation: previous turn is sent as history.
    follow = client.post(
        "/api/v1/query",
        headers=auth(admin),
        json={"question": "And what about clause 8.1?", "conversation_id": conversation_id},
    )
    assert follow.status_code == 200
    roles = [m.role for m in llm.calls[-1]]
    assert roles == ["system", "user", "assistant", "user"]
    assert llm.calls[-1][1].content == QUESTION

    # A colleague in the same organization cannot continue someone else's conversation.
    email = new_email("colleague")
    client.post(
        "/api/v1/users",
        headers=auth(admin),
        json={"email": email, "full_name": "C", "password": PASSWORD, "role": "ANALYST"},
    )
    colleague = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).json()["data"]
    hijack = client.post(
        "/api/v1/query",
        headers=auth(colleague),
        json={"question": QUESTION, "conversation_id": conversation_id},
    )
    assert hijack.status_code == 404


def test_fast_mode_skips_the_agent(stack, cleanup):
    client, settings, llm = stack
    tokens, _ = register(client, cleanup, "Query Org Fast")
    _index_contract(settings, _tenant_of(client, tokens))
    data = client.post(
        "/api/v1/query", headers=auth(tokens), json={"question": QUESTION, "mode": "fast"}
    ).json()["data"]
    assert data["mode"] == "fast" and data["agent"] is None
    steps = [s["key"] for s in data["steps"]]
    assert steps == ["retrieve", "rerank", "context", "generate", "cite"]
    assert data["citations"] and data["insufficient_evidence"] is False
