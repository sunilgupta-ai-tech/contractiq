import type { LucideIcon } from "lucide-react";
import { CalendarClock, FileCheck2, Loader, ShieldAlert } from "lucide-react";
import type { ContractDocument, KeyDate, RiskFinding } from "@/types";
import { daysUntil, isProcessing } from "@/utils/format";
import { cn } from "@/utils/cn";

interface Kpi {
  label: string;
  value: number;
  hint: string;
  icon: LucideIcon;
  accent: string;
}

export function computeKpis(docs: ContractDocument[], findings: RiskFinding[], dates: KeyDate[]): Kpi[] {
  const indexed = docs.filter((d) => d.status === "COMPLETED");
  return [
    { label: "Contracts indexed", value: indexed.length, hint: `${indexed.reduce((n, d) => n + d.pages, 0)} pages searchable`, icon: FileCheck2, accent: "text-brand bg-brand-soft" },
    { label: "In processing", value: docs.filter((d) => isProcessing(d.status)).length, hint: "OCR, chunking, embedding", icon: Loader, accent: "text-info bg-info-soft" },
    { label: "Open high-risk clauses", value: findings.filter((f) => f.severity === "high" && f.status !== "accepted").length, hint: `${findings.length} findings in total`, icon: ShieldAlert, accent: "text-danger bg-danger-soft" },
    { label: "Deadlines · 90 days", value: dates.filter((d) => daysUntil(d.date) <= 90 && daysUntil(d.date) >= 0).length, hint: "Renewals and notice windows", icon: CalendarClock, accent: "text-warn bg-warn-soft" },
  ];
}

export function KpiRow({ kpis }: { kpis: Kpi[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {kpis.map((k, i) => (
        <div key={k.label} className="card animate-fade-up p-4 sm:p-5" style={{ animationDelay: `${i * 50}ms` }}>
          <div className="flex items-start justify-between">
            <p className="text-[13px] font-medium text-ink-2">{k.label}</p>
            <span className={cn("grid h-8 w-8 place-items-center rounded-lg", k.accent)}>
              <k.icon className="h-4 w-4" />
            </span>
          </div>
          <p className="display num mt-3 text-[38px] leading-none">{k.value}</p>
          <p className="mt-2 text-2xs text-ink-3">{k.hint}</p>
        </div>
      ))}
    </div>
  );
}
