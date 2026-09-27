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
