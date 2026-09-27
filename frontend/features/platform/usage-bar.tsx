import { cn } from "@/utils/cn";

/** "12 / 25" with a bar; turns amber at 80% and red at the limit. */
export function UsageBar({ used, max, format = (n: number) => n.toLocaleString() }: { used: number; max: number | null; format?: (n: number) => string }) {
  const share = max ? Math.min(100, (used / max) * 100) : 0;
  return (
    <span className="block">
      <span className="num block text-[12.5px] text-ink-2">
        {format(used)} <span className="text-ink-3">/ {max === null ? "∞" : format(max)}</span>
      </span>
      {max !== null && (
        <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-sunken">
          <span
            className={cn("block h-full", share >= 100 ? "bg-danger" : share >= 80 ? "bg-warn" : "bg-brand")}
            style={{ width: `${share}%` }}
          />
        </span>
      )}
    </span>
  );
}
