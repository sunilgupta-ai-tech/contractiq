import Link from "next/link";
import { BookOpenCheck, ShieldCheck } from "lucide-react";
import type { QueryAnswer } from "@/types";
import { cn } from "@/utils/cn";

export function EvidencePanel({ answer, active, onSelect }: { answer: QueryAnswer | null; active: number | null; onSelect: (n: number) => void }) {
  if (!answer) {
    return (
      <div className="card flex h-full flex-col items-center justify-center p-8 text-center">
        <BookOpenCheck className="mb-3 h-6 w-6 text-ink-3" />
        <p className="font-medium text-ink">Evidence appears here</p>
        <p className="mt-1 max-w-[240px] text-[13px] text-ink-2">Each claim in an answer links to the exact clause, page and version it came from.</p>
      </div>
    );
  }
  return (
    <div className="card flex h-full flex-col overflow-hidden">
      <div className="border-b border-line px-5 py-4">
        <p className="eyebrow mb-1">Evidence</p>
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">{answer.citations.length} sources cited</h2>
          <span className="inline-flex items-center gap-1 rounded-md bg-ok-soft px-1.5 py-0.5 text-2xs font-semibold text-ok">
            <ShieldCheck className="h-3 w-3" /> {Math.round(answer.groundedness * 100)}% grounded
          </span>
        </div>
      </div>
      <ol className="flex-1 space-y-3 overflow-y-auto scroll-thin p-4">
        {answer.citations.map((c) => (
          <li key={c.id}>
            <button
              onClick={() => onSelect(c.index)}
              className={cn(
                "w-full rounded-xl border p-4 text-left transition",
                active === c.index ? "border-brand/50 bg-brand-soft/50 shadow-card" : "border-line bg-surface hover:border-line-strong",
              )}
            >
              <div className="mb-2 flex items-center gap-2">
                <span className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded px-1 font-mono text-[10.5px] font-semibold leading-none", active === c.index ? "bg-brand text-white" : "bg-brand-soft text-brand-ink")}>
                  {c.index}
                </span>
                <span className="truncate text-[13px] font-medium text-ink">{c.documentTitle}</span>
              </div>
              <blockquote className="border-l-2 border-[#E3C766] pl-3 font-serif text-[14px] leading-6 text-ink">
                <span className="cite-mark">{c.quote}</span>
              </blockquote>
              <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 font-mono text-2xs text-ink-3">
                <span>§{c.clause}</span>
                <span>p.{c.page}</span>
                <span>{c.section}</span>
                <span className={c.version === "v1" ? "text-warn" : ""}>{c.version}</span>
                <span className="ml-auto">score {c.score.toFixed(2)}</span>
              </div>
            </button>
            {active === c.index && (
              <Link href={`/documents/${c.documentId}`} className="mt-1.5 inline-block pl-1 text-2xs font-medium text-brand hover:underline">
                Open in document →
              </Link>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
