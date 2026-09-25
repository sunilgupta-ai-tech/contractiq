import { Check, X } from "lucide-react";
import type { DocumentStatus } from "@/types";
import { cn } from "@/utils/cn";

// The visible pipeline mirrors the worker's stages one-to-one.
const STEPS: { key: DocumentStatus; label: string }[] = [
  { key: "QUEUED", label: "Queued" },
  { key: "PROCESSING", label: "Parse" },
  { key: "OCR_PROCESSING", label: "OCR" },
  { key: "CHUNKING", label: "Chunk" },
  { key: "EMBEDDING", label: "Embed" },
  { key: "INDEXING", label: "Index" },
  { key: "COMPLETED", label: "Ready" },
];

export function PipelineStepper({ status, failedAt }: { status: DocumentStatus; failedAt?: DocumentStatus }) {
  const failed = status === "FAILED";
  const currentKey = failed ? (failedAt ?? "PROCESSING") : status === "UPLOADED" ? "QUEUED" : status;
  const currentIndex = STEPS.findIndex((s) => s.key === currentKey);

  return (
    <ol className="flex items-center gap-1" aria-label="Processing pipeline">
      {STEPS.map((step, i) => {
        const done = i < currentIndex || status === "COMPLETED";
        const active = i === currentIndex && status !== "COMPLETED";
        return (
          <li key={step.key} className="flex items-center gap-1">
            <span
              title={step.label}
              className={cn(
                "flex h-5 items-center gap-1 rounded-full px-2 text-2xs font-medium transition-colors",
                done && "bg-ok-soft text-ok",
                active && !failed && "bg-info-soft text-info ring-1 ring-inset ring-info/30",
                active && failed && "bg-danger-soft text-danger ring-1 ring-inset ring-danger/30",
                !done && !active && "bg-sunken text-ink-3",
              )}
            >
              {done && <Check className="h-3 w-3" />}
              {active && failed && <X className="h-3 w-3" />}
              {active && !failed && <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current" />}
              {step.label}
            </span>
            {i < STEPS.length - 1 && <span className={cn("h-px w-2", done ? "bg-ok/50" : "bg-line")} />}
          </li>
        );
      })}
    </ol>
  );
}
