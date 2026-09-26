import { Fragment, type ReactNode } from "react";
import { cn } from "@/utils/cn";
import { parseAnswer } from "@/utils/answer-markdown";

/**
 * Renders an answer: headings, paragraphs and bullet/numbered lists (see
 * utils/answer-markdown.ts), with `[n]` as citation chips and `**x**` as
 * bold. Everything is rendered as React nodes — never via innerHTML —
 * because the answer can quote uploaded (untrusted) document content.
 */
export function AnswerBody({ text, active, onCite }: { text: string; active: number | null; onCite: (n: number) => void }) {
  const inline = (value: string) => <Inline text={value} active={active} onCite={onCite} />;
  return (
    <div className="space-y-3 text-[15px] leading-7 text-ink-2">
      {parseAnswer(text).map((block, i) => {
        if (block.kind === "heading") {
          return (
            <h4 key={i} className="pt-2 text-[13px] font-semibold uppercase tracking-[0.06em] text-ink first:pt-0">
              {block.text}
            </h4>
          );
        }
        if (block.kind === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={i} className={cn("space-y-1.5 pl-5", block.ordered ? "list-decimal" : "list-disc", "marker:text-ink-3")}>
              {block.items.map((item, j) => (
                <li key={j} className="pl-1">
                  {inline(item)}
                </li>
              ))}
            </List>
          );
        }
        return <p key={i}>{inline(block.text)}</p>;
      })}
    </div>
  );
}

function Inline({ text, active, onCite }: { text: string; active: number | null; onCite: (n: number) => void }) {
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
  return <>{nodes}</>;
}
