"""
Phase 6 unit tests: Gemini/Ollama clients (with a mocked HTTP layer),
provider selection, the embedding service (batching, retries, cache),
sparse keyword vectors and Qdrant point building.

The Gemini tests check the exact request our client sends against Google's
documented batchEmbedContents format; no real API call is made.
"""

import json
import math

import httpx
import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.chunking.models import ChunkLevel
from app.core.config import Settings
from app.llm.base import EmbeddingConfigError, EmbeddingError, EmbeddingTask
from app.llm.factory import create_embeddings
from app.llm.gemini import GeminiEmbeddings
from app.llm.ollama import OllamaEmbeddings
from app.services.chunking_service import ChunkingOptions, chunk_document
from app.services.embedding_service import EmbeddingService
from app.vectorstore.indexing import IndexTarget, build_points
from app.vectorstore.sparse import sparse_vector, term_index, tokenize
from tests.fake_embeddings import FakeEmbeddings, vector_for
from tests.unit.test_chunking import CONTRACT

DIM = 8


def _gemini(handler, dimension=DIM):
    return GeminiEmbeddings(
        "test-key", "gemini-embedding-001", dimension, transport=httpx.MockTransport(handler)
    )


def _ok(count, dimension=DIM, value=2.0):
    return httpx.Response(200, json={"embeddings": [{"values": [value] * dimension}] * count})


# --- Gemini client ---------------------------------------------------------------------


async def test_gemini_request_format_and_normalised_vectors():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return _ok(2)

    vectors = await _gemini(handler).embed(["clause one", "clause two"])
    assert seen["url"].endswith("/v1beta/models/gemini-embedding-001:batchEmbedContents")
    assert "test-key" not in seen["url"] and seen["key"] == "test-key"  # key only in header
    first = seen["body"]["requests"][0]
    assert first["model"] == "models/gemini-embedding-001"
    assert first["content"] == {"parts": [{"text": "clause one"}]}
    assert first["taskType"] == "RETRIEVAL_DOCUMENT" and first["outputDimensionality"] == DIM
    assert math.isclose(math.sqrt(sum(v * v for v in vectors[0])), 1.0)  # unit length


async def test_gemini_query_task_type():
    seen = {}

    def handler(request):
        seen["task"] = json.loads(request.content)["requests"][0]["taskType"]
        return _ok(1)

    await _gemini(handler).embed(["what is the notice period?"], task=EmbeddingTask.QUERY)
    assert seen["task"] == "RETRIEVAL_QUERY"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, EmbeddingError),  # rate limited -> retryable
        (503, EmbeddingError),
        (400, EmbeddingConfigError),  # bad request -> not retryable
        (403, EmbeddingConfigError),  # bad key
    ],
)
async def test_gemini_error_classification(status, error):
    client = _gemini(lambda r: httpx.Response(status, json={"error": {"message": "secret text"}}))
    with pytest.raises(error) as info:
        await client.embed(["x"])
    assert type(info.value) is error
    assert "secret text" not in str(info.value)  # provider bodies never leak into errors


async def test_gemini_network_failure_is_retryable():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(EmbeddingError):
        await _gemini(handler).embed(["x"])


async def test_gemini_rejects_wrong_dimension_and_oversized_batches():
    with pytest.raises(EmbeddingConfigError, match="3072-dimensional"):
        await _gemini(lambda r: _ok(1, dimension=3072)).embed(["x"])
    with pytest.raises(EmbeddingConfigError, match="at most 100"):
        await _gemini(lambda r: _ok(101)).embed(["x"] * 101)


# --- Ollama client & provider selection --------------------------------------------------


@pytest.mark.parametrize(
    ("model", "task", "prefix"),
    [
        ("nomic-embed-text", EmbeddingTask.DOCUMENT, "search_document: "),
        ("nomic-embed-text", EmbeddingTask.QUERY, "search_query: "),
        ("mxbai-embed-large", EmbeddingTask.DOCUMENT, ""),
    ],
)
async def test_ollama_task_prefixes_for_nomic_models(model, task, prefix):
    seen = {}

    def handler(request):
        seen["input"] = json.loads(request.content)["input"]
        return httpx.Response(200, json={"embeddings": [[1.0] * DIM]})

    client = OllamaEmbeddings("http://ollama", model, DIM, transport=httpx.MockTransport(handler))
    await client.embed(["notice period"], task=task)
    assert seen["input"] == [prefix + "notice period"]


def test_factory_picks_provider_and_requires_gemini_key():
    with pytest.raises(EmbeddingConfigError, match="GEMINI_API_KEY"):
        create_embeddings(Settings(embedding_provider="gemini", gemini_api_key=None))
    gemini = create_embeddings(
        Settings(
            embedding_provider="gemini",
            embedding_model="gemini-embedding-001",
            gemini_api_key="k",
        )
    )
    assert isinstance(gemini, GeminiEmbeddings) and gemini.model == "gemini-embedding-001"
    ollama = create_embeddings(
        Settings(embedding_provider="ollama", embedding_model="nomic-embed-text")
    )
    assert isinstance(ollama, OllamaEmbeddings)


def test_production_refuses_gemini_without_key():
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        Settings(
            app_env="production",
            jwt_secret_key="x" * 64,
            embedding_provider="gemini",
            gemini_api_key=None,
        )


# --- EmbeddingService: batching, cache, retries -------------------------------------------


class FakeRedis:
    def __init__(self, fail=False):
        self.data: dict[str, str] = {}
        self.fail = fail

    async def mget(self, keys):
        if self.fail:
            raise RedisConnectionError("down")
        return [self.data.get(k) for k in keys]

    def pipeline(self, transaction=False):
        return _FakePipe(self)


