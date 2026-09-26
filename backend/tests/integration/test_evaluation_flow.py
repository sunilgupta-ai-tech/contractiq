"""
Phase 12 end to end: the sample contract is ingested (parse -> chunk ->
embed -> index) into a throwaway Qdrant collection, evaluated through real
hybrid search, and the run is stored as an EvaluationRun in PostgreSQL.

Embeddings and the answer model are deterministic fakes, so the dense half
of hybrid search is noise; the keyword half is real. That makes the
retrieval numbers here a floor, not a benchmark.

    CONTRACTIQ_INTEGRATION=1 pytest tests/integration
"""

import argparse
import os
import uuid

import pytest
from sqlalchemy import delete, select

from app.core.config import Settings
from app.core.resources import Resources
from app.db.models import EvaluationRun, Organization
from app.evaluation.__main__ import _save_run, config_snapshot
from app.evaluation.dataset import DATASETS_DIR, GoldenDataset
from app.evaluation.evaluator import Evaluator
from app.evaluation.ingest import ingest_document
from app.rag.reranker import HeuristicReranker
from app.services.retrieval_service import RetrievalService
from tests.fake_embeddings import FakeEmbeddings
from tests.unit.test_evaluation import ReaderLLM

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)


async def test_sample_dataset_is_ingested_evaluated_and_saved():
    settings = Settings(qdrant_collection=f"eval_test_{uuid.uuid4().hex[:10]}")
    resources = Resources.create(settings)
    resources._embeddings = FakeEmbeddings(768)
    resources._llm = ReaderLLM()
    dataset = GoldenDataset.load(DATASETS_DIR / "sample_msa.json")
    tenant_id = str(uuid.uuid4())
    org = Organization(name="Eval Org", slug=f"eval-{uuid.uuid4().hex[:8]}")
    try:
        documents = {
            key: await ingest_document(
                source.load(dataset.base_dir),
                key=key,
                title=source.title,
                contract_type=source.contract_type,
                tenant_id=tenant_id,
                document_id=str(uuid.uuid4()),
                version_id=str(uuid.uuid4()),
                settings=settings,
                embeddings=resources.embeddings(),
                qdrant=resources.qdrant,
                redis=resources.redis,
            )
            for key, source in dataset.documents.items()
        }
        assert documents["msa"].page_count == 3 and len(documents["msa"].children) >= 14

        evaluator = Evaluator(
            retriever=RetrievalService(resources),
            reranker=HeuristicReranker(),
            llm=resources.llm(),
            settings=settings,
        )
        config = config_snapshot(settings, resources.llm(), "fake:hash-embed:768", "heuristic")
        report = await evaluator.run(
            dataset, tenant_id=tenant_id, documents=documents, config=config
        )
        m = report.metrics
        assert report.warnings == []
        assert m["retrieval.recall@10"] >= 0.8  # keyword search alone finds the clauses
        assert m["answer.accuracy"] >= 0.6 and m["citations.relevant_rate"] >= 0.6
        assert report.config["chunker_version"] >= 2 and report.config["mode"] == "fast"

        async with resources.db.session_factory() as session:
            session.add(org)
            await session.commit()
        await _save_run(resources, argparse.Namespace(save_tenant=str(org.id)), report)
        async with resources.db.session_factory() as session:
            run = (
                await session.execute(
                    select(EvaluationRun).where(EvaluationRun.organization_id == org.id)
                )
            ).scalar_one()
            assert run.dataset_name == "sample-msa" and run.sample_count == 27
            assert run.metrics["answer.accuracy"] == m["answer.accuracy"]
    finally:
        async with resources.db.session_factory() as session:
            await session.execute(delete(Organization).where(Organization.slug == org.slug))
            await session.commit()
        await resources.qdrant.delete_collection(settings.qdrant_collection)
        await resources.close()
