"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronLeft, ChevronRight, ScrollText } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { platformService } from "@/services/platform-service";
import { relativeTime } from "@/utils/format";

const PAGE = 50;

const LABELS: Record<string, string> = {
  "platform.login": "Signed in",
  "platform.login_failed": "Failed sign-in",
  "organization.update": "Changed organization",
  "organization.member_update": "Changed member",
  "platform_admin.create": "Added platform admin",
  "platform_admin.update": "Changed platform admin",
  "platform_admin.create_cli": "Admin created from the command line",
  "platform_admin.reset_password_cli": "Password reset from the command line",
};

export function PlatformAuditView() {
  const [page, setPage] = useState(0);
  const { data, error, loading, reload } = useAsync(() => platformService.audit({ offset: page * PAGE, limit: PAGE }), [page]);
  const total = data?.total ?? 0;

  return (
    <>
      <PageHeader eyebrow="Platform" title="Audit log" description="Everything platform admins did, newest first." />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Card>
        {loading && !data ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : !data?.items.length ? (
          <EmptyState icon={ScrollText} title="Nothing recorded yet" body="Platform actions appear here." />
        ) : (
          <ul className="divide-y divide-line">
            {data.items.map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-5 py-3 text-[13px]">
                <span className="num w-28 shrink-0 text-ink-3" title={new Date(entry.created_at).toLocaleString()}>
                  {relativeTime(entry.created_at)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-ink">{LABELS[entry.action] ?? entry.action}</span>
                  <span className="text-ink-3"> · {entry.actor_email ?? "system"}</span>
                  {entry.organization_id && (
                    <Link href={`/platform/organizations/${entry.organization_id}`} className="ml-2 text-brand">
                      organization
                    </Link>
                  )}
                  {Object.keys(entry.details).length > 0 && (
                    <code className="mt-0.5 block truncate font-mono text-2xs text-ink-3">{JSON.stringify(entry.details)}</code>
                  )}
                </span>
                {entry.ip_address && <span className="font-mono text-2xs text-ink-3">{entry.ip_address}</span>}
              </li>
            ))}
          </ul>
        )}
        {total > PAGE && (
          <div className="flex justify-end gap-1 border-t border-line px-5 py-3">
            <button aria-label="Newer" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="grid h-8 w-8 place-items-center rounded-lg border border-line disabled:opacity-40">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button aria-label="Older" disabled={(page + 1) * PAGE >= total} onClick={() => setPage((p) => p + 1)} className="grid h-8 w-8 place-items-center rounded-lg border border-line disabled:opacity-40">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </Card>
    </>
  );
}
