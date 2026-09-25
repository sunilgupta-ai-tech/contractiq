import type { RiskLevel } from "@/types";
import { Badge } from "./badge";

const map = { high: ["danger", "High"], medium: ["warn", "Medium"], low: ["ok", "Low"] } as const;

export function RiskBadge({ level, count }: { level: RiskLevel | null; count?: number }) {
  if (!level) return <span className="text-2xs text-ink-3">—</span>;
  const [tone, label] = map[level];
  return (
    <Badge tone={tone}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {label}
      {count !== undefined && count > 0 && <span className="num opacity-70">· {count}</span>}
    </Badge>
  );
}
