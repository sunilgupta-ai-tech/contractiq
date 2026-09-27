"use client";

import { useEffect, useMemo, useState } from "react";
import { Building2, Loader2, Lock, Search, UserRound, UsersRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { ApiError } from "@/lib/api-client";
import { accessService, type Directory, type DocumentAccessInfo } from "@/services/document-service";
import { cn } from "@/utils/cn";

type Visibility = DocumentAccessInfo["visibility"];

/** Who can see this document (Phase 20). The API enforces it everywhere —
 *  library, search, the Assistant and analysis; this card only shows and
 *  edits it. */
export function AccessCard({ documentId, onChanged }: { documentId: string; onChanged?: (v: Visibility) => void }) {
  const { data, error, reload } = useAsync(() => accessService.get(documentId), [documentId]);
  const [editing, setEditing] = useState(false);

  return (
    <Card>
      <CardHeader
        eyebrow="Access"
        title="Who can see this"
        action={
          data?.canManage && !editing ? (
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              Change
            </Button>
          ) : undefined
        }
      />
      <div className="p-4">
        {error && <ErrorState error={error} onRetry={reload} />}
        {!data ? (
          !error && <Skeleton className="h-16" />
        ) : editing ? (
          <AccessEditor
            documentId={documentId}
            current={data}
            onDone={(saved) => {
              setEditing(false);
              reload();
              if (saved) onChanged?.(saved.visibility);
            }}
          />
        ) : (
          <AccessSummary access={data} />
        )}
      </div>
    </Card>
  );
}

function AccessSummary({ access }: { access: DocumentAccessInfo }) {
  if (access.visibility === "ORGANIZATION") {
    return (
      <p className="flex items-start gap-2.5 text-[13px] text-ink-2">
        <Building2 className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" />
        Everyone in your organization who can view documents.
      </p>
    );
  }
  return (
    <div className="space-y-2.5 text-[13px]">
      <p className="flex items-start gap-2.5 text-ink-2">
        <Lock className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
        Restricted. {access.ownerName ? `${access.ownerName} (uploader)` : "The uploader"}, administrators
        {access.grants.length ? " and:" : " only."}
      </p>
      {access.grants.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 pl-6">
          {access.grants.map((g) => (
            <li key={`${g.kind}-${g.id}`}>
              <Badge tone={g.kind === "role" ? "brand" : "neutral"}>
                {g.kind === "role" ? <UsersRound className="h-3 w-3" /> : <UserRound className="h-3 w-3" />}
                {g.name}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AccessEditor({
  documentId,
  current,
  onDone,
}: {
  documentId: string;
  current: DocumentAccessInfo;
  onDone: (saved: DocumentAccessInfo | null) => void;
}) {
  const directory = useAsync<Directory>(() => accessService.directory(), []);
  const [visibility, setVisibility] = useState<Visibility>(current.visibility);
  const [users, setUsers] = useState<Set<string>>(new Set(current.grants.filter((g) => g.kind === "user").map((g) => g.id)));
  const [roles, setRoles] = useState<Set<string>>(new Set(current.grants.filter((g) => g.kind === "role").map((g) => g.id)));
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => setError(null), [visibility]);

  const people = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (directory.data?.users ?? []).filter(
      (u) => u.id !== current.ownerId && (!q || `${u.name} ${u.email}`.toLowerCase().includes(q)),
    );
  }, [directory.data, filter, current.ownerId]);

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setter(next);
  };

  async function save() {
    setSaving(true);
    setError(null);
    try {
      onDone(await accessService.set(documentId, visibility, [...users], [...roles]));
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("Could not save access.", "UNKNOWN", 0, null));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3">
      {error && <ErrorState error={error} />}
      <div className="grid grid-cols-2 gap-1 rounded-lg bg-sunken p-1">
        {(["ORGANIZATION", "RESTRICTED"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setVisibility(v)}
            className={cn(
              "rounded-md px-2 py-1.5 text-[12.5px] font-medium transition",
              visibility === v ? "bg-surface text-ink shadow-card" : "text-ink-2 hover:text-ink",
            )}
          >
            {v === "ORGANIZATION" ? "Everyone" : "Restricted"}
          </button>
        ))}
      </div>

      {visibility === "RESTRICTED" && (
        <>
          <p className="text-2xs text-ink-3">The uploader and administrators always keep access. Add people or whole roles:</p>
          {directory.error && <ErrorState error={directory.error} />}
          <fieldset>
            <legend className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">Roles</legend>
            <div className="flex flex-wrap gap-1.5">
              {(directory.data?.roles ?? []).map((r) => (
                <label key={r.id} className={cn("cursor-pointer rounded-md border px-2 py-1 text-[12.5px]", roles.has(r.id) ? "border-brand bg-brand-soft text-brand-ink" : "border-line text-ink-2")}>
                  <input type="checkbox" className="sr-only" checked={roles.has(r.id)} onChange={() => toggle(roles, setRoles, r.id)} />
                  {r.name}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">People</legend>
            <label className="mb-2 flex h-8 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 text-ink-3">
              <Search className="h-3.5 w-3.5" />
              <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a person…" className="h-full w-full bg-transparent text-[12.5px] text-ink focus:outline-none focus-visible:outline-none focus-visible:ring-0" />
            </label>
            <div className="max-h-44 space-y-1 overflow-y-auto scroll-thin">
              {people.map((u) => (
                <label key={u.id} className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 hover:bg-sunken">
                  <input type="checkbox" checked={users.has(u.id)} onChange={() => toggle(users, setUsers, u.id)} className="h-3.5 w-3.5 accent-[rgb(var(--brand))]" />
                  <span className="min-w-0 text-[12.5px]">
                    <span className="block truncate text-ink">{u.name}</span>
                    <span className="block truncate text-2xs text-ink-3">{u.email}</span>
                  </span>
                </label>
              ))}
              {directory.data && people.length === 0 && <p className="px-1.5 text-2xs text-ink-3">No one else to add.</p>}
            </div>
          </fieldset>
        </>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <Button size="sm" variant="secondary" onClick={() => onDone(null)}>
          Cancel
        </Button>
        <Button size="sm" disabled={saving} onClick={() => void save()}>
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save
        </Button>
      </div>
    </div>
  );
}
