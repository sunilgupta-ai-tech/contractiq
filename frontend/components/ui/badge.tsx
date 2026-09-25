import type { ReactNode } from "react";
import { cn } from "@/utils/cn";

export type Tone = "neutral" | "brand" | "danger" | "warn" | "ok" | "info";

const tones: Record<Tone, string> = {
  neutral: "bg-sunken text-ink-2 ring-line",
  brand: "bg-brand-soft text-brand-ink ring-brand/20",
  danger: "bg-danger-soft text-danger ring-danger/20",
  warn: "bg-warn-soft text-warn ring-warn/20",
  ok: "bg-ok-soft text-ok ring-ok/20",
  info: "bg-info-soft text-info ring-info/20",
};

export function Badge({ tone = "neutral", className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-medium ring-1 ring-inset", tones[tone], className)}>
      {children}
    </span>
  );
}
