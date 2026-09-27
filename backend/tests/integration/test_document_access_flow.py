"""Phase 20: document-level access inside one organization — restricted
documents, grants to users and roles, and the same rules in search (RAG),
duplicates and analysis. Uploads are tiny non-PDF bodies the worker rejects
quickly, so no model is called; the RAG test uses fake vectors."""

import os
import uuid
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.rag.hybrid_search import hybrid_search, retrieval_filter
from app.services.retrieval_service import RetrievalService
from app.vectorstore.collections import ensure_collection
from app.vectorstore.indexing import upsert_version
from app.vectorstore.qdrant import create_qdrant
from app.vectorstore.sparse import sparse_vector
from tests.fake_embeddings import vector_for
from tests.integration.conftest import PASSWORD, auth, new_email, register
from tests.integration.test_vector_index import _points, _target

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

API = "/api/v1"


def _pdf() -> bytes:
    return f"%PDF-1.7\n% {uuid.uuid4()}\ntrailer<<>>\n%%EOF\n".encode()


def _member(api, admin, cleanup, role_name: str) -> tuple[dict, str]:
    roles = {
        r["name"]: r["id"] for r in api.get(f"{API}/roles", headers=auth(admin)).json()["data"]
    }
    email = new_email(role_name.lower())
    cleanup.append(email)
    created = api.post(
        f"{API}/users",
        json={
            "email": email,
            "full_name": role_name,
            "password": PASSWORD,
            "role_id": roles[role_name],
        },
        headers=auth(admin),
    )
    assert created.status_code == 201, created.text
    tokens = api.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}).json()[
        "data"
    ]
    return tokens, created.json()["data"]["id"]


def _upload(api, tokens, data=None, **form):
    return api.post(
        f"{API}/documents/upload",
        headers=auth(tokens),
        files={"file": ("board-minutes.pdf", data or _pdf(), "application/pdf")},
        data={k: str(v) for k, v in form.items()},
    )


def _titles(api, tokens) -> set[str]:
    items = api.get(f"{API}/documents", headers=auth(tokens)).json()["data"]["items"]
    return {d["id"] for d in items}


def test_restricted_documents_are_visible_only_to_owner_grants_and_read_all(api, cleanup):
    admin, _ = register(api, cleanup, "Access Org")
    alice, _ = _member(api, admin, cleanup, "Employee")
    bob, bob_id = _member(api, admin, cleanup, "Employee")
    carol, _ = _member(api, admin, cleanup, "Viewer")

    uploaded = _upload(api, alice, visibility="RESTRICTED")
    assert uploaded.status_code == 202, uploaded.text
    doc = uploaded.json()["data"]["document"]
    assert doc["visibility"] == "RESTRICTED"
    doc_id = doc["id"]

    # Owner and document:read_all (Admin) see it; colleagues do not — not in
    # the list, the counts, by id, its access, or the question scope.
    assert doc_id in _titles(api, alice) and doc_id in _titles(api, admin)
    assert doc_id not in _titles(api, bob)
    assert api.get(f"{API}/documents/{doc_id}", headers=auth(bob)).status_code == 404
    assert api.get(f"{API}/documents/{doc_id}/status", headers=auth(bob)).status_code == 404
    assert api.get(f"{API}/documents/{doc_id}/access", headers=auth(bob)).status_code == 404
    facets_bob = api.get(f"{API}/documents/facets", headers=auth(bob)).json()["data"]
    assert facets_bob["all"] == 0
    job_id = uploaded.json()["data"]["job"]["id"]
    assert api.get(f"{API}/jobs/{job_id}", headers=auth(bob)).status_code == 404
    ask = api.post(
        f"{API}/query",
        json={"question": "What was decided?", "document_ids": [doc_id]},
        headers=auth(bob),
    )
    assert ask.status_code == 404

    # The uploader shares it with Bob, and with the Viewer role.
    roles = {
        r["name"]: r["id"]
        for r in api.get(f"{API}/documents/directory", headers=auth(alice)).json()["data"]["roles"]
    }
    shared = api.put(
        f"{API}/documents/{doc_id}/access",
        json={"visibility": "RESTRICTED", "user_ids": [bob_id], "role_ids": [roles["Viewer"]]},
        headers=auth(alice),
    )
    assert shared.status_code == 200, shared.text
    access = shared.json()["data"]
    assert {g["kind"] for g in access["grants"]} == {"user", "role"} and access["can_manage"]
    assert doc_id in _titles(api, bob) and doc_id in _titles(api, carol)

    # Seeing is not managing: Bob (no document:share, not the owner) cannot.
    assert (
        api.get(f"{API}/documents/{doc_id}/access", headers=auth(bob)).json()["data"]["can_manage"]
        is False
    )
    grab = api.put(
        f"{API}/documents/{doc_id}/access", json={"visibility": "ORGANIZATION"}, headers=auth(bob)
    )
    assert grab.status_code == 403

    # Back to everyone; grants are cleared.
    opened = api.put(
        f"{API}/documents/{doc_id}/access", json={"visibility": "ORGANIZATION"}, headers=auth(admin)
    )
    assert opened.json()["data"]["grants"] == []


