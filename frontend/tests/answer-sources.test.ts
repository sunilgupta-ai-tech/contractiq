import { describe, expect, it } from "vitest";
import type { Citation } from "@/types";
import { answerSources } from "@/utils/answer-sources";

const cite = (index: number, documentId: string, documentTitle: string, page: number, version = "v1"): Citation => ({
  id: `${documentId}-${index}`,
  index,
  documentId,
  documentTitle,
  version,
  page,
  section: "",
  clause: "",
  quote: "",
  score: 1,
});

describe("answer sources", () => {
  it("groups citations by document, in the order first cited", () => {
    const sources = answerSources([
      cite(2, "b", "Vendor B contract", 4),
      cite(1, "a", "Vendor A contract", 9),
      cite(3, "a", "Vendor A contract", 2),
    ]);
    expect(sources.map((s) => [s.title, s.indexes, s.pages])).toEqual([
      ["Vendor A contract", [1, 3], [2, 9]],
      ["Vendor B contract", [2], [4]],
    ]);
  });

  it("lists each version once and names untitled documents", () => {
    const [source] = answerSources([cite(1, "a", "", 1, "v1"), cite(2, "a", "", 1, "v2"), cite(3, "a", "", 1, "v2")]);
    expect([source!.title, source!.versions, source!.pages]).toEqual(["Untitled document", ["v1", "v2"], [1]]);
  });

  it("lists other documents with the same text once, never one already cited", () => {
    const a = { ...cite(1, "a", "Handbook", 2), alsoFoundIn: [{ documentId: "b", title: "Training" }, { documentId: "c", title: "IT Policy" }] };
    const b = { ...cite(2, "b", "Training", 5), alsoFoundIn: [{ documentId: "c", title: "IT Policy" }] };
    const [first, second] = answerSources([a, b]);
    expect(first!.alsoFoundIn.map((d) => d.title)).toEqual(["IT Policy"]);
    expect(second!.alsoFoundIn.map((d) => d.title)).toEqual(["IT Policy"]);
  });

  it("is empty when nothing was cited", () => {
    expect(answerSources([])).toEqual([]);
  });
});
