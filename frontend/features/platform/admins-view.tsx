"use client";

import { useState } from "react";
import { Loader2, Lock, UserPlus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { ApiError } from "@/lib/api-client";
import { platformService, type PlatformAdmin, type PlatformRole } from "@/services/platform-service";
import { relativeTime } from "@/utils/format";
import { isSuperAdmin, usePlatformMe } from "./platform-shell";

const ROLE_LABEL: Record<PlatformRole, string> = { SUPER_ADMIN: "Super admin", SUPPORT: "Support (read-only)" };
const input =
  "h-10 w-full rounded-lg border border-line bg-surface px-3 text-[13.5px] text-ink focus:border-brand/60 focus:outline-none";

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError("Something went wrong.", "UNKNOWN", 0, null);
}

export function PlatformAdminsView() {
  const me = usePlatformMe();
  const { data, error, reload } = useAsync(() => platformService.admins(), []);
  const [adding, setAdding] = useState(false);
  const [actionError, setActionError] = useState<ApiError | null>(null);

  if (me && !isSuperAdmin(me)) {
    return (
      <Card>
        <EmptyState icon={Lock} title="Super admins only" body="Support admins can view organizations and the audit log." />
      </Card>
    );
  }

  async function update(admin: PlatformAdmin, body: { role?: PlatformRole; is_active?: boolean }) {
    setActionError(null);
    try {
      await platformService.updateAdmin(admin.id, body);
      reload();
    } catch (err) {
      setActionError(asApiError(err));
    }
  }

  return (
    <>
      <PageHeader eyebrow="Platform" title="Platform admins" description="People who operate DocuNexa AI. Support admins can look; super admins can change." />
      <div className="space-y-4">
        {(error || actionError) && <ErrorState error={(actionError ?? error)!} />}
        {adding && <AddAdmin onDone={() => { setAdding(false); reload(); }} onCancel={() => setAdding(false)} />}
        <Card>
          <CardHeader
            title="Admins"
            action={!adding && <Button size="sm" onClick={() => setAdding(true)}><UserPlus className="h-4 w-4" /> Add admin</Button>}
          />
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[680px] text-left">
              <thead>
                <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">
                  <th className="px-5 py-3">Admin</th>
                  <th className="px-3 py-3">Role</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3">Last sign-in</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(data ?? []).map((a) => {
                  const self = a.id === me?.id;
                  return (
                    <tr key={a.id} className={a.is_active ? "" : "opacity-60"}>
                      <td className="px-5 py-3">
                        <span className="block text-[13.5px] font-medium text-ink">
                          {a.full_name} {self && <Badge tone="brand">You</Badge>}
                        </span>
                        <span className="block text-2xs text-ink-3">{a.email}</span>
                      </td>
                      <td className="px-3 py-3">
                        {self ? (
                          <span className="text-[13px] text-ink-2">{ROLE_LABEL[a.role]}</span>
                        ) : (
                          <select value={a.role} onChange={(e) => void update(a, { role: e.target.value as PlatformRole })} className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px]">
                            <option value="SUPPORT">{ROLE_LABEL.SUPPORT}</option>
                            <option value="SUPER_ADMIN">{ROLE_LABEL.SUPER_ADMIN}</option>
                          </select>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <Badge tone={a.is_active ? "ok" : "neutral"}>{a.is_active ? "Active" : "Inactive"}</Badge>
                      </td>
                      <td className="num px-3 py-3 text-[12.5px] text-ink-3">{a.last_login_at ? relativeTime(a.last_login_at) : "Never"}</td>
                      <td className="px-5 py-3 text-right">
                        {!self && (
                          <Button size="sm" variant="ghost" onClick={() => void update(a, { is_active: !a.is_active })}>
                            {a.is_active ? "Deactivate" : "Activate"}
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}

function AddAdmin({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<PlatformRole>("SUPPORT");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await platformService.createAdmin({ full_name: fullName, email, password, role });
      onDone();
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Add a platform admin" />
      <form onSubmit={submit} className="grid gap-4 p-5 sm:grid-cols-2">
        {error && <div className="sm:col-span-2"><ErrorState error={error} /></div>}
        <input required placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} className={input} />
        <input required type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
        <input required minLength={12} type="text" autoComplete="off" placeholder="Temporary password (12+ characters)" value={password} onChange={(e) => setPassword(e.target.value)} className={`${input} font-mono`} />
        <select value={role} onChange={(e) => setRole(e.target.value as PlatformRole)} className={input}>
          <option value="SUPPORT">{ROLE_LABEL.SUPPORT}</option>
          <option value="SUPER_ADMIN">{ROLE_LABEL.SUPER_ADMIN}</option>
        </select>
        <div className="flex justify-end gap-2 sm:col-span-2">
          <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button type="submit" disabled={saving}>{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />} Add admin</Button>
        </div>
      </form>
    </Card>
  );
}