def test_a_restricted_duplicate_is_refused_without_revealing_it(api, cleanup):
    admin, _ = register(api, cleanup, "Access Dup")
    alice, _ = _member(api, admin, cleanup, "Employee")
    bob, _ = _member(api, admin, cleanup, "Employee")
    data = _pdf()
    assert _upload(api, alice, data, visibility="RESTRICTED").status_code == 202
    again = _upload(api, bob, data)
    assert again.status_code == 409
    error = again.json()["error"]
    assert error["code"] == "DUPLICATE_DOCUMENT"
    assert not error.get("details")  # no id or title of a document Bob cannot see


def test_grants_only_name_people_and_roles_of_the_organization(api, cleanup):
    admin_a, _ = register(api, cleanup, "Access A")
    admin_b, _ = register(api, cleanup, "Access B")
    doc_id = _upload(api, admin_a, visibility="RESTRICTED").json()["data"]["document"]["id"]
    other = api.get(f"{API}/users/me", headers=auth(admin_b)).json()["data"]["id"]
    foreign = api.put(
        f"{API}/documents/{doc_id}/access",
        json={"visibility": "RESTRICTED", "user_ids": [other]},
        headers=auth(admin_a),
    )
    assert foreign.status_code == 404


async def test_search_never_returns_chunks_of_hidden_documents():
    """The RAG path (Phase 20): hidden documents are excluded inside the
    vector search, and their parents are dropped from context."""
    client = create_qdrant(Settings())
    name = f"test_chunks_{uuid.uuid4().hex[:10]}"
    await ensure_collection(client, name, 768)
    try:
        visible, hidden = (
            _target(document="d-visible", version="v-a"),
            _target(document="d-hidden", version="v-b"),
        )
        for target in (visible, hidden):
            points, _ = _points(target)
            await upsert_version(client, name, target, points)

        question = "termination notice period"
        found = await hybrid_search(
            client,
            name,
            dense=vector_for(question),
            sparse=sparse_vector(question, query=True),
            query_filter=retrieval_filter(
                "t-a", embedding_model="fake:hash-embed:768", exclude_document_ids=["d-hidden"]
            ),
            prefetch=50,
            limit=50,
        )
        assert found and {c.document_id for c in found} == {"d-visible"}

        resources = SimpleNamespace(qdrant=client, settings=Settings(qdrant_collection=name))
        retriever = RetrievalService(resources, hidden_document_ids=["d-hidden"])  # type: ignore[arg-type]
        _, hidden_chunks = _points(hidden)
        parents = await retriever.parents(
            tenant_id="t-a", parent_ids=[p.id for p in hidden_chunks.parents]
        )
        assert parents == {}
    finally:
        await client.delete_collection(name)
        await client.close()
