import { describe, expect, it } from "vitest";
import { wordDiff } from "@/utils/diff";

describe("wordDiff", () => {
  it("marks changed words on each side", () => {
    const { left, right } = wordDiff("not less than thirty (30) days", "not less than sixty (60) days");
    expect(left.filter((s) => s.kind === "del").map((s) => s.text.trim()).join(" ")).toBe("thirty (30)");
    expect(right.filter((s) => s.kind === "add").map((s) => s.text.trim()).join(" ")).toBe("sixty (60)");
  });

  it("reconstructs both inputs exactly", () => {
    const a = "pay within thirty (30) days of receipt.";
    const b = "pay within forty-five (45) days of receipt.";
    const { left, right } = wordDiff(a, b);
    expect(left.map((s) => s.text).join("")).toBe(a);
    expect(right.map((s) => s.text).join("")).toBe(b);
  });

  it("returns only 'same' segments for identical text", () => {
    const { left } = wordDiff("governed by English law", "governed by English law");
    expect(left.every((s) => s.kind === "same")).toBe(true);
  });
});
