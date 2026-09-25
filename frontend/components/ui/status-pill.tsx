import { AlertCircle, CheckCircle2 } from "lucide-react";
import type { DocumentStatus } from "@/types";
import { cn } from "@/utils/cn";
import { statusLabel } from "@/utils/format";

/** Document processing status. In-flight states show a live progress bar. */
export function StatusPill({ status, progress }: { status: DocumentStatus; progress?: number }) {
  if (status === "COMPLETED") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ok">
        <CheckCircle2 className="h-3.5 w-3.5" /> Ready
      </span>
    );
  }
  if (status === "FAILED") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-danger">
        <AlertCircle className="h-3.5 w-3.5" /> Failed
      </span>
    );
  }
  return (
    <span className="inline-flex min-w-[124px] flex-col gap-1">
      <span className="flex items-center justify-between gap-2 text-[13px] font-medium text-info">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current" aria-hidden />
          {statusLabel(status)}
        </span>
        {progress !== undefined && <span className="num text-2xs text-ink-3">{progress}%</span>}
      </span>
      <span className="h-1 w-full overflow-hidden rounded-full bg-line">
        <span
          className={cn("block h-full rounded-full bg-info transition-[width] duration-700")}
          style={{ width: `${Math.max(4, progress ?? 0)}%` }}
        />
      </span>
    </span>
  );
}
