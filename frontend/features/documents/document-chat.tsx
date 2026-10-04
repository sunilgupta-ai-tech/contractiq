"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ExternalLink, Loader2, MessageSquareText, ShieldAlert, X } from "lucide-react";
import { ErrorState } from "@/components/ui/states";
import { ApiError } from "@/lib/api-client";
import { queryService } from "@/services/query-service";
import type { Citation, QueryAnswer } from "@/types";
import { cn } from "@/utils/cn";
import { personalDataLevel, sensitiveText } from "@/utils/personal-data";
import { AnswerBody } from "../assistant/answer-body";
import { Composer } from "../assistant/composer";

interface Turn {
  question: string;
  answer: QueryAnswer | null;
  error: ApiError | null;
}

const STARTERS = ["Summarise this document", "What are the key dates and deadlines?", "What amounts or payment terms does it mention?"];

/**
 * Questions about one document, asked beside it. Uses the same /query endpoint
 * as the Assistant, limited to this document. Citations are handed to the page
 * (`onCite`) so it can show the cited page or clause next to the chat.
 */
export function DocumentChat({
  documentId,
  title,
  personalData = {},
  onClose,
  onCite,
}: {
  documentId: string;
  title: string;
  personalData?: Record<string, number>;
  onClose: () => void;
  onCite: (citation: Citation) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [active, setActive] = useState<{ turn: number; index: number } | null>(null);
  const busy = turns.some((t) => !t.answer && !t.error);
  const thread = useRef<HTMLDivElement>(null);

  // Scroll only the conversation, never the page behind it.
  useEffect(() => {
    thread.current?.scrollTo({ top: thread.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  async function ask(question: string) {
    const index = turns.length;
    setTurns((t) => [...t, { question, answer: null, error: null }]);
    try {
      const answer = await queryService.ask({ question, documentIds: [documentId] });
      setTurns((t) => t.map((turn, i) => (i === index ? { ...turn, answer } : turn)));
    } catch (err) {
      const error = err instanceof ApiError ? err : new ApiError("Something went wrong.", "UNKNOWN", 0, null);
      setTurns((t) => t.map((turn, i) => (i === index ? { ...turn, error } : turn)));
    }
  }

  function cite(turn: number, answer: QueryAnswer, n: number) {
    setActive({ turn, index: n });
    const citation = answer.citations.find((c) => c.index === n);
    if (citation) onCite(citation);
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface xl:rounded-2xl xl:border xl:border-line">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <MessageSquareText className="h-4 w-4 shrink-0 text-brand" />
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold text-ink">Ask this document</p>
          <p className="truncate text-2xs text-ink-3">{title}</p>
        </div>
        <Link
          href={`/assistant?doc=${documentId}`}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium text-ink-2 hover:bg-sunken hover:text-ink"
        >
          <ExternalLink className="h-3 w-3" /> Assistant
        </Link>
        <button onClick={onClose} aria-label="Close chat" className="rounded-md p-1.5 text-ink-3 hover:bg-sunken hover:text-ink">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div ref={thread} className="flex-1 space-y-5 overflow-y-auto scroll-thin px-4 py-4">
        {personalDataLevel(personalData) === "sensitive" && (
          <p role="note" className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-[12.5px] text-ink">
            <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" />
            <span>This document contains {sensitiveText(personalData)}. Answers may quote them, so share answers with care.</span>
          </p>
        )}
        {turns.length === 0 && (
          <div className="space-y-2">
            <p className="text-[13px] text-ink-2">Answers come only from this document and cite the page they came from.</p>
            {STARTERS.map((q) => (
              <button
                key={q}
                onClick={() => void ask(q)}
                className="block w-full rounded-lg border border-line bg-sunken px-3 py-2 text-left text-[13px] text-ink-2 transition hover:border-brand/40 hover:text-ink"
              >
                {q}
              </button>
            ))}
          </div>
        )}

        {turns.map((turn, i) => (
          <article key={i} className="space-y-2">
            <div className="flex justify-end">
              <p className="max-w-[90%] rounded-2xl rounded-br-md bg-rail px-3.5 py-2 text-[13.5px] text-rail-ink dark:bg-rail-2 dark:ring-1 dark:ring-line">
                {turn.question}
              </p>
            </div>
            {!turn.answer && !turn.error && (
              <p className="inline-flex items-center gap-2 text-[12.5px] text-ink-3">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading the document…
              </p>
            )}
            {turn.error && <ErrorState error={turn.error} onRetry={() => void ask(turn.question)} />}
            {turn.answer && (
              <div className="rounded-xl border border-line bg-canvas p-3.5 text-[14px]">
                <AnswerBody
                  text={turn.answer.answer}
                  active={active?.turn === i ? active.index : null}
                  onCite={(n) => cite(i, turn.answer!, n)}
                />
                {turn.answer.citations.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-2.5">
                    {turn.answer.citations.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => cite(i, turn.answer!, c.index)}
                        title={c.quote}
                        className={cn(
                          "rounded-md px-1.5 py-0.5 font-mono text-2xs transition",
                          active?.turn === i && active.index === c.index
                            ? "bg-brand text-white dark:text-rail"
                            : "bg-brand-soft text-brand-ink hover:bg-brand hover:text-white",
                        )}
                      >
                        [{c.index}] {c.clause ? `§${c.clause} · ` : ""}p.{c.page}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </article>
        ))}
      </div>

      <div className="border-t border-line p-3">
        <Composer
          disabled={busy}
          scope={[title]}
          placeholder="Ask about this document…"
          onSubmit={(q) => void ask(q)}
        />
      </div>
    </div>
  );
}
