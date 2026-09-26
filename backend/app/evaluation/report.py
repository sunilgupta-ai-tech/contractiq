"""
Evaluation reports and the regression gate (Phase 12).

    report.json   everything: config snapshot, metrics, calibration, and every
                  example's retrieval list, answer, citations and scores
    report.md     the summary a reviewer reads in a PR

Regression gate
---------------
`compare_to_baseline` checks the gated metrics against a stored baseline
(a previous report.json). A higher-is-better metric that falls more than
`max_drop` (absolute) below baseline, or a lower-is-better one that rises
more than `max_drop`, is a regression; the CLI then exits non-zero, which
fails CI. With a 23-question answerable set, one question is ~4.3 points,
so the default tolerance (0.05) allows one flipped answer, not two.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evaluation.evaluator import EvaluationReport

HIGHER_IS_BETTER = (
    "retrieval.recall@5",
    "retrieval.mrr",
    "answer.accuracy",
    "answer.fact_recall",
    "answer.abstention_accuracy",
    "citations.relevant_rate",
    "grounding.mean",
)
LOWER_IS_BETTER = ("answer.false_abstention_rate",)
DEFAULT_MAX_DROP = 0.05


@dataclass
class Regression:
    metric: str
    baseline: float
    current: float

    def __str__(self) -> str:
        return f"{self.metric}: {self.baseline:.3f} -> {self.current:.3f}"


def compare_to_baseline(
    metrics: dict[str, float], baseline: dict[str, float], *, max_drop: float = DEFAULT_MAX_DROP
) -> list[Regression]:
    """Gated metrics that got worse by more than `max_drop`. A metric missing
    from either side is not compared (e.g. judge scores in a non-judged run)."""
    regressions = []
    for name in HIGHER_IS_BETTER:
        if name in metrics and name in baseline and metrics[name] < baseline[name] - max_drop:
            regressions.append(Regression(name, baseline[name], metrics[name]))
    for name in LOWER_IS_BETTER:
        if name in metrics and name in baseline and metrics[name] > baseline[name] + max_drop:
            regressions.append(Regression(name, baseline[name], metrics[name]))
    return regressions


def load_baseline(path: str | Path) -> dict[str, float]:
    data = json.loads(Path(path).read_text())
    metrics = data.get("metrics", data)
    return {k: float(v) for k, v in metrics.items() if isinstance(v, int | float)}


def write_reports(report: EvaluationReport, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "report.json", out / "report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str))
    md_path.write_text(render_markdown(report))
    return json_path, md_path


def render_markdown(report: EvaluationReport, regressions: list[Regression] | None = None) -> str:
    cfg = report.config
    lines = [
        f"# Evaluation: {report.dataset} v{report.dataset_version}",
        "",
        f"Mode `{cfg.get('mode')}` · model `{cfg.get('llm')}` · embeddings "
        f"`{cfg.get('embedding_model')}` · reranker `{cfg.get('reranker')}` · "
        f"chunker v{cfg.get('chunker_version')} · prompt `{cfg.get('prompt_version')}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        *[f"| {name} | {_fmt(value)} |" for name, value in report.metrics.items()],
        "",
        "## Grounding calibration",
        "",
        "What `GROUNDING_MODE=enforce` would withhold among answered questions at each "
        "`GROUNDING_MIN_SCORE`. A good threshold withholds incorrect answers, not correct ones.",
        "",
        "| Threshold | Withheld | Correct withheld | Incorrect withheld | Accuracy of shown |",
        "|---|---|---|---|---|",
        *[
            f"| {row['threshold']} | {row['withheld']} | {row['withheld_correct']} | "
            f"{row['withheld_incorrect']} | {row['shown_accuracy']:.0%} |"
            for row in report.calibration
        ],
        "",
    ]
    failures = [ex for ex in report.examples if _failed(ex)]
    if failures:
        lines += ["## Failures", "", "| Example | Problem | Answer |", "|---|---|---|"]
        for ex in failures:
            answer = " ".join(ex.answer.split())[:160].replace("|", "\\|")
            lines.append(f"| {ex.id} | {_problem(ex)} | {answer} |")
        lines.append("")
    if report.warnings:
        lines += ["## Warnings", "", *[f"* {w}" for w in report.warnings], ""]
    if regressions is not None:
        lines += ["## Regression gate", ""]
        lines += [f"* ❌ {r}" for r in regressions] or ["* ✅ no regressions against baseline"]
        lines.append("")
    return "\n".join(lines)


def _failed(example: Any) -> bool:
    s = example.scores
    return (example.answerable and not s.correct) or not s.abstention_correct


def _problem(example: Any) -> str:
    s = example.scores
    if not example.answerable:
        return "answered an unanswerable question"
    if s.abstained:
        return "said not found"
    # "|" separates fact alternatives; shown as "or" so the table stays intact.
    return "missing " + ", ".join(f.replace("|", " or ") for f in s.missing_facts)


def _fmt(value: float) -> str:
    return f"{value:.0f}" if value.is_integer() and value > 1 else f"{value:.3f}"
