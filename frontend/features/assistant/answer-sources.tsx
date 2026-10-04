import Link from "next/link";
import { FileText } from "lucide-react";
import type { Citation } from "@/types";
import { answerSources } from "@/utils/answer-sources";
import { cn } from "@/utils/cn";

const SHOWN = 3;

/** "Also found in: A, B, C (+2 more)": the same text in other documents. */
function AlsoFoundIn({ docs }: { docs: { documentId: string; title: string }[] }) {
  return (
    <p className="mt-0.5 pl-[22px] text-2xs text-ink-3">
      Same text also in:{" "}
      {docs.slice(0, SHOWN).map((d, i) => (
        <span key={d.documentId}>
          {i > 0 && ", "}
          <Link href={`/documents/${d.documentId}`} className="text-ink-2 hover:text-brand hover:underline">
            {d.title}
          </Link>
        </span>
      ))}
      {docs.length > SHOWN && <span title={docs.slice(SHOWN).map((d) => d.title).join(", ")}> (+{docs.length - SHOWN} more)</span>}
    </p>
  );
}

/** "Sources" under an answer: each document it came from, with its citations and pages. */
export function AnswerSources({ citations, active, onCite }: { citations: Citation[]; active: number | null; onCite: (n: number) => void }) {
  const sources = answerSources(citations);
  if (sources.length === 0) return null;
  return (
    <div className="mt-4 border-t border-line pt-3">
      <p className="mb-2 text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">
        {sources.length === 1 ? "Source" : `Sources · ${sources.length} documents`}
      </p>
      <ul className="space-y-1.5">
        {sources.map((s) => (
          <li key={s.documentId} className="text-[13px]">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <FileText className="h-3.5 w-3.5 shrink-0 text-ink-3" />
              <Link href={`/documents/${s.documentId}`} className="min-w-0 truncate font-medium text-ink hover:text-brand hover:underline">
                {s.title}
              </Link>
              {s.versions.length > 0 && <span className="font-mono text-2xs text-ink-3">{s.versions.join(", ")}</span>}
              {s.pages.length > 0 && <span className="text-2xs text-ink-3">p.{s.pages.join(", ")}</span>}
              <span className="flex gap-1">
                {s.indexes.map((n) => (
                  <button
                    key={n}
                    onClick={() => onCite(n)}
                    aria-label={`Citation ${n}`}
                    className={cn(
                      "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded px-1 font-mono text-[10.5px] font-semibold leading-none transition",
                      active === n ? "bg-brand text-white dark:text-rail" : "bg-brand-soft text-brand-ink hover:bg-brand hover:text-white",
                    )}
                  >
                    {n}
                  </button>
                ))}
              </span>
            </div>
            {s.alsoFoundIn.length > 0 && <AlsoFoundIn docs={s.alsoFoundIn} />}
          </li>
        ))}
      </ul>
    </div>
  );
}
