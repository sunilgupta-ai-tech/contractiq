import { describe, expect, it } from "vitest";
import { daysUntil, formatBytes, isProcessing, statusLabel } from "@/utils/format";

describe("format utils", () => {
  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(3_420_112)).toBe("3.3 MB");
  });
  it("labels statuses", () => {
    expect(statusLabel("OCR_PROCESSING")).toBe("OCR");
    expect(isProcessing("EMBEDDING")).toBe(true);
    expect(isProcessing("COMPLETED")).toBe(false);
  });
  it("counts days until a date", () => {
    expect(daysUntil("2026-10-05T00:00:00Z", new Date("2026-09-25T00:00:00Z"))).toBe(10);
  });
});
