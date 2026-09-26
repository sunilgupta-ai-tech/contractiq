import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, parseEnvelope } from "@/lib/api-client";

describe("parseEnvelope", () => {
  it("unwraps data on success", () => {
    expect(parseEnvelope(200, { success: true, data: { ok: 1 }, request_id: "r" })).toEqual({ ok: 1 });
  });

  it("throws ApiError with code and request id on failure", () => {
    try {
      parseEnvelope(501, { success: false, error: { code: "NOT_IMPLEMENTED", message: "Later" }, request_id: "req-9" });
      throw new Error("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).code).toBe("NOT_IMPLEMENTED");
      expect((e as ApiError).requestId).toBe("req-9");
      expect((e as ApiError).status).toBe(501);
    }
  });

  it("returns readiness data even when success=false if requested", () => {
    const report = { status: "not_ready", dependencies: [] };
    expect(parseEnvelope(503, { success: false, data: report }, true)).toEqual(report);
  });

  it("rejects non-envelope payloads", () => {
    expect(() => parseEnvelope(502, "<html>Bad gateway</html>")).toThrow(ApiError);
  });
});

describe("session renewal", () => {
  const ok = (data: unknown) => ({ status: 200, ok: true, json: async () => ({ success: true, data }) });
  const expired = { status: 401, ok: false, json: async () => ({ success: false, error: { code: "UNAUTHORIZED", message: "Expired" } }) };

  function browser() {
    vi.resetModules(); // load config/api-client fresh with the env stubbed below
    const store = new Map<string, string>();
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
      location: { pathname: "/assistant", assign: vi.fn() },
    });
    return window as unknown as { location: { assign: ReturnType<typeof vi.fn> } };
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("renews an expired session once and retries the request", async () => {
    browser();
    vi.stubEnv("NEXT_PUBLIC_USE_DEMO_DATA", "false");
    const { apiRequest, setSession, getAccessToken } = await import("@/lib/api-client");
    setSession("old-access", "refresh-1");
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      const auth = (init.headers as Record<string, string>)?.Authorization;
      calls.push(`${url.split("/api/v1")[1]} ${auth ?? ""}`.trim());
      if (url.endsWith("/auth/refresh")) return ok({ access_token: "new-access", refresh_token: "refresh-2" });
      return auth === "Bearer new-access" ? ok({ answer: 42 }) : expired;
    }));
    await expect(apiRequest("/query", { method: "POST", body: { q: 1 } })).resolves.toEqual({ answer: 42 });
    expect(calls).toEqual(["/query Bearer old-access", "/auth/refresh", "/query Bearer new-access"]);
    expect(getAccessToken()).toBe("new-access");
    vi.unstubAllEnvs();
  });

  it("shares one renewal between parallel requests (refresh tokens are single-use)", async () => {
    browser();
    vi.stubEnv("NEXT_PUBLIC_USE_DEMO_DATA", "false");
    const { apiRequest, setSession } = await import("@/lib/api-client");
    setSession("old", "refresh-1");
    let refreshes = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith("/auth/refresh")) {
        refreshes++;
        return ok({ access_token: "new", refresh_token: "r2" });
      }
      return (init.headers as Record<string, string>).Authorization === "Bearer new" ? ok(1) : expired;
    }));
    await Promise.all([apiRequest("/a"), apiRequest("/b"), apiRequest("/c")]);
    expect(refreshes).toBe(1);
    vi.unstubAllEnvs();
  });

  it("sends the user to sign in when renewal fails", async () => {
    const win = browser();
    vi.stubEnv("NEXT_PUBLIC_USE_DEMO_DATA", "false");
    const { apiRequest, setSession, hasSession } = await import("@/lib/api-client");
    setSession("old", "revoked");
    vi.stubGlobal("fetch", vi.fn(async () => expired));
    await expect(apiRequest("/query")).rejects.toThrow("Expired");
    expect(win.location.assign).toHaveBeenCalledWith("/login");
    expect(hasSession()).toBe(false);
    vi.unstubAllEnvs();
  });
});
