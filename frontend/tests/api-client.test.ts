import { describe, expect, it } from "vitest";
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
