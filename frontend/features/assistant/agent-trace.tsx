"use client";

import { useState } from "react";
import { Check, ChevronDown, Loader2, Workflow } from "lucide-react";
import type { AgentStep } from "@/types";
import { cn } from "@/utils/cn";

/** Visualises the LangGraph run: each node, what it did and how long it took. */
export function AgentTrace({ steps, live }: { steps: AgentStep[]; live?: boolean }) {
  const [open, setOpen] = useState(!!live);
  const total = steps.reduce((n, s) => n + s.durationMs, 0);
  const expanded = open || live;

  return (
    <div className="rounded-xl border border-line bg-sunken/70">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-[12.5px] text-ink-2">
        <Workflow className="h-3.5 w-3.5 text-brand" />
        <span className="font-medium text-ink">{live ? "Agent is working…" : "Agent trace"}</span>
        <span className="text-ink-3">· {steps.length} steps{!live && ` · ${(total / 1000).toFixed(2)}s`}</span>
        <ChevronDown className={cn("ml-auto h-4 w-4 transition", expanded && "rotate-180")} />
      </button>
      {expanded && (
        <ol className="border-t border-line px-3.5 py-2">
          {steps.map((s) => (
            <li key={s.key} className="flex items-center gap-3 py-1.5 text-[12.5px]">
              <span
                className={cn(
                  "grid h-5 w-5 shrink-0 place-items-center rounded-full",
                  s.status === "done" && "bg-ok-soft text-ok",
                  s.status === "running" && "bg-info-soft text-info",
                  s.status === "pending" && "bg-surface text-ink-3 ring-1 ring-line",
                )}
              >
                {s.status === "done" && <Check className="h-3 w-3" />}
                {s.status === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
              </span>
              <span className={cn("w-40 shrink-0 font-medium", s.status === "pending" ? "text-ink-3" : "text-ink")}>{s.label}</span>
              <span className="min-w-0 flex-1 truncate text-ink-3">{s.status === "pending" ? "" : s.detail}</span>
              {s.status === "done" && <span className="num font-mono text-2xs text-ink-3">{s.durationMs}ms</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
