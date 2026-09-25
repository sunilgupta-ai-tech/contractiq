"use client";

import Link from "next/link";
import { useState } from "react";
import { Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { RiskBadge } from "@/components/ui/risk-badge";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { analysisService } from "@/services/analysis-service";
import type { RiskFinding, RiskLevel } from "@/types";
import { cn } from "@/utils/cn";

const statusStyle: Record<RiskFinding["status"], string> = {
  open: "text-danger",
  reviewing: "text-info",
  accepted: "text-ok",
};

export function RiskView() {
  const { data, error, loading, reload } = useAsync(() => analysisService.riskFindings(), []);
  const [level, setLevel] = useState<RiskLevel | "all">("all");
  const findings = (data ?? []).filter((f) => level === "all" || f.severity === level);
  const count = (l: RiskLevel) => (data ?? []).filter((f) => f.severity === l).length;

  const tiles: { key: RiskLevel | "all"; label: string; value: number; bar: string }[] = [
    { key: "all", label: "All findings", value: data?.length ?? 0, bar: "bg-ink-3" },
    { key: "high", label: "High", value: count("high"), bar: "bg-danger" },
    { key: "medium", label: "Medium", value: count("medium"), bar: "bg-warn" },
    { key: "low", label: "Low", value: count("low"), bar: "bg-ok" },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Contract intelligence"
        title="Risk review"
        description="Clauses flagged by deterministic rules and LLM review. Each finding carries its evidence so reviewers can accept or escalate quickly."
      />
      <div className="mb-5 flex items-start gap-3 rounded-xl border border-info/20 bg-info-soft px-4 py-3 text-[13px] text-ink-2">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" />
        Risk flags are AI-assisted and advisory. They are not legal advice and should be reviewed by a qualified professional before any decision.
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <button key={t.key} onClick={() => setLevel(t.key)} className={cn("card relative overflow-hidden p-4 text-left transition", level === t.key ? "ring-2 ring-brand/50" : "hover:border-line-strong")}>
            <span className={cn("absolute inset-y-0 left-0 w-1", t.bar)} />
            <p className="text-[13px] text-ink-2">{t.label}</p>
            <p className="display num mt-1 text-[30px] leading-none">{t.value}</p>
          </button>
        ))}
      </div>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-32 rounded-xl" />)}</div>
      ) : (
        <div className="space-y-3">
          {findings.map((f) => (
            <Card key={f.id} className="grid grid-cols-1 gap-4 p-5 md:grid-cols-[220px_minmax(0,1fr)_120px]">
              <div className="space-y-2">
                <RiskBadge level={f.severity} />
                <p className="font-medium text-ink">{f.rule}</p>
                <Link href={`/documents/${f.documentId}`} className="block text-[12.5px] text-ink-2 hover:text-brand">
                  {f.documentTitle}
                </Link>
                <p className="font-mono text-2xs text-ink-3">§{f.clause} · p.{f.page}</p>
              </div>
              <div className="space-y-2.5">
                <blockquote className="border-l-2 border-[#E3C766] pl-3 font-serif text-[14.5px] leading-6 text-ink">
                  <span className="cite-mark">{f.excerpt}</span>
                </blockquote>
                <p className="text-[13px] leading-5 text-ink-2">{f.rationale}</p>
              </div>
              <div className="flex items-start justify-between gap-2 md:flex-col md:items-end">
                <span className={cn("text-2xs font-semibold uppercase tracking-[0.08em]", statusStyle[f.status])}>{f.status}</span>
                <button className="rounded-lg border border-line px-3 py-1.5 text-[12.5px] font-medium text-ink-2 hover:bg-sunken hover:text-ink">Review</button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
