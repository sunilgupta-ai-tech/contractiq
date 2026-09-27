"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, Ban, CheckCircle2, Loader2, Save } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { ApiError } from "@/lib/api-client";
import { PLANS, platformService, type Limits, type OrgDetail, type OrgUpdate, type Plan } from "@/services/platform-service";
import { formatBytes, formatDate, relativeTime } from "@/utils/format";
import { isSuperAdmin, usePlatformMe } from "./platform-shell";
import { UsageBar } from "./usage-bar";

const MB = 1024 * 1024;
const LIMIT_FIELDS: { key: keyof Limits; label: string; unit: string }[] = [
  { key: "max_users", label: "Active users", unit: "users" },
  { key: "max_documents", label: "Documents", unit: "documents" },
  { key: "max_storage_mb", label: "Storage", unit: "MB" },
];

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError("Something went wrong.", "UNKNOWN", 0, null);
}

export function OrganizationDetailView({ id }: { id: string }) {
  const me = usePlatformMe();
  const canEdit = isSuperAdmin(me);
  const { data: loaded, error, reload } = useAsync(() => platformService.organization(id), [id]);
  const [org, setOrg] = useState<OrgDetail | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (loaded) setOrg(loaded);
  }, [loaded]);

  async function apply(update: OrgUpdate) {
    setBusy(true);
    setActionError(null);
    try {
      setOrg(await platformService.updateOrganization(id, update));
    } catch (err) {
      setActionError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function suspend() {
    const reason = window.prompt("Why is this organization being suspended? (shown in the audit log)");
    if (reason?.trim()) await apply({ status: "SUSPENDED", suspended_reason: reason.trim() });
  }

  async function setMember(userId: string, active: boolean) {
    setActionError(null);
    try {
      setOrg(await platformService.setMemberActive(id, userId, active));
    } catch (err) {
      setActionError(asApiError(err));
    }
  }

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!org) return <Skeleton className="h-[60vh] rounded-xl" />;
  const suspended = org.status === "SUSPENDED";

  return (
    <div className="space-y-5">
      <Link href="/platform/organizations" className="inline-flex items-center gap-1.5 text-[13px] text-ink-2 hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Organizations
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <Badge tone={suspended ? "danger" : "ok"}>{suspended ? "Suspended" : "Active"}</Badge>
            <Badge tone="brand">{org.plan}</Badge>
          </div>
          <h1 className="display text-[30px] leading-tight">{org.name}</h1>
          <p className="mt-1 text-[13px] text-ink-3">
            {org.slug} · created {formatDate(org.created_at)} · last active {org.last_active_at ? relativeTime(org.last_active_at) : "never"}
          </p>
        </div>
        {canEdit &&
          (suspended ? (
            <Button disabled={busy} onClick={() => void apply({ status: "ACTIVE" })}>
              <CheckCircle2 className="h-4 w-4" /> Reactivate
            </Button>
          ) : (
            <Button variant="danger" disabled={busy} onClick={() => void suspend()}>
              <Ban className="h-4 w-4" /> Suspend
            </Button>
          ))}
      </div>

      {suspended && (
        <div className="rounded-xl border border-danger/25 bg-danger-soft px-4 py-3 text-[13px] text-ink">
          <strong>Suspended {formatDate(org.suspended_at)}.</strong> {org.suspended_reason} — its users cannot sign in.
        </div>
      )}
      {actionError && <ErrorState error={actionError} />}

      <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="Usage" />
            <div className="grid gap-5 p-5 sm:grid-cols-3">
              <Usage label="Active users" used={org.usage.active_users} max={org.limits.max_users} />
              <Usage label="Documents" used={org.usage.documents} max={org.limits.max_documents} />
              <Usage
                label="Storage"
                used={org.usage.storage_bytes}
                max={org.limits.max_storage_mb === null ? null : org.limits.max_storage_mb * MB}
                format={formatBytes}
              />
            </div>
            <div className="flex flex-wrap gap-2 border-t border-line px-5 py-3 text-2xs text-ink-3">
              {Object.entries(org.documents_by_type).map(([type, n]) => (
                <span key={type} className="rounded-md bg-sunken px-2 py-0.5">
                  {type} {n}
                </span>
              ))}
              {org.failed_documents > 0 && <span className="rounded-md bg-danger-soft px-2 py-0.5 text-danger">{org.failed_documents} failed</span>}
            </div>
          </Card>

          <Card>
            <CardHeader title={`Members (${org.members.length})`} />
            <div className="overflow-x-auto scroll-thin">
              <table className="w-full min-w-[640px] text-left">
                <thead>
                  <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">
                    <th className="px-5 py-3">Member</th>
                    <th className="px-3 py-3">Role</th>
                    <th className="px-3 py-3">Status</th>
                    <th className="px-3 py-3">Last sign-in</th>
                    <th className="px-5 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {org.members.map((m) => (
                    <tr key={m.id}>
                      <td className="px-5 py-3">
                        <span className="block text-[13.5px] font-medium text-ink">{m.full_name}</span>
                        <span className="block text-2xs text-ink-3">{m.email}</span>
                      </td>
                      <td className="px-3 py-3 text-[13px] text-ink-2">{m.role_name}</td>
                      <td className="px-3 py-3">
                        <Badge tone={m.is_active ? "ok" : "neutral"}>{m.is_active ? "Active" : "Inactive"}</Badge>
                      </td>
                      <td className="num px-3 py-3 text-[12.5px] text-ink-3">{m.last_login_at ? relativeTime(m.last_login_at) : "Never"}</td>
                      <td className="px-5 py-3 text-right">
                        {canEdit && (
                          <Button size="sm" variant="ghost" onClick={() => void setMember(m.id, !m.is_active)}>
                            {m.is_active ? "Deactivate" : "Activate"}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="border-t border-line px-5 py-3 text-2xs text-ink-3">
              The console shows accounts and counts only — never an organization&apos;s documents, questions or answers.
            </p>
          </Card>
        </div>

        <PlanCard org={org} canEdit={canEdit} busy={busy} onApply={apply} />
      </div>
    </div>
  );
}

function Usage({ label, used, max, format }: { label: string; used: number; max: number | null; format?: (n: number) => string }) {
  return (
    <div>
      <p className="mb-1.5 text-[13px] text-ink-2">{label}</p>
      <UsageBar used={used} max={max} format={format} />
    </div>
  );
}

function PlanCard({ org, canEdit, busy, onApply }: { org: OrgDetail; canEdit: boolean; busy: boolean; onApply: (u: OrgUpdate) => Promise<void> }) {
  const [plan, setPlan] = useState<Plan>(org.plan);
  const [limits, setLimits] = useState<Record<keyof Limits, string>>(() => toStrings(org.limits));

  useEffect(() => {
    setPlan(org.plan);
    setLimits(toStrings(org.limits));
  }, [org]);

  async function save() {
    const update: OrgUpdate = { unlimited: [] };
    for (const { key } of LIMIT_FIELDS) {
      const value = limits[key].trim();
      if (value === "") update.unlimited!.push(key);
      else update[key] = Number(value);
    }
    await onApply(update);
  }

  return (
    <Card className="h-fit">
      <CardHeader title="Plan and limits" />
      <div className="space-y-4 p-5">
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-medium text-ink">Plan</span>
          <div className="flex gap-2">
            <select
              disabled={!canEdit || busy}
              value={plan}
              onChange={(e) => setPlan(e.target.value as Plan)}
              className="h-9 flex-1 rounded-lg border border-line bg-surface px-2.5 text-[13px] text-ink"
            >
              {PLANS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            {canEdit && (
              <Button size="sm" variant="secondary" disabled={busy || plan === org.plan} onClick={() => void onApply({ plan })}>
                Change plan
              </Button>
            )}
          </div>
          <span className="mt-1.5 block text-2xs text-ink-3">Changing the plan resets the limits to its defaults.</span>
        </label>
        <div className="space-y-3 border-t border-line pt-4">
          {LIMIT_FIELDS.map(({ key, label, unit }) => (
            <label key={key} className="flex items-center justify-between gap-3">
              <span className="text-[13px] text-ink-2">{label}</span>
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  disabled={!canEdit || busy}
                  value={limits[key]}
                  placeholder="∞"
                  onChange={(e) => setLimits((l) => ({ ...l, [key]: e.target.value }))}
                  className="num h-9 w-28 rounded-lg border border-line bg-surface px-2.5 text-right text-[13px] text-ink"
                />
                <span className="w-16 text-2xs text-ink-3">{unit}</span>
              </span>
            </label>
          ))}
          <p className="text-2xs text-ink-3">Leave empty for unlimited. Over-limit organizations keep their data; they just cannot add more.</p>
          {canEdit && (
            <Button size="sm" disabled={busy} onClick={() => void save()}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Save limits
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

function toStrings(limits: Limits): Record<keyof Limits, string> {
  return {
    max_users: limits.max_users?.toString() ?? "",
    max_documents: limits.max_documents?.toString() ?? "",
    max_storage_mb: limits.max_storage_mb?.toString() ?? "",
  };
}