class _FakePipe:
    def __init__(self, redis):
        self.redis, self.ops = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def set(self, key, value, ex=None):
        self.ops.append((key, value))

    async def execute(self):
        if self.redis.fail:
            raise RedisConnectionError("down")
        self.redis.data.update(self.ops)


def _service(provider, redis=None, **overrides):
    settings = Settings(embedding_batch_size=2, embedding_max_retries=3, **overrides)
    delays: list[float] = []

    async def no_sleep(seconds):
        delays.append(seconds)

    return EmbeddingService(provider, settings, redis, sleep=no_sleep), delays


async def test_batches_preserve_order():
    provider = FakeEmbeddings(DIM)
    service, _ = _service(provider)
    texts = [f"clause {i}" for i in range(5)]
    vectors, stats = await service.embed_documents(texts, tenant_id="t1")
    assert [len(b) for b in provider.calls] == [2, 2, 1]  # EMBEDDING_BATCH_SIZE=2
    assert vectors == [vector_for(t, DIM) for t in texts]
    assert stats.api_calls == 3 and stats.cache_hits == 0


async def test_cache_skips_known_texts_but_only_within_a_tenant():
    provider, redis = FakeEmbeddings(DIM), FakeRedis()
    service, _ = _service(provider, redis)
    await service.embed_documents(["8.1 Termination", "8.2 Notice"], tenant_id="t1")
    provider.calls.clear()

    vectors, stats = await service.embed_documents(
        ["8.1 Termination", "8.3 New clause"], tenant_id="t1"
    )
    assert stats.cache_hits == 1 and provider.calls == [["8.3 New clause"]]
    assert math.isclose(vectors[0][0], vector_for("8.1 Termination", DIM)[0], rel_tol=1e-6)

    _, other = await service.embed_documents(["8.1 Termination"], tenant_id="t2")
    assert other.cache_hits == 0  # cache keys are tenant-scoped


async def test_redis_outage_degrades_to_no_cache():
    service, _ = _service(FakeEmbeddings(DIM), FakeRedis(fail=True))
    vectors, stats = await service.embed_documents(["a", "b"], tenant_id="t1")
    assert len(vectors) == 2 and stats.cache_hits == 0


class FlakyProvider(FakeEmbeddings):
    def __init__(self, failures, error=EmbeddingError):
        super().__init__(DIM)
        self.failures, self.error = failures, error

    async def embed(self, texts, *, task=EmbeddingTask.DOCUMENT):
        if self.failures:
            self.failures -= 1
            raise self.error("429")
        return await super().embed(texts, task=task)


async def test_temporary_errors_are_retried_with_backoff():
    service, delays = _service(FlakyProvider(failures=2))
    _, stats = await service.embed_documents(["x"], tenant_id="t1")
    assert stats.retries == 2 and len(delays) == 2
    assert 1 <= delays[0] < 2 <= delays[1] < 3  # 1s then 2s, plus <1s jitter


async def test_retries_are_bounded():
    service, delays = _service(FlakyProvider(failures=10))
    with pytest.raises(EmbeddingError):
        await service.embed_documents(["x"], tenant_id="t1")
    assert len(delays) == 3  # EMBEDDING_MAX_RETRIES=3


async def test_config_errors_are_not_retried():
    service, delays = _service(FlakyProvider(failures=1, error=EmbeddingConfigError))
    with pytest.raises(EmbeddingConfigError):
        await service.embed_documents(["x"], tenant_id="t1")
    assert delays == []


# --- Sparse keyword vectors ------------------------------------------------------------


def test_tokens_keep_clause_numbers_and_amounts():
    tokens = tokenize("Under clause 8.3, the cap is 5,000,000 and the Supplier shall not ...")
    assert "8.3" in tokens and "5,000,000" in tokens and "not" in tokens
    assert "the" not in tokens and "is" not in tokens


def test_sparse_vectors_are_deterministic_bm25_weights():
    doc = sparse_vector("notice notice notice period")
    assert doc == sparse_vector("notice notice notice period")
    weights = dict(zip(doc.indices, doc.values, strict=True))
    assert weights[term_index("notice")] > weights[term_index("period")]  # tf 3 > tf 1
    assert weights[term_index("notice")] < 3  # saturates: tf is not linear
    query = sparse_vector("notice notice period", query=True)
    assert set(query.values) == {1.0}  # repeats in a question don't matter


# --- Qdrant points ---------------------------------------------------------------------


def test_points_children_have_vectors_parents_do_not():
    result = chunk_document(
        CONTRACT, version_id="v-1", document_title="Acme MSA", options=ChunkingOptions()
    )
    target = IndexTarget(
        tenant_id="t1",
        document_id="d1",
        version_id="v-1",
        version_label="v1",
        document_title="Acme MSA",
        contract_type="MSA",
        is_current=True,
        embedding_model="fake:hash-embed:8",
        chunker_version=1,
    )
    vectors = [vector_for(c.embedding_text, DIM) for c in result.children]
    points = build_points(result.children, vectors, result.parents, target)
    assert len(points) == len(result.chunks)
    child = next(p for p in points if p.payload["level"] == ChunkLevel.CHILD.value)
    assert set(child.vector) == {"dense", "sparse"} and len(child.vector["dense"]) == DIM
    assert child.payload["tenant_id"] == "t1" and child.payload["embedding_model"].startswith(
        "fake"
    )
    parent = next(p for p in points if p.payload["level"] == ChunkLevel.PARENT.value)
    assert parent.vector == {}  # never matched by similarity search
    with pytest.raises(ValueError, match="vectors"):
        build_points(result.children, vectors[:-1], result.parents, target)
