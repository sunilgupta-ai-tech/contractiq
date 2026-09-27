"use client";

import { useMemo, useState } from "react";
import { Check, Copy, Link2, Loader2, Lock, Mail, Pencil, Plus, ShieldCheck, Trash2, UserPlus, UsersRound, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { ApiError } from "@/lib/api-client";
import { config } from "@/lib/config";
import { can, useMe, type Me } from "@/lib/session";
import { invitationService, teamService, type RoleInput } from "@/services/team-service";
import type { Permission, PermissionInfo, RoleDef, TeamMember } from "@/types";
import { cn } from "@/utils/cn";
import { relativeTime } from "@/utils/format";

type Tab = "members" | "roles";

const MIN_PASSWORD = 12; // backend policy (app/schemas/auth.py)

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError("Something went wrong.", "UNKNOWN", 0, null);
}

/** Members and roles of the organization (Phase 17). Every action is also
 *  checked by the API; the UI only hides what the user may not do. */
export function TeamView() {
  const me = useMe();
  const [tab, setTab] = useState<Tab>("members");
  const members = useAsync(() => (config.useDemoData ? Promise.resolve([]) : teamService.members()), []);
  const roles = useAsync(() => (config.useDemoData ? Promise.resolve([]) : teamService.roles()), []);
  const catalog = useAsync(() => (config.useDemoData ? Promise.resolve([]) : teamService.permissions()), []);

  if (config.useDemoData) {
    return (
      <>
        <PageHeader eyebrow="Organization" title="Team" />
        <Card>
          <EmptyState icon={UsersRound} title="Team management uses the live API" body="Switch off demo data to manage members and roles." />
        </Card>
      </>
    );
  }
  if (me && !can(me, "user:manage")) {
    return (
      <>
        <PageHeader eyebrow="Organization" title="Team" />
        <Card>
          <EmptyState icon={Lock} title="Only administrators manage the team" body="Ask your organization's admin if you need a different role." />
        </Card>
      </>
    );
  }

  const reloadAll = () => {
    members.reload();
    roles.reload();
  };

  return (
    <>
      <PageHeader
        eyebrow="Organization"
        title="Team"
        description="Who can use your workspace, and what each role may do. Changes take effect immediately."
      />
      <div role="tablist" aria-label="Team" className="mb-5 inline-flex gap-1 rounded-lg bg-sunken p-1">
        {(["members", "roles"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={cn(
              "rounded-md px-4 py-1.5 text-[13px] font-medium capitalize transition",
              tab === t ? "bg-surface text-ink shadow-card" : "text-ink-2 hover:text-ink",
            )}
          >
            {t}
            <span className="num ml-1.5 text-ink-3">{(t === "members" ? members.data?.length : roles.data?.length) ?? "·"}</span>
          </button>
        ))}
      </div>

      {tab === "members" ? (
        <MembersTab me={me} members={members} roles={roles.data ?? []} onChanged={reloadAll} />
      ) : (
        <RolesTab me={me} roles={roles} catalog={catalog.data ?? []} onChanged={reloadAll} />
      )}
    </>
  );
}

// --- Members --------------------------------------------------------------------------

