"""
Phase 6 integration tests against a real Qdrant: upsert/prune, parents
without vectors, current-version flags, tenant isolation, deletes, and the
schema/dimension checks.

Each test uses its own throwaway collection (deleted afterwards), so the
real `contract_chunks` collection is never touched.

    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import os
import uuid

import pytest
from qdrant_client.http import models as qm

from app.chunking.models import ChunkLevel
from app.core.config import Settings
from app.services.chunking_service import ChunkingOptions, chunk_document
from app.vectorstore.collections import (
    DENSE_VECTOR,
    CollectionMismatchError,
    check_dimension,
    ensure_collection,
)
from app.vectorstore.indexing import (
    IndexTarget,
    build_points,
    delete_document_points,
    get_parents,
    mark_current_version,
    upsert_version,
)
from app.vectorstore.qdrant import create_qdrant, tenant_filter
from tests.fake_embeddings import vector_for
from tests.unit.test_chunking import CONTRACT

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)
DIM = 768


@pytest.fixture
async def qdrant():
    client = create_qdrant(Settings())
    name = f"test_chunks_{uuid.uuid4().hex[:10]}"
    await ensure_collection(client, name, DIM)
    yield client, name
    await client.delete_collection(name)
    await client.close()


def _target(tenant="t-a", document="d-1", version="v-1", current=True) -> IndexTarget:
    return IndexTarget(
        tenant_id=tenant,
        document_id=document,
        version_id=version,
        version_label="v1",
        document_title="Acme MSA",
        contract_type="MSA",
        is_current=current,
        embedding_model="fake:hash-embed:768",
        chunker_version=1,
    )


def _points(target: IndexTarget, *, drop_last_child: bool = False):
    # Chunk IDs derive from the version id (Phase 5), as in production.
    result = chunk_document(
        CONTRACT, version_id=target.version_id, document_title="Acme MSA", options=ChunkingOptions()
    )
    children = result.children[:-1] if drop_last_child else result.children
    vectors = [vector_for(c.embedding_text) for c in children]
    return build_points(children, vectors, result.parents, target), result


async def _count(client, name, flt=None) -> int:
    return (await client.count(name, count_filter=flt, exact=True)).count


async def test_reindexing_overwrites_and_prunes_without_duplicates(qdrant):
    client, name = qdrant
    target = _target()
    points, result = _points(target)
    await upsert_version(client, name, target, points)
    assert await _count(client, name) == len(result.chunks)

    await upsert_version(client, name, target, points)  # retried job
    assert await _count(client, name) == len(result.chunks)

    fewer, _ = _points(target, drop_last_child=True)  # a chunk disappeared
    await upsert_version(client, name, target, fewer)
    assert await _count(client, name) == len(fewer)


async def test_parents_have_no_vectors_and_are_tenant_checked(qdrant):
    client, name = qdrant
    target = _target()
    points, result = _points(target)
    await upsert_version(client, name, target, points)

    hits = await client.query_points(
        name,
        query=vector_for(result.children[0].embedding_text),
        using=DENSE_VECTOR,
        query_filter=tenant_filter("t-a"),
        limit=100,
        with_payload=True,
    )
    assert hits.points and {p.payload["level"] for p in hits.points} == {"child"}
    assert hits.points[0].id == result.children[0].id  # exact text -> top hit

    parent_ids = [c.parent_id for c in result.children]
    parents = await get_parents(client, name, tenant_id="t-a", parent_ids=parent_ids)
    assert {p["level"] for p in parents} == {ChunkLevel.PARENT.value}
    assert await get_parents(client, name, tenant_id="t-b", parent_ids=parent_ids) == []


async def test_search_never_crosses_tenants(qdrant):
    client, name = qdrant
    for tenant in ("t-a", "t-b"):
        target = _target(tenant=tenant, version=f"v-{tenant}")
        points, _ = _points(target)
        await upsert_version(client, name, target, points)
    hits = await client.query_points(
        name,
        query=vector_for("anything"),
        using=DENSE_VECTOR,
        query_filter=tenant_filter("t-a"),
        limit=200,
        with_payload=True,
    )
    assert hits.points and {p.payload["tenant_id"] for p in hits.points} == {"t-a"}


async def test_new_version_becomes_current_and_old_version_stays_indexed(qdrant):
    client, name = qdrant
    v1, v2 = _target(version="v-1"), _target(version="v-2")
    for target in (v1, v2):
        points, _ = _points(target)
        await upsert_version(client, name, target, points)
    await mark_current_version(client, name, tenant_id="t-a", document_id="d-1", version_id="v-2")

    def current(version: str, flag: bool) -> qm.Filter:
        return qm.Filter(
            must=[
                *tenant_filter("t-a", version_ids=[version]).must,
                qm.FieldCondition(key="is_current", match=qm.MatchValue(value=flag)),
            ]
        )

    assert await _count(client, name, current("v-2", False)) == 0
    assert await _count(client, name, current("v-1", True)) == 0
    assert await _count(client, name, current("v-1", False)) > 0  # kept for comparisons


async def test_delete_document_removes_every_point_of_that_document_only(qdrant):
    client, name = qdrant
    for document in ("d-1", "d-2"):
        target = _target(document=document, version=f"v-{document}")
        points, _ = _points(target)
        await upsert_version(client, name, target, points)
    await delete_document_points(client, name, tenant_id="t-a", document_id="d-1")
    assert await _count(client, name, tenant_filter("t-a", document_ids=["d-1"])) == 0
    assert await _count(client, name, tenant_filter("t-a", document_ids=["d-2"])) > 0


async def test_existing_collection_gains_new_indexes_and_dimension_is_checked(qdrant):
    client, _ = qdrant
    legacy = f"test_legacy_{uuid.uuid4().hex[:8]}"
    # A collection as Phase 1 created it: no Phase 6 payload indexes.
    await client.create_collection(
        legacy,
        vectors_config={DENSE_VECTOR: qm.VectorParams(size=DIM, distance=qm.Distance.COSINE)},
    )
    try:
        await ensure_collection(client, legacy, DIM)
        schema = (await client.get_collection(legacy)).payload_schema
        assert {"level", "is_current", "embedding_model"} <= set(schema)

        await check_dimension(client, legacy, DIM)
        with pytest.raises(CollectionMismatchError, match="768-dimensional"):
            await check_dimension(client, legacy, 3072)
    finally:
        await client.delete_collection(legacy)
