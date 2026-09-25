"use client";

import { useState } from "react";
import { ArrowRightLeft, Equal, Minus, PenLine } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { RiskBadge } from "@/components/ui/risk-badge";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { demoDocuments } from "@/lib/demo/fixtures";
import { analysisService } from "@/services/analysis-service";
import type { ComparisonRow, DiffKind } from "@/types";
import { cn } from "@/utils/cn";
import { wordDiff, type DiffSegment } from "@/utils/diff";

const diffMeta: Record<DiffKind, { label: string; tone: "warn" | "neutral" | "danger"; icon: typeof Equal }> = {
  changed: { label: "Changed", tone: "warn", icon: PenLine },
  same: { label: "Unchanged", tone: "neutral", icon: Equal },
  missing: { label: "Added", tone: "danger", icon: Minus },
};

function Segments({ segments }: { segments: DiffSegment[] }) {
  return (
    <>
      {segments.map((s, i) =>
        s.kind === "same" ? (
          <span key={i}>{s.text}</span>
        ) : s.kind === "del" ? (
          <del key={i} className="rounded-[2px] bg-danger-soft text-danger decoration-danger/50">{s.text}</del>
        ) : (
          <ins key={i} className="cite-mark no-underline">{s.text}</ins>
        ),
      )}
    </>
  );
}

function Side({ side, label, segments }: { side: ComparisonRow["left"]; label: string; segments?: DiffSegment[] }) {
  if (!side) {
    return (
      <div className="grid h-full place-items-center rounded-lg border border-dashed border-line-strong p-4 text-[13px] italic text-ink-3">
        Not present in {label}
      </div>
    );
  }
  return (
    <div className="h-full rounded-lg bg-sunken p-4">
      <p className="mb-1.5 font-mono text-2xs text-ink-3">§{side.clause} · p.{side.page}</p>
      <p className="font-serif text-[14.5px] leading-6 text-ink">{segments ? <Segments segments={segments} /> : side.text}</p>
    </div>
  );
}

export function CompareView() {
  const versioned = demoDocuments.filter((d) => d.versions.length > 1);
  const [docId, setDocId] = useState(versioned[0]!.id);
  const doc = versioned.find((d) => d.id === docId)!;
  const [left, setLeft] = useState(doc.versions[0]!.id);
  const [right, setRight] = useState(doc.versions.at(-1)!.id);
  const [onlyChanges, setOnlyChanges] = useState(false);
  const { data, error, loading, reload } = useAsync(() => analysisService.compare(left, right), [left, right]);

  const leftLabel = doc.versions.find((v) => v.id === left)?.label ?? "A";
  const rightLabel = doc.versions.find((v) => v.id === right)?.label ?? "B";
  const rows = (data ?? []).filter((r) => !onlyChanges || r.diff !== "same");
  const changed = (data ?? []).filter((r) => r.diff !== "same").length;

  const select = "h-9 rounded-lg border border-line bg-surface px-3 text-[13px] text-ink shadow-card focus:border-brand/50 focus:outline-none";

  return (
    <>
      <PageHeader
        eyebrow="Contract intelligence"
        title="Compare versions"
        description="Clauses are aligned by topic, not by page, so renumbered or moved provisions still line up. Every difference links back to its source."
      />
      <Card className="mb-5 flex flex-wrap items-center gap-3 p-4">
        <select value={docId} onChange={(e) => { const d = versioned.find((x) => x.id === e.target.value)!; setDocId(d.id); setLeft(d.versions[0]!.id); setRight(d.versions.at(-1)!.id); }} className={cn(select, "min-w-[240px] flex-1")}>
          {versioned.map((d) => <option key={d.id} value={d.id}>{d.title} — {d.counterparty}</option>)}
        </select>
        <select value={left} onChange={(e) => setLeft(e.target.value)} className={select} aria-label="Base version">
          {doc.versions.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
        <ArrowRightLeft className="h-4 w-4 text-ink-3" />
        <select value={right} onChange={(e) => setRight(e.target.value)} className={select} aria-label="Compared version">
          {doc.versions.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
        <label className="ml-auto flex items-center gap-2 text-[13px] text-ink-2">
          <input type="checkbox" checked={onlyChanges} onChange={(e) => setOnlyChanges(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--brand))]" />
          Only differences
        </label>
      </Card>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-36 rounded-xl" />)}</div>
      ) : (
        <>
          <p className="mb-3 text-[13px] text-ink-2">
            <span className="num font-semibold text-ink">{changed}</span> of {data?.length} aligned topics differ between{" "}
            <span className="font-mono">{leftLabel}</span> and <span className="font-mono">{rightLabel}</span>.
          </p>
          <div className="space-y-3">
            <div className="hidden grid-cols-[180px_1fr_1fr] gap-4 px-5 text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3 lg:grid">
              <span>Topic</span><span>{leftLabel}</span><span>{rightLabel}</span>
            </div>
            {rows.map((row) => {
              const meta = diffMeta[row.diff];
              const diff = row.diff === "changed" && row.left && row.right ? wordDiff(row.left.text, row.right.text) : null;
              return (
                <Card key={row.topic} className={cn("grid grid-cols-1 gap-4 p-5 lg:grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)]", row.diff !== "same" && "border-l-[3px] border-l-warn")}>
                  <div className="space-y-2">
                    <p className="font-medium text-ink">{row.topic}</p>
                    <div className="flex flex-wrap gap-1.5">
                      <Badge tone={meta.tone}><meta.icon className="h-3 w-3" /> {meta.label}</Badge>
                      {row.risk && <RiskBadge level={row.risk} />}
                    </div>
                    <p className="text-[12.5px] leading-5 text-ink-2">{row.note}</p>
                  </div>
                  <Side side={row.left} label={leftLabel} segments={diff?.left} />
                  <Side side={row.right} label={rightLabel} segments={diff?.right} />
                </Card>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}
