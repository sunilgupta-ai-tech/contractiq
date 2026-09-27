import { apiRequest } from "@/lib/api-client";
import type { ApiPage } from "@/lib/adapters";
import type { Permission, PermissionInfo, RoleDef, TeamMember } from "@/types";

// Wire shapes (backend app/schemas/user.py).
interface ApiUser {
  id: string;
  email: string;
  full_name: string;
  role_id: string;
  role_name: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

interface ApiRole {
  id: string;
  name: string;
  description: string;
  permissions: Permission[];
  is_system: boolean;
  member_count: number;
}

export function toMember(u: ApiUser): TeamMember {
  return {
    id: u.id,
    email: u.email,
    name: u.full_name,
    roleId: u.role_id,
    roleName: u.role_name,
    isActive: u.is_active,
    lastLoginAt: u.last_login_at,
    createdAt: u.created_at,
  };
}

export function toRole(r: ApiRole): RoleDef {
  return {
    id: r.id,
    name: r.name,
    description: r.description,
    permissions: r.permissions,
    isSystem: r.is_system,
    memberCount: r.member_count,
  };
}

export interface NewMember {
  name: string;
  email: string;
  password: string;
  roleId: string;
}

export interface RoleInput {
  name: string;
  description: string;
  permissions: Permission[];
}

/** Users and roles of the signed-in user's organization (Phase 17). */
export const teamService = {
  async members(): Promise<TeamMember[]> {
    const page = await apiRequest<ApiPage<ApiUser>>("/users?limit=200");
    return page.items.map(toMember);
  },

  async addMember(input: NewMember): Promise<TeamMember> {
    const user = await apiRequest<ApiUser>("/users", {
      method: "POST",
      body: { full_name: input.name, email: input.email, password: input.password, role_id: input.roleId },
    });
    return toMember(user);
  },

  async updateMember(id: string, patch: { roleId?: string; isActive?: boolean }): Promise<TeamMember> {
    const body: Record<string, unknown> = {};
    if (patch.roleId !== undefined) body.role_id = patch.roleId;
    if (patch.isActive !== undefined) body.is_active = patch.isActive;
    const user = await apiRequest<ApiUser>(`/users/${encodeURIComponent(id)}`, { method: "PATCH", body });
    return toMember(user);
  },

  async roles(): Promise<RoleDef[]> {
    return (await apiRequest<ApiRole[]>("/roles")).map(toRole);
  },

  async permissions(): Promise<PermissionInfo[]> {
    return apiRequest<PermissionInfo[]>("/permissions");
  },

  async createRole(input: RoleInput): Promise<RoleDef> {
    return toRole(await apiRequest<ApiRole>("/roles", { method: "POST", body: input }));
  },

  async updateRole(id: string, input: RoleInput): Promise<RoleDef> {
    return toRole(
      await apiRequest<ApiRole>(`/roles/${encodeURIComponent(id)}`, { method: "PATCH", body: input }),
    );
  },

  async deleteRole(id: string): Promise<void> {
    await apiRequest<null>(`/roles/${encodeURIComponent(id)}`, { method: "DELETE" });
  },
};

// --- Invitations (Phase 22) -------------------------------------------------------------

export interface Invitation {
  id: string;
  email: string;
  roleName: string;
  expiresAt: string;
}

interface ApiInvitation {
  id: string;
  email: string;
  role_name: string;
  expires_at: string;
  token?: string;
}

const toInvitation = (i: ApiInvitation): Invitation => ({ id: i.id, email: i.email, roleName: i.role_name, expiresAt: i.expires_at });

export const invitationService = {
  /** Returns the invitation and the link to share (the token is shown only once). */
  async create(email: string, roleId: string): Promise<{ invitation: Invitation; link: string }> {
    const created = await apiRequest<ApiInvitation>("/invitations", { method: "POST", body: { email, role_id: roleId } });
    const origin = typeof window === "undefined" ? "" : window.location.origin;
    return { invitation: toInvitation(created), link: `${origin}/invite/${created.token}` };
  },
  async pending(): Promise<Invitation[]> {
    return (await apiRequest<ApiInvitation[]>("/invitations")).map(toInvitation);
  },
  async revoke(id: string): Promise<void> {
    await apiRequest<null>(`/invitations/${encodeURIComponent(id)}`, { method: "DELETE" });
  },
  async preview(token: string): Promise<{ email: string; organizationName: string; roleName: string }> {
    const p = await apiRequest<{ email: string; organization_name: string; role_name: string }>(
      `/auth/invitations/${encodeURIComponent(token)}`,
    );
    return { email: p.email, organizationName: p.organization_name, roleName: p.role_name };
  },
  async accept(token: string, fullName: string, password: string): Promise<{ access_token: string; refresh_token: string }> {
    return apiRequest(`/auth/invitations/${encodeURIComponent(token)}/accept`, {
      method: "POST",
      body: { full_name: fullName, password },
    });
  },
};
