import { afterEach, describe, expect, it, vi } from "vitest";
import { tokensOf } from "@/services/admin-service";

describe("usage", () => {
  it("counts input, output and embedding tokens", () => {
    expect(tokensOf({ period: "2026-09", queries: 2, prompt_tokens: 100, completion_tokens: 20, embedding_tokens: 5, model_calls: 2 })).toBe(125);
  });
});

describe("invitations", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.doUnmock("@/lib/api-client");
  });

  it("builds the share link from the one-time token", async () => {
    vi.resetModules();
    vi.stubGlobal("window", { location: { origin: "https://app.docunexa.ai" } });
    const apiRequest = vi.fn().mockResolvedValue({ id: "i1", email: "a@b.c", role_name: "Viewer", expires_at: "2026-10-05T00:00:00Z", token: "tok" });
    vi.doMock("@/lib/api-client", () => ({ apiRequest }));
    const { invitationService } = await import("@/services/team-service");
    const { link, invitation } = await invitationService.create("a@b.c", "r1");
    expect(link).toBe("https://app.docunexa.ai/invite/tok");
    expect(invitation.roleName).toBe("Viewer");
    expect(apiRequest.mock.calls[0]![1]).toMatchObject({ method: "POST", body: { email: "a@b.c", role_id: "r1" } });
  });
});
