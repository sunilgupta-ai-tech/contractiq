"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Clock, Cpu, MessageSquareText } from "lucide-react";
import { ErrorState } from "@/components/ui/states";
import { ApiError } from "@/lib/api-client";
import { demoAgentSteps, demoDocuments, suggestedQuestions } from "@/lib/demo/fixtures";
import { queryService } from "@/services/query-service";
import type { AgentStep, QueryAnswer } from "@/types";
import { AgentTrace } from "./agent-trace";
import { AnswerBody } from "./answer-body";
import { Composer } from "./composer";
import { EvidencePanel } from "./evidence-panel";

interface Turn {
  question: string;
  answer: QueryAnswer | null;
  error: ApiError | null;
  liveSteps: AgentStep[];
}

export function AssistantView() {
  const params = useSearchParams();
  const initialDoc = demoDocuments.find((d) => d.id === params.get("doc"));
  const [scope, setScope] = useState<string[]>(initialDoc ? [initialDoc.title] : []);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [focusTurn, setFocusTurn] = useState(0);
  const busy = turns.some((t) => !t.answer && !t.error);
  const asked = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);

  const ask = useCallback(async (question: string) => {
    const index = turns.length;
    const pending = demoAgentSteps.map((s) => ({ ...s, status: "pending" as const }));
    setTurns((t) => [...t, { question, answer: null, error: null, liveSteps: pending }]);
    setFocusTurn(index);
    setActive(null);

    // Animate the agent's progress while the request is in flight.
    let step = 0;
    const timer = setInterval(() => {
      step++;
      setTurns((t) =>
        t.map((turn, i) =>
          i !== index ? turn : { ...turn, liveSteps: turn.liveSteps.map((s, j) => ({ ...s, status: j < step ? "done" : j === step ? "running" : "pending" })) },
        ),
      );
    }, 300);

    try {
      const answer = await queryService.ask({ question, documentIds: [] });
      setTurns((t) => t.map((turn, i) => (i === index ? { ...turn, answer } : turn)));
      setActive(answer.citations[0]?.index ?? null);
    } catch (err) {
      const error = err instanceof ApiError ? err : new ApiError("Something went wrong.", "UNKNOWN", 0, null);
      setTurns((t) => t.map((turn, i) => (i === index ? { ...turn, error } : turn)));
    } finally {
      clearInterval(timer);
    }
  }, [turns.length]);

  useEffect(() => {
    const q = params.get("q");
    if (q && !asked.current) {
      asked.current = true;
      void ask(q);
    }
  }, [params, ask]);

  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [turns]);

  const focused = turns[focusTurn]?.answer ?? null;

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
      <div className="flex min-w-0 min-h-[calc(100vh-9rem)] flex-col">
        <div className="mb-5 animate-fade-up">
          <p className="eyebrow mb-2">Agentic RAG</p>
          <h1 className="display text-[30px] leading-tight">Contract assistant</h1>
        </div>

        <div className="flex-1 space-y-8 pb-6">
          {turns.length === 0 && (
            <div className="card animate-fade-up p-6 sm:p-8">
              <MessageSquareText className="mb-4 h-6 w-6 text-brand" />
              <p className="font-serif text-[21px] leading-snug text-ink">What would you like to know about your contracts?</p>
              <p className="mt-2 max-w-lg text-[13.5px] text-ink-2">
                Questions are routed through a LangGraph agent: it picks relevant contracts, runs hybrid retrieval with a tenant filter, reranks, validates evidence and only then answers.
              </p>
              <div className="mt-6 grid gap-2 sm:grid-cols-2">
                {suggestedQuestions.map((q) => (
                  <button key={q} onClick={() => void ask(q)} className="rounded-xl border border-line bg-sunken px-4 py-3 text-left text-[13.5px] text-ink-2 transition hover:border-brand/40 hover:bg-brand-soft/40 hover:text-ink">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, i) => (
            <article key={i} className="animate-fade-up space-y-3" onClick={() => setFocusTurn(i)}>
              <div className="flex justify-end">
                <p className="max-w-[85%] rounded-2xl rounded-br-md bg-rail px-4 py-2.5 text-[14.5px] text-rail-ink dark:bg-rail-2 dark:ring-1 dark:ring-line">{turn.question}</p>
              </div>
              <div className="space-y-3">
                <AgentTrace steps={turn.answer?.steps ?? turn.liveSteps} live={!turn.answer && !turn.error} />
                {turn.error && <ErrorState error={turn.error} onRetry={() => void ask(turn.question)} />}
                {turn.answer && (
                  <div className="card p-5">
                    <AnswerBody text={turn.answer.answer} active={focusTurn === i ? active : null} onCite={(n) => { setFocusTurn(i); setActive(n); }} />
                    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-3 text-2xs text-ink-3">
                      <span className="inline-flex items-center gap-1"><Cpu className="h-3 w-3" /> {turn.answer.model}</span>
                      <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> {(turn.answer.latencyMs / 1000).toFixed(1)}s</span>
                      <span>AI-assisted analysis · verify with counsel</span>
                    </div>
                  </div>
                )}
              </div>
            </article>
          ))}
          <div ref={bottom} />
        </div>

        <div className="sticky bottom-4 z-10">
          <Composer disabled={busy} scope={scope} onClearScope={(s) => setScope((list) => list.filter((x) => x !== s))} onSubmit={(q) => void ask(q)} />
        </div>
      </div>

      <aside className="hidden xl:block">
        <div className="sticky top-20 h-[calc(100vh-7rem)]">
          <EvidencePanel answer={focused} active={active} onSelect={setActive} />
        </div>
      </aside>
    </div>
  );
}