function MembersTab({
  me,
  members,
  roles,
  onChanged,
}: {
  me: Me | null;
  members: ReturnType<typeof useAsync<TeamMember[]>>;
  roles: RoleDef[];
  onChanged: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const mine = new Set(me?.permissions ?? []);
  const assignable = roles.filter((r) => r.permissions.every((p) => mine.has(p)));

  async function update(member: TeamMember, patch: { roleId?: string; isActive?: boolean }) {
    setBusy(member.id);
    setError(null);
    try {
      await teamService.updateMember(member.id, patch);
      onChanged();
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {error && <ErrorState error={error} />}
      {members.error && <ErrorState error={members.error} onRetry={members.reload} />}
      <InvitationsCard roles={assignable} />
      {adding && (
        <AddMemberForm
          roles={assignable}
          onCancel={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            onChanged();
          }}
        />
      )}
      <Card>
        <CardHeader
          title="Members"
          action={
            !adding && (
              <Button size="sm" onClick={() => setAdding(true)}>
                <UserPlus className="h-4 w-4" /> Add member
              </Button>
            )
          }
        />
        {members.loading && !members.data ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[760px] text-left">
              <thead>
                <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">
                  <th className="px-5 py-3">Member</th>
                  <th className="px-3 py-3">Role</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3">Last sign-in</th>
                  <th className="px-5 py-3 text-right" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(members.data ?? []).map((m) => {
                  const self = m.id === me?.id;
                  const current = roles.find((r) => r.id === m.roleId);
                  // Someone with more access than you is not yours to change.
                  const locked = self || Boolean(current && !current.permissions.every((p) => mine.has(p)));
                  return (
                    <tr key={m.id} className={cn(!m.isActive && "opacity-60")}>
                      <td className="px-5 py-3">
                        <span className="block text-[13.5px] font-medium text-ink">
                          {m.name} {self && <Badge tone="brand">You</Badge>}
                        </span>
                        <span className="block text-2xs text-ink-3">{m.email}</span>
                      </td>
                      <td className="px-3 py-3">
                        {locked ? (
                          <span className="inline-flex items-center gap-1.5 text-[13px] text-ink-2">
                            <Lock className="h-3.5 w-3.5 text-ink-3" /> {m.roleName}
                          </span>
                        ) : (
                          <select
                            aria-label={`Role of ${m.name}`}
                            value={m.roleId}
                            disabled={busy === m.id}
                            onChange={(e) => void update(m, { roleId: e.target.value })}
                            className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px] text-ink focus:border-brand/50 focus:outline-none"
                          >
                            {assignable.map((r) => (
                              <option key={r.id} value={r.id}>
                                {r.name}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <Badge tone={m.isActive ? "ok" : "neutral"}>{m.isActive ? "Active" : "Inactive"}</Badge>
                      </td>
                      <td className="num px-3 py-3 text-[12.5px] text-ink-3">
                        {m.lastLoginAt ? relativeTime(m.lastLoginAt) : "Never"}
                      </td>
                      <td className="px-5 py-3 text-right">
                        {!locked && (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy === m.id}
                            onClick={() => void update(m, { isActive: !m.isActive })}
                          >
                            {busy === m.id && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                            {m.isActive ? "Deactivate" : "Activate"}
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function AddMemberForm({ roles, onCancel, onAdded }: { roles: RoleDef[]; onCancel: () => void; onAdded: () => void }) {
  const viewer = roles.find((r) => r.isSystem && r.name === "Viewer") ?? roles[0];
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [roleId, setRoleId] = useState(viewer?.id ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await teamService.addMember({ name, email, password, roleId });
      onAdded();
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Add a member" />
      <form onSubmit={submit} className="grid gap-4 p-5 sm:grid-cols-2">
        {error && (
          <div className="sm:col-span-2">
            <ErrorState error={error} />
          </div>
        )}
        <Field label="Full name">
          <input required value={name} onChange={(e) => setName(e.target.value)} className={inputClass} placeholder="Priya Sharma" />
        </Field>
        <Field label="Work email">
          <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} placeholder="priya@company.com" />
        </Field>
        <Field label="Temporary password" hint={`${MIN_PASSWORD}+ characters. Share it privately; they can use it to sign in.`}>
          <input
            required
            minLength={MIN_PASSWORD}
            type="text"
            autoComplete="off"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={cn(inputClass, "font-mono")}
          />
        </Field>
        <Field label="Role">
          <select value={roleId} onChange={(e) => setRoleId(e.target.value)} className={inputClass}>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="flex justify-end gap-2 sm:col-span-2">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />} Add member
          </Button>
        </div>
      </form>
    </Card>
  );
}

// --- Invitations (Phase 22) ----------------------------------------------------------------

function InvitationsCard({ roles }: { roles: RoleDef[] }) {
  const pending = useAsync(() => invitationService.pending(), []);
  const viewer = roles.find((r) => r.isSystem && r.name === "Viewer") ?? roles[0];
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const created = await invitationService.create(email, roleId || viewer?.id || "");
      setLink(created.link);
      setEmail("");
      pending.reload();
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    try {
      await invitationService.revoke(id);
      pending.reload();
    } catch (err) {
      setError(asApiError(err));
    }
  }

  return (
    <Card>
      <CardHeader title="Invite by link" eyebrow="Invitations" />
      <form onSubmit={invite} className="flex flex-wrap items-end gap-3 p-5">
        <label className="min-w-[220px] flex-1">
          <span className="mb-1.5 block text-[13px] font-medium text-ink">Work email</span>
          <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} placeholder="new.colleague@company.com" />
        </label>
        <label className="w-44">
          <span className="mb-1.5 block text-[13px] font-medium text-ink">Role</span>
          <select value={roleId || viewer?.id || ""} onChange={(e) => setRoleId(e.target.value)} className={inputClass}>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />} Create link
        </Button>
      </form>
      {error && <div className="px-5 pb-4"><ErrorState error={error} /></div>}
      {link && (
        <div className="mx-5 mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-brand/30 bg-brand-soft px-3 py-2 text-[12.5px]">
          <Link2 className="h-4 w-4 text-brand" />
          <code className="min-w-0 flex-1 truncate font-mono text-ink">{link}</code>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              void navigator.clipboard.writeText(link).then(() => setCopied(true));
            }}
          >
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} {copied ? "Copied" : "Copy"}
          </Button>
          <p className="w-full text-2xs text-ink-3">Share it privately. It works once and expires in 7 days; this is the only time it is shown.</p>
        </div>
      )}
      {(pending.data?.length ?? 0) > 0 && (
        <ul className="divide-y divide-line border-t border-line">
          {pending.data!.map((i) => (
            <li key={i.id} className="flex items-center gap-3 px-5 py-2.5 text-[13px]">
              <span className="min-w-0 flex-1 truncate text-ink">{i.email}</span>
              <Badge>{i.roleName}</Badge>
              <span className="text-2xs text-ink-3">expires {relativeTime(i.expiresAt)}</span>
              <Button size="sm" variant="ghost" onClick={() => void revoke(i.id)}>
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --- Roles ----------------------------------------------------------------------------

function RolesTab({
  me,
  roles,
  catalog,
  onChanged,
}: {
  me: Me | null;
  roles: ReturnType<typeof useAsync<RoleDef[]>>;
  catalog: PermissionInfo[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState<RoleDef | "new" | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const manage = can(me, "role:manage");
  const labels = useMemo(() => new Map(catalog.map((p) => [p.key, p.label])), [catalog]);
  // Chips in catalog order (documents, assistant, analysis, administration).
  const order = useMemo(() => new Map(catalog.map((p, i) => [p.key, i])), [catalog]);
  const sorted = (permissions: Permission[]) =>
    [...permissions].sort((a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99));

  async function remove(role: RoleDef) {
    if (!window.confirm(`Delete the role "${role.name}"?`)) return;
    setError(null);
    try {
      await teamService.deleteRole(role.id);
      onChanged();
    } catch (err) {
      setError(asApiError(err));
    }
  }

  return (
    <div className="space-y-4">
      {error && <ErrorState error={error} />}
      {roles.error && <ErrorState error={roles.error} onRetry={roles.reload} />}
      {editing && (
        <RoleForm
          role={editing === "new" ? null : editing}
          catalog={catalog}
          mine={new Set(me?.permissions ?? [])}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onChanged();
          }}
        />
      )}
      {manage && !editing && (
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" /> New role
          </Button>
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {(roles.data ?? []).map((role) => {
          const own = me?.role === role.name;
          return (
            <Card key={role.id} className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-[15px] font-semibold text-ink">
                    {role.name}
                    {role.isSystem ? (
                      <Badge>
                        <Lock className="h-3 w-3" /> Built-in
                      </Badge>
                    ) : (
                      <Badge tone="brand">Custom</Badge>
                    )}
                  </p>
                  {role.description && <p className="mt-1 text-[13px] text-ink-2">{role.description}</p>}
                </div>
                <span className="shrink-0 text-2xs text-ink-3">
                  {role.memberCount} {role.memberCount === 1 ? "member" : "members"}
                </span>
              </div>
              <ul className="mt-3 flex flex-wrap gap-1.5">
                {sorted(role.permissions).map((p) => (
                  <li key={p}>
                    <Badge tone="info">{labels.get(p) ?? p}</Badge>
                  </li>
                ))}
              </ul>
              {manage && !role.isSystem && (
                <div className="mt-4 flex gap-2 border-t border-line pt-3">
                  <Button size="sm" variant="secondary" disabled={own} title={own ? "You cannot edit your own role" : undefined} onClick={() => setEditing(role)}>
                    <Pencil className="h-3.5 w-3.5" /> Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={own || role.memberCount > 0}
                    title={role.memberCount > 0 ? "Give its members another role first" : undefined}
                    onClick={() => void remove(role)}
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Delete
                  </Button>
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function RoleForm({
  role,
  catalog,
  mine,
  onCancel,
  onSaved,
}: {
  role: RoleDef | null;
  catalog: PermissionInfo[];
  mine: Set<Permission>;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [selected, setSelected] = useState<Set<Permission>>(new Set(role?.permissions ?? ["document:read"]));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const groups = useMemo(() => {
    const byGroup = new Map<string, PermissionInfo[]>();
    for (const p of catalog) byGroup.set(p.group, [...(byGroup.get(p.group) ?? []), p]);
    return [...byGroup];
  }, [catalog]);

  function toggle(key: Permission) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const input: RoleInput = { name, description, permissions: [...selected] };
    try {
      if (role) await teamService.updateRole(role.id, input);
      else await teamService.createRole(input);
      onSaved();
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={role ? `Edit ${role.name}` : "New role"}
        action={
          <button onClick={onCancel} aria-label="Close" className="rounded-md p-1 text-ink-3 hover:bg-sunken hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        }
      />
      <form onSubmit={submit} className="space-y-5 p-5">
        {error && <ErrorState error={error} />}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name">
            <input required minLength={2} maxLength={80} value={name} onChange={(e) => setName(e.target.value)} className={inputClass} placeholder="e.g. Finance reviewer" />
          </Field>
          <Field label="Description">
            <input maxLength={300} value={description} onChange={(e) => setDescription(e.target.value)} className={inputClass} placeholder="What this role is for" />
          </Field>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {groups.map(([group, permissions]) => (
            <fieldset key={group} className="rounded-xl border border-line p-4">
              <legend className="px-1 text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">{group}</legend>
              <div className="space-y-2.5">
                {permissions.map((p) => {
                  const allowed = mine.has(p.key);
                  return (
                    <label key={p.key} className={cn("flex items-start gap-3", !allowed && "opacity-50")}>
                      <input
                        type="checkbox"
                        checked={selected.has(p.key)}
                        disabled={!allowed}
                        onChange={() => toggle(p.key)}
                        className="mt-0.5 h-4 w-4 accent-[rgb(var(--brand))]"
                      />
                      <span>
                        <span className="block text-[13px] font-medium text-ink">{p.label}</span>
                        <span className="block text-2xs text-ink-3">
                          {allowed ? p.description : "You can only grant access you have yourself."}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>
        <div className="flex items-center justify-between gap-3">
          <p className="flex items-center gap-1.5 text-2xs text-ink-3">
            <ShieldCheck className="h-3.5 w-3.5" /> Members get the new permissions immediately.
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="secondary" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || selected.size === 0}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} {role ? "Save role" : "Create role"}
            </Button>
          </div>
        </div>
      </form>
    </Card>
  );
}

// --- Small form helpers -----------------------------------------------------------------

const inputClass =
  "h-10 w-full rounded-lg border border-line bg-surface px-3 text-[13.5px] text-ink placeholder:text-ink-3 focus:border-brand/60 focus:outline-none focus:ring-4 focus:ring-brand/10";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-2xs text-ink-3">{hint}</span>}
    </label>
  );
}
