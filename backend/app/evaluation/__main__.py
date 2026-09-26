"""
Evaluation command line (Phase 12).

    python -m app.evaluation run [--dataset PATH] [--mode fast|agent] [--judge]
                                 [--out DIR] [--baseline FILE] [--max-drop 0.05]
                                 [--save-tenant ORG_ID] [--keep-collection]

Uses the configured models (LLM_PROVIDER, EMBEDDING_PROVIDER, ...) and the
configured Qdrant/Redis, but indexes the dataset's contracts into a
throwaway collection (eval_<run>) under a throwaway tenant id, deleted
afterwards unless --keep-collection. Exit codes: 0 ok, 1 regression
against --baseline, 2 the run itself failed.

To create a baseline, run once on a known-good commit and keep report.json:

    python -m app.evaluation run --out eval/baseline
    python -m app.evaluation run --baseline eval/baseline/report.json   # in CI
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.resources import Resources
from app.evaluation.dataset import DATASETS_DIR, GoldenDataset
from app.evaluation.evaluator import EvaluationReport, Evaluator
from app.evaluation.ingest import ingest_document
from app.evaluation.report import (
    DEFAULT_MAX_DROP,
    compare_to_baseline,
    load_baseline,
    render_markdown,
    write_reports,
)
from app.llm.base import embedding_model_label
from app.rag.prompts.system import PROMPT_VERSION
from app.services.chunking_service import CHUNKER_VERSION
from app.services.reranking_service import reranker_for
from app.services.retrieval_service import RetrievalService

logger = get_logger("contractiq.evaluation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="evaluate the pipeline on a golden dataset")
    run.add_argument("--dataset", default=str(DATASETS_DIR / "sample_msa.json"))
    run.add_argument("--mode", choices=("fast", "agent"), default="fast")
    run.add_argument("--judge", action="store_true", help="also score answers with the LLM judge")
    run.add_argument("--out", default="eval-reports")
    run.add_argument("--baseline", help="report.json to gate against")
    run.add_argument("--max-drop", type=float, default=DEFAULT_MAX_DROP)
    run.add_argument("--save-tenant", help="also store an EvaluationRun for this organization id")
    run.add_argument("--keep-collection", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    try:
        report = asyncio.run(_run(args))
    except Exception:  # noqa: BLE001 — a failed run must be distinguishable from a regression
        logger.exception("evaluation_failed")
        return 2

    regressions = None
    if args.baseline:
        regressions = compare_to_baseline(
            report.metrics, load_baseline(args.baseline), max_drop=args.max_drop
        )
    json_path, md_path = write_reports(report, args.out)
    summary = render_markdown(report, regressions)
    md_path.write_text(summary)
    print(summary)
    print(f"Reports: {json_path} {md_path}")
    return 1 if regressions else 0


async def _run(args: argparse.Namespace) -> EvaluationReport:
    run_id = uuid.uuid4().hex[:10]
    base = get_settings()
    settings = base.model_copy(update={"qdrant_collection": f"eval_{run_id}"})
    resources = Resources.create(settings)
    tenant_id = str(uuid.uuid4())  # throwaway: nothing real is ever searched
    try:
        dataset = GoldenDataset.load(args.dataset)
        embeddings = resources.embeddings()
        llm = resources.llm()
        documents = {}
        for key, source in dataset.documents.items():
            documents[key] = await ingest_document(
                source.load(dataset.base_dir),
                key=key,
                title=source.title,
                contract_type=source.contract_type,
                tenant_id=tenant_id,
                document_id=str(uuid.uuid4()),
                version_id=str(uuid.uuid4()),
                settings=settings,
                embeddings=embeddings,
                qdrant=resources.qdrant,
                redis=resources.redis,
            )
        reranker = reranker_for(settings)
        evaluator = Evaluator(
            retriever=RetrievalService(resources),
            reranker=reranker,
            llm=llm,
            settings=settings,
            mode=args.mode,
            judge=llm if args.judge else None,
        )
        report = await evaluator.run(
            dataset,
            tenant_id=tenant_id,
            documents=documents,
            config=config_snapshot(settings, llm, embedding_model_label(embeddings), reranker.name),
        )
        if args.save_tenant:
            await _save_run(resources, args, report)
        return report
    finally:
        if not args.keep_collection:
            await resources.qdrant.delete_collection(settings.qdrant_collection)
        await resources.close()


def config_snapshot(settings: Any, llm: Any, embedding_model: str, reranker: str) -> dict[str, Any]:
    """Everything that can move the metrics, so a change is attributable."""
    return {
        "llm": f"{llm.name}:{llm.model}",
        "embedding_model": embedding_model,
        "reranker": reranker,
        "chunker_version": CHUNKER_VERSION,
        "prompt_version": PROMPT_VERSION,
        "retrieval_prefetch": settings.retrieval_prefetch,
        "retrieval_candidates": settings.retrieval_candidates,
        "rerank_top_n": settings.rerank_top_n,
        "context_max_tokens": settings.context_max_tokens,
        "chunk_max_tokens": settings.chunk_max_tokens,
        "grounding_mode": settings.grounding_mode,
        "grounding_min_score": settings.grounding_min_score,
        "git_sha": os.getenv("GIT_SHA"),
    }


async def _save_run(
    resources: Resources, args: argparse.Namespace, report: EvaluationReport
) -> None:
    from app.db.models import EvaluationRun

    async with resources.db.session_factory() as session:
        session.add(
            EvaluationRun(
                organization_id=uuid.UUID(args.save_tenant),
                name=f"{report.dataset} ({report.config['mode']})",
                dataset_name=report.dataset,
                status="COMPLETED",
                sample_count=len(report.examples),
                config=report.config,
                metrics=report.metrics,
            )
        )
        await session.commit()


if __name__ == "__main__":
    sys.exit(main())
