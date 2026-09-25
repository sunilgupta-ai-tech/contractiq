import Link from "next/link";
import { Card, CardHeader } from "@/components/ui/card";
import type { RiskFinding } from "@/types";

export function RiskExposure({ findings }: { findings: RiskFinding[] }) {
  const byDoc = new Map<string, { title: string; high: number; medium: number; low: number }>();
  for (const f of findings) {
    const row = byDoc.get(f.documentId) ?? { title: f.documentTitle, high: 0, medium: 0, low: 0 };
    row[f.severity]++;
    byDoc.set(f.documentId, row);
  }
  const rows = [...byDoc.entries()].sort((a, b) => b[1].high * 3 + b[1].medium - (a[1].high * 3 + a[1].medium));
  const max = Math.max(...rows.map(([, r]) => r.high + r.medium + r.low), 1);

  return (
    <Card>
      <CardHeader
        eyebrow="Risk"
        title="Exposure by contract"
        action={<Link href="/risk" className="text-[13px] font-medium text-brand hover:underline">Review</Link>}
      />
      <ul className="space-y-4 px-5 py-5">
        {rows.map(([id, r]) => {
          const total = r.high + r.medium + r.low;
          return (
            <li key={id}>
              <div className="mb-1.5 flex items-baseline justify-between gap-3">
                <p className="truncate text-[13px] font-medium text-ink">{r.title}</p>
                <span className="num text-2xs text-ink-3">{total} flags</span>
              </div>
              <div className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-sunken" style={{ width: `${(total / max) * 100}%` }}>
                {r.high > 0 && <span className="h-full bg-danger" style={{ flex: r.high }} title={`${r.high} high`} />}
                {r.medium > 0 && <span className="h-full bg-warn" style={{ flex: r.medium }} title={`${r.medium} medium`} />}
                {r.low > 0 && <span className="h-full bg-ok" style={{ flex: r.low }} title={`${r.low} low`} />}
              </div>
            </li>
          );
        })}
      </ul>
      <div className="flex gap-4 border-t border-line px-5 py-3 text-2xs text-ink-3">
        {[
          ["bg-danger", "High"],
          ["bg-warn", "Medium"],
          ["bg-ok", "Low"],
        ].map(([swatch, label]) => (
          <span key={label} className="inline-flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-sm ${swatch}`} /> {label}
          </span>
        ))}
      </div>
    </Card>
  );
}
