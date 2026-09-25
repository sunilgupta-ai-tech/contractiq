"use client";

import { useState } from "react";
import { ArrowUp, FileText, X } from "lucide-react";
import { MAX_QUERY_LENGTH, validateQuestion } from "@/utils/validation";

export function Composer({ disabled, scope, onClearScope, onSubmit }: { disabled: boolean; scope: string[]; onClearScope: (s: string) => void; onSubmit: (q: string) => void }) {
  const [value, setValue] = useState("");
  const [hint, setHint] = useState<string | null>(null);

  function submit() {
    const check = validateQuestion(value);
    if (!check.ok) return setHint(check.reason);
    setHint(null);
    onSubmit(value.trim());
    setValue("");
  }

  return (
    <div className="card p-2 focus-within:border-brand/50 focus-within:shadow-lift">
      <div className="flex flex-wrap items-center gap-1.5 px-2 pt-1">
        <span className="text-2xs text-ink-3">Scope:</span>
        {scope.length === 0 && <span className="rounded-md bg-sunken px-2 py-0.5 text-2xs text-ink-2">All accessible contracts</span>}
        {scope.map((s) => (
          <span key={s} className="inline-flex items-center gap-1 rounded-md bg-brand-soft px-2 py-0.5 text-2xs font-medium text-brand-ink">
            <FileText className="h-3 w-3" /> {s}
            <button onClick={() => onClearScope(s)} aria-label={`Remove ${s}`}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex items-end gap-2">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!disabled) submit();
            }
          }}
          rows={2}
          maxLength={MAX_QUERY_LENGTH}
          placeholder="Ask about terms, obligations, risks or differences between versions…"
          className="max-h-40 min-h-[52px] flex-1 resize-none bg-transparent px-2 py-2 text-[14.5px] text-ink placeholder:text-ink-3 focus:outline-none"
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="mb-1 mr-1 grid h-9 w-9 place-items-center rounded-lg bg-brand text-white transition hover:bg-brand/90 disabled:opacity-40 dark:text-rail"
          aria-label="Send"
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      </div>
      <p className="px-2 pb-1 text-2xs text-ink-3">
        {hint ? <span className="text-danger">{hint}</span> : "Enter to send · Shift+Enter for a new line · Answers cite sources and are not legal advice."}
      </p>
    </div>
  );
}
