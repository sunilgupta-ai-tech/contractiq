import { AlertTriangle, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import type { ApiError } from "@/lib/api-client";
import { cn } from "@/utils/cn";
import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4", className)} />;
}

export function EmptyState({ icon: Icon, title, body, action }: { icon: LucideIcon; title: string; body: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <span className="mb-4 grid h-11 w-11 place-items-center rounded-xl border border-line bg-sunken text-ink-3">
        <Icon className="h-5 w-5" />
      </span>
      <p className="font-medium text-ink">{title}</p>
      <p className="mt-1 max-w-sm text-[13px] text-ink-2">{body}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
      <div className="min-w-0 flex-1 text-[13px]">
        <p className="font-medium text-ink">{error.message}</p>
        <p className="mt-0.5 font-mono text-2xs text-ink-3">
          {error.code}
          {error.requestId && ` · ref ${error.requestId}`}
        </p>
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
