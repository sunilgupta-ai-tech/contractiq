"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft, GitCompareArrows, History, MessageSquareText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { RiskBadge } from "@/components/ui/risk-badge";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { StatusPill } from "@/components/ui/status-pill";
import { useAsync } from "@/hooks/use-async";
import { documentService } from "@/services/document-service";
import type { Clause } from "@/types";
import { cn } from "@/utils/cn";
import { formatDate } from "@/utils/format";

function groupBySection(clauses: Clause[]) {
  const map = new Map<string, Clause[]>();
  for (const c of clauses) map.set(c.section, [...(map.get(c.section) ?? []), c]);
  return [...map.entries()];
}

const riskDot = { high: "bg-danger", medium: "bg-warn", low: "bg-ok" } as const;

export function ContractDetailView({ id }: { id: string }) {
  const { data: doc, error, loading, reload } = useAsync(() => documentService.get(id), [id]);
  const [selected, setSelected] = useState<string>("c-8-3");
  const sections = useMemo(() => groupBySection(doc?.clauses ?? []), [doc]);

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !doc) return <Skeleton className="h-[70vh] rounded-xl" />;

  return (
    <>
      <div className="mb-6 animate-fade-up">
        <Link href="/documents" className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-ink-2 hover:text-ink">
          <ArrowLeft className="h-3.5 w-3.5" /> Contracts
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge>{doc.contractType}</Badge>
              <Badge tone="brand">{doc.version} · current</Badge>
              <StatusPill status={doc.status} progress={doc.progress} />
            </div>
            <h1 className="display text-[30px] leading-tight">{doc.title}</h1>
            <p className="mt-1 text-[13.5px] text-ink-2">
              {doc.counterparty} · effective {formatDate(doc.effectiveDate)} · expires {formatDate(doc.expiryDate)}
            </p>
          </div>
          <div className="flex gap-2">
            <Link href="/compare">
              <Button variant="secondary"><GitCompareArrows className="h-4 w-4" /> Compare versions</Button>
            </Link>
            <Link href={`/assistant?doc=${doc.id}`}>
              <Button><MessageSquareText className="h-4 w-4" /> Ask this contract</Button>
            </Link>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[240px_minmax(0,1fr)] 2xl:grid-cols-[240px_minmax(0,1fr)_320px]">
        {/* Outline */}
        <Card className="h-fit lg:sticky lg:top-20">
          <CardHeader eyebrow="Structure" title="Clauses" />
          <nav className="max-h-[60vh] overflow-y-auto scroll-thin p-2">
            {sections.map(([section, clauses]) => (
              <div key={section} className="mb-2">
                <p className="px-2 pb-1 pt-2 text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">{section}</p>
                {clauses.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => {
                      setSelected(c.id);
                      document.getElementById(c.id)?.scrollIntoView({ behavior: "smooth", block: "center" });
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition",
                      selected === c.id ? "bg-brand-soft text-brand-ink" : "text-ink-2 hover:bg-sunken hover:text-ink",
                    )}
                  >
                    <span className="w-8 shrink-0 font-mono text-2xs text-ink-3">{c.number}</span>
                    <span className="flex-1 truncate">{c.title}</span>
                    {c.risk && <span className={cn("h-1.5 w-1.5 rounded-full", riskDot[c.risk])} />}
                  </button>
                ))}
              </div>
            ))}
          </nav>
        </Card>

        {/* Paper view */}
        <div className="rounded-2xl border border-line bg-sunken p-3 sm:p-6">
          <article className="mx-auto max-w-[720px] rounded-sm bg-[#FFFEFB] px-7 py-10 text-[#23252B] shadow-paper sm:px-14 sm:py-14 dark:bg-[#1B2029] dark:text-[#DADDE3]">
            <p className="text-center font-serif text-[13px] uppercase tracking-[0.25em] text-[#8A8577]">{doc.contractType} · {doc.version}</p>
            <h2 className="mt-2 text-center font-serif text-[26px]">{doc.title}</h2>
            <p className="mb-10 mt-1 text-center text-[12.5px] text-[#8A8577]">between Acme Legal Holdings and {doc.counterparty}</p>
            {sections.map(([section, clauses]) => (
              <section key={section} className="mb-8">
                <h3 className="mb-3 font-serif text-[15px] font-semibold uppercase tracking-[0.08em]">{section}</h3>
                {clauses.map((c) => (
                  <p
                    id={c.id}
                    key={c.id}
                    onClick={() => setSelected(c.id)}
                    className={cn(
                      "-mx-3 mb-3 cursor-pointer rounded-md px-3 py-2 font-serif text-[15px] leading-7 transition",
                      selected === c.id ? "bg-mark/70 ring-1 ring-[#E3C766]" : "hover:bg-black/[0.025] dark:hover:bg-white/[0.03]",
                    )}
                  >
                    <span className="mr-2 font-sans text-[12px] font-semibold text-[#8A8577]">{c.number}</span>
                    <span className="font-semibold">{c.title}.</span> {c.text}
                    <span className="ml-2 font-sans text-2xs text-[#A09A8A]">p.{c.page}</span>
                  </p>
                ))}
              </section>
            ))}
          </article>
        </div>

        {/* Inspector */}
        <div className="space-y-5 lg:col-span-2 2xl:col-span-1">
          <Card>
            <CardHeader eyebrow="Extracted" title="Key terms" />
            <dl className="divide-y divide-line">
              {doc.keyTerms.map((t) => (
                <div key={t.label} className="px-5 py-3">
                  <dt className="text-2xs text-ink-3">{t.label}</dt>
                  <dd className="mt-0.5 flex items-baseline justify-between gap-3 text-[13.5px] font-medium text-ink">
                    {t.value}
                    <span className="shrink-0 font-mono text-2xs font-normal text-ink-3">§{t.clause} · p.{t.page}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card>
            <CardHeader eyebrow="Assessment" title="Risk" action={<RiskBadge level={doc.riskLevel} count={doc.riskCount} />} />
            <ul className="space-y-2 px-5 py-4">
              {doc.clauses.filter((c) => c.risk).map((c) => (
                <li key={c.id}>
                  <button onClick={() => setSelected(c.id)} className="flex w-full items-center gap-2 text-left text-[13px] text-ink-2 hover:text-ink">
                    <span className={cn("h-2 w-2 rounded-full", riskDot[c.risk!])} />
                    <span className="font-mono text-2xs text-ink-3">{c.number}</span> {c.title}
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader eyebrow="Lineage" title="Versions" action={<History className="h-4 w-4 text-ink-3" />} />
            <ol className="px-5 py-4">
              {[...doc.versions].reverse().map((v, i) => (
                <li key={v.id} className="flex items-center justify-between py-1.5 text-[13px]">
                  <span className="flex items-center gap-2">
                    <span className={cn("h-2 w-2 rounded-full", i === 0 ? "bg-brand" : "bg-line-strong")} />
                    <span className="font-medium text-ink">{v.label}</span>
                  </span>
                  <span className="num text-2xs text-ink-3">{formatDate(v.uploadedAt)} · {v.pages}p</span>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
    </>
  );
}
