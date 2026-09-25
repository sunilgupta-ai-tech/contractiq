import { Card, CardHeader } from "@/components/ui/card";
import type { KeyDate } from "@/types";
import { cn } from "@/utils/cn";
import { daysUntil } from "@/utils/format";

const kindStyle = { notice: "bg-warn", renewal: "bg-info", expiry: "bg-ink-3" } as const;

export function KeyDates({ dates }: { dates: KeyDate[] }) {
  return (
    <Card>
      <CardHeader eyebrow="Obligations" title="Upcoming key dates" />
      <ol className="relative px-5 py-4">
        <span className="absolute bottom-6 left-[29px] top-6 w-px bg-line" aria-hidden />
        {dates.map((d) => {
          const days = daysUntil(d.date);
          const dt = new Date(d.date);
          return (
            <li key={d.date + d.label} className="relative flex gap-4 py-2.5">
              <span className={cn("relative z-10 mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-surface", kindStyle[d.kind])} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="truncate text-[13.5px] font-medium text-ink">{d.label}</p>
                  <span className={cn("num shrink-0 text-2xs font-semibold", days <= 14 ? "text-danger" : "text-ink-3")}>
                    {days <= 0 ? "Today" : `in ${days}d`}
                  </span>
                </div>
                <p className="truncate text-2xs text-ink-3">
                  {dt.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })} · {d.documentTitle}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
