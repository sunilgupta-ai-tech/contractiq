"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, ScrollText } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { adminService } from "@/services/admin-service";
import { relativeTime } from "@/utils/format";

const PAGE = 50;

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "Everything" },
  { key: "auth.", label: "Sign-ins" },
  { key: "document.", label: "Documents" },
  { key: "query.", label: "AI questions" },
  { key: "user.", label: "Users" },
  { key: "role.", label: "Roles" },
  { key: "invitation.", label: "Invitations" },
];

const LABELS: Record<string, string> = {
  "auth.login": "Signed in",
  "auth.login_failed": "Failed sign-in",
  "auth.register": "Created the organization",
  "document.upload": "Uploaded a document",
  "document.download": "Downloaded a document",
  "document.delete": "Deleted a document",
  "document.access": "Changed who can see a document",
  "document.reviewed": "Marked a document reviewed",
  "query.run": "Asked the Assistant",
  "user.create": "Added a user",
  "user.update": "Changed a user",
  "role.create": "Created a role",
  "role.update": "Changed a role",
  "role.delete": "Deleted a role",
  "invitation.create": "Invited someone",
  "invitation.accept": "Joined by invitation",
  "invitation.revoke": "Revoked an invitation",
};

/** Phase 22: who did what in the organization. IDs and parameters only —
 *  never document text or questions. */
export function AuditView() {
  const [action, setAction] = useState("");
  const [page, setPage] = useState(0);
  const { data, error, loading, reload } = useAsync(
    () => adminService.audit({ action, offset: page * PAGE, limit: PAGE }),
    [action, page],
  );
  const total = data?.total ?? 0;

  return (
    <>
      <PageHeader eyebrow="Organization" title="Audit log" description="Sign-ins, uploads, downloads, deletions, access changes and AI questions — who, what and when." />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Card>
        <div className="flex flex-wrap gap-1 border-b border-line px-5 py-3">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => {
                setAction(f.key);
                setPage(0);
              }}
              className={`rounded-md px-2.5 py-1 text-[13px] ${action === f.key ? "bg-sunken font-medium text-ink" : "text-ink-2 hover:text-ink"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
        {loading && !data ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : !data?.items.length ? (
          <EmptyState icon={ScrollText} title="Nothing recorded" body="Try another filter." />
        ) : (
          <ul className="divide-y divide-line">
            {data.items.map((e) => (
              <li key={e.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-5 py-3 text-[13px]">
                <span className="num w-28 shrink-0 text-ink-3" title={new Date(e.created_at).toLocaleString()}>
                  {relativeTime(e.created_at)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-ink">{e.actor_name ?? "Someone"}</span>
                  <span className="text-ink-2"> — {LABELS[e.action] ?? e.action}</span>
                  {Object.keys(e.metadata).length > 0 && (
                    <code className="mt-0.5 block truncate font-mono text-2xs text-ink-3">{JSON.stringify(e.metadata)}</code>
                  )}
                </span>
                {e.ip_address && <span className="font-mono text-2xs text-ink-3">{e.ip_address}</span>}
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
