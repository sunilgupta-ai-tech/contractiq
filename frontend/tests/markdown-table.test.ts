import { describe, expect, it } from "vitest";
import { initials } from "@/lib/session";
import { parseMarkdownTable } from "@/utils/markdown-table";

describe("parseMarkdownTable", () => {
  it("parses a table collapsed onto one line (as clause quotes arrive)", () => {
    const text = "| Milestone | Due | Fee | | --- | --- | --- | | Kick-off | Week 1 | 10,000 | | Go-live | Week 12 | 40,000 |";
    expect(parseMarkdownTable(text)).toEqual([
      ["Milestone", "Due", "Fee"],
      ["Kick-off", "Week 1", "10,000"],
      ["Go-live", "Week 12", "40,000"],
    ]);
  });

  it("parses a multi-line table and unescapes pipes in cells", () => {
    const text = "| A | B |\n| --- | --- |\n| x \\| y | 2 |";
    expect(parseMarkdownTable(text)).toEqual([["A", "B"], ["x | y", "2"]]);
  });

  it("leaves ordinary clause text alone", () => {
    expect(parseMarkdownTable("Either party may terminate on 30 days' notice.")).toBeNull();
    expect(parseMarkdownTable("| not | a table without a separator |")).toBeNull();
  });
});

describe("initials", () => {
  it("uses first and last names", () => {
    expect(initials("Sunil Kumar Gupta")).toBe("SG");
    expect(initials("acme")).toBe("A");
    expect(initials("  ")).toBe("?");
  });
});
