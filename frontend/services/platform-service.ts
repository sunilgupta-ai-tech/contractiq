import { platformRequest, setPlatformSession } from "@/lib/platform-client";
import type { FileType } from "@/types";

// Shapes follow backend app/schemas/platform.py (snake_case kept: this
// console is small and reads them directly).

export type OrgStatus = "ACTIVE" | "SUSPENDED";
export type Plan = "FREE" | "STARTER" | "BUSINESS" | "ENTERPRISE";
export type PlatformRole = "SUPER_ADMIN" | "SUPPORT";

export const PLANS: Plan[] = ["FREE", "STARTER", "BUSINESS", "ENTERPRISE"];

export interface Limits {
  max_users: number | null;
  max_documents: number | null;
  max_storage_mb: number | null;
}

export interface OrgSummary {
  id: string;
  name: string;
  slug: string;
  status: OrgStatus;
  plan: Plan;
  limits: Limits;
  usage: { active_users: number; total_users: number; documents: number; storage_bytes: number };
  last_active_at: string | null;
  created_at: string;
}

export interface OrgMember {
  id: string;
  email: string;
  full_name: string;
  role_name: string;
  is_active: boolean;
  last_login_at: string | null;
}

export interface OrgDetail extends OrgSummary {
  suspended_reason: string | null;
  suspended_at: string | null;
  documents_by_type: Record<FileType, number>;
  failed_documents: number;
  members: OrgMember[];
}

export interface Overview {
  organizations: number;
  active_organizations: number;
  suspended_organizations: number;
  users: number;
  active_users: number;
  documents: number;
  storage_bytes: number;
  failed_documents_24h: number;
  organizations_by_plan: Record<Plan, number>;
  new_organizations_30d: number;
}

export interface PlatformAdmin {
  id: string;
  email: string;
  full_name: string;
  role: PlatformRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  organization_id: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface OrgUpdate {
  status?: OrgStatus;
  suspended_reason?: string;
  plan?: Plan;
  max_users?: number;
  max_documents?: number;
  max_storage_mb?: number;
  unlimited?: (keyof Limits)[];
}

export const platformService = {
  async login(email: string, password: string): Promise<void> {
    const tokens = await platformRequest<{ access_token: string; refresh_token: string }>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setPlatformSession(tokens.access_token, tokens.refresh_token);
  },
  me: () => platformRequest<PlatformAdmin>("/me"),
  overview: () => platformRequest<Overview>("/overview"),
  plans: () => platformRequest<{ plan: Plan; limits: Limits }[]>("/plans"),
  organizations(params: { q?: string; status?: OrgStatus | ""; plan?: Plan | ""; offset: number; limit: number }) {
    const query = new URLSearchParams();
    if (params.q?.trim()) query.set("q", params.q.trim());
    if (params.status) query.set("status", params.status);
    if (params.plan) query.set("plan", params.plan);
    query.set("offset", String(params.offset));
    query.set("limit", String(params.limit));
    return platformRequest<Page<OrgSummary>>(`/organizations?${query}`);
  },
  organization: (id: string) => platformRequest<OrgDetail>(`/organizations/${encodeURIComponent(id)}`),
  updateOrganization: (id: string, body: OrgUpdate) =>
    platformRequest<OrgDetail>(`/organizations/${encodeURIComponent(id)}`, { method: "PATCH", body }),
  setMemberActive: (orgId: string, userId: string, isActive: boolean) =>
    platformRequest<OrgDetail>(
      `/organizations/${encodeURIComponent(orgId)}/members/${encodeURIComponent(userId)}`,
      { method: "PATCH", body: { is_active: isActive } },
    ),
  admins: () => platformRequest<PlatformAdmin[]>("/admins"),
  createAdmin: (body: { email: string; full_name: string; password: string; role: PlatformRole }) =>
    platformRequest<PlatformAdmin>("/admins", { method: "POST", body }),
  updateAdmin: (id: string, body: { role?: PlatformRole; is_active?: boolean }) =>
    platformRequest<PlatformAdmin>(`/admins/${encodeURIComponent(id)}`, { method: "PATCH", body }),
  audit: (params: { organizationId?: string; offset: number; limit: number }) => {
    const query = new URLSearchParams({ offset: String(params.offset), limit: String(params.limit) });
    if (params.organizationId) query.set("organization_id", params.organizationId);
    return platformRequest<Page<AuditEntry>>(`/audit?${query}`);
  },
};
