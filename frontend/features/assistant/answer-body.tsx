import { Fragment, type ReactNode } from "react";
import { cn } from "@/utils/cn";

/**
 * Renders answer text, turning `[n]` into citation chips and `**x**` into
 * bold. Text is rendered as React nodes — never via innerHTML — because the
 * answer can quote uploaded (untrusted) document content.
 */
export function AnswerBody({ text, active, onCite }: { text: string; active: number | null; onCite: (n: number) => void }) {
  const parts = text.split(/(\[\d+\]|\*\*[^*]+\*\*)/g);
  const nodes: ReactNode[] = parts.map((part, i) => {
    const cite = part.match(/^\[(\d+)\]$/);
    if (cite) {
      const n = Number(cite[1]);
      return (
        <button
          key={i}
          onClick={() => onCite(n)}
          className={cn(
            "mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded px-1 align-middle font-mono text-[10.5px] font-semibold leading-none transition",
            active === n ? "bg-brand text-white" : "bg-brand-soft text-brand-ink hover:bg-brand hover:text-white",
          )}
          aria-label={`Citation ${n}`}
        >
          {n}
        </button>
      );
    }
    const bold = part.match(/^\*\*(.+)\*\*$/);
    if (bold) return <strong key={i} className="font-semibold text-ink">{bold[1]}</strong>;
    return <Fragment key={i}>{part}</Fragment>;
  });
  return <p className="text-[15px] leading-7 text-ink-2">{nodes}</p>;
}
