import { describe, expect, it } from "vitest";
import { can, type Me } from "@/lib/session";
import { toMember, toRole } from "@/services/team-service";

const me: Me = { id: "u1", name: "A", role: "Auditor", organization: "Acme", members: 2, permissions: ["document:read"] };

describe("permissions in the UI", () => {
  it("offers only what the role allows", () => {
    expect(can(me, "document:read")).toBe(true);
    expect(can(me, "document:upload")).toBe(false);
  });
  it("offers nothing while the profile is loading", () => expect(can(null, "document:read")).toBe(false));
});

describe("team adapters", () => {
  it("maps users and roles", () => {
    expect(
      toMember({
        id: "u2", email: "b@x.test", full_name: "B", role_id: "r1", role_name: "Viewer",
        is_active: false, last_login_at: null, created_at: "2026-09-27T00:00:00Z",
      }),
    ).toMatchObject({ name: "B", roleName: "Viewer", isActive: false });
    expect(
      toRole({ id: "r1", name: "Viewer", description: "", permissions: ["query:run"], is_system: true, member_count: 3 }),
    ).toEqual({ id: "r1", name: "Viewer", description: "", permissions: ["query:run"], isSystem: true, memberCount: 3 });
  });
});
