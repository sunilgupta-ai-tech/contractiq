"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Building2, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { PLANS, platformService, type OrgStatus, type Plan } from "@/services/platform-service";
import { formatBytes, relativeTime } from "@/utils/format";
import { UsageBar } from "./usage-bar";

const PAGE = 50;

export function OrganizationsView() {
  const params = useSearchParams();
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<OrgStatus | "">("");
  const [plan, setPlan] = useState<Plan | "">((params.get("plan") as Plan) ?? "");
  const [page, setPage] = useState(0);

  useEffect(() => {
    const next = input.trim();
    if (next === q) return;
    const timer = setTimeout(() => {
      setQ(next);
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [input, q]);

  const { data, error, loading, reload } = useAsync(
    () => platformService.organizations({ q, status, plan, offset: page * PAGE, limit: PAGE }),
    [q, status, plan, page],
  );
  const total = data?.total ?? 0;

  return (
    <>
      <PageHeader eyebrow="Platform" title="Organizations" description="Status, plan, limits and usage of every organization." />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
          <label className="flex h-9 w-full items-center gap-2 rounded-lg border border-line bg-surface px-3 text-ink-3 focus-within:border-brand/50 sm:w-72">
            <Search className="h-4 w-4" />
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Name, slug or a member's email…"
              aria-label="Search organizations"
              className="h-full w-full bg-transparent text-[13px] text-ink focus:outline-none focus-visible:outline-none focus-visible:ring-0"
            />
          </label>
          <select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value as OrgStatus | ""); setPage(0); }} className="h-9 rounded-lg border border-line bg-surface px-2.5 text-[13px] text-ink-2">
            <option value="">Any status</option>
            <option value="ACTIVE">Active</option>
            <option value="SUSPENDED">Suspended</option>
          </select>
          <select aria-label="Plan" value={plan} onChange={(e) => { setPlan(e.target.value as Plan | ""); setPage(0); }} className="h-9 rounded-lg border border-line bg-surface px-2.5 text-[13px] text-ink-2">
            <option value="">Any plan</option>
            {PLANS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>

        {loading && !data ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : !data?.items.length ? (
          <EmptyState icon={Building2} title="No organizations found" body="Try another search or filter." />
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[900px] text-left">
              <thead>
                <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">
                  <th className="px-5 py-3">Organization</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3">Plan</th>
                  <th className="w-44 px-3 py-3">Users</th>
                  <th className="w-44 px-3 py-3">Documents</th>
                  <th className="px-3 py-3 text-right">Storage</th>
                  <th className="px-5 py-3 text-right">Last active</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((org) => (
                  <tr key={org.id} className="group hover:bg-sunken">
                    <td className="px-5 py-3">
                      <Link href={`/platform/organizations/${org.id}`} className="block">
                        <span className="block text-[13.5px] font-medium text-ink group-hover:text-brand">{org.name}</span>
                        <span className="block text-2xs text-ink-3">{org.slug} · since {new Date(org.created_at).toLocaleDateString("en-GB", { month: "short", year: "numeric" })}</span>
                      </Link>
                    </td>
                    <td className="px-3 py-3">
                      <Badge tone={org.status === "ACTIVE" ? "ok" : "danger"}>{org.status === "ACTIVE" ? "Active" : org.status === "DELETING" ? "Deleting" : "Suspended"}</Badge>
                    </td>
                    <td className="px-3 py-3">
                      <Badge tone="brand">{org.plan}</Badge>
                    </td>
                    <td className="px-3 py-3">
                      <UsageBar used={org.usage.active_users} max={org.limits.max_users} />
                    </td>
                    <td className="px-3 py-3">
                      <UsageBar used={org.usage.documents} max={org.limits.max_documents} />
                    </td>
                    <td className="num px-3 py-3 text-right text-[12.5px] text-ink-2">{formatBytes(org.usage.storage_bytes)}</td>
                    <td className="num px-5 py-3 text-right text-[12.5px] text-ink-3">{org.last_active_at ? relativeTime(org.last_active_at) : "Never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > 0 && (
          <div className="flex items-center justify-between border-t border-line px-5 py-3 text-[12.5px] text-ink-3">
            <span className="num">
              {(page * PAGE + 1).toLocaleString()}–{Math.min(total, (page + 1) * PAGE).toLocaleString()} of {total.toLocaleString()}
            </span>
            <div className="flex gap-1">
              <button aria-label="Previous page" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="grid h-8 w-8 place-items-center rounded-lg border border-line disabled:opacity-40">
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button aria-label="Next page" disabled={(page + 1) * PAGE >= total} onClick={() => setPage((p) => p + 1)} className="grid h-8 w-8 place-items-center rounded-lg border border-line disabled:opacity-40">
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
