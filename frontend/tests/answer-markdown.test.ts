import { describe, expect, it } from "vitest";
import { parseAnswer } from "@/utils/answer-markdown";

describe("parseAnswer", () => {
  it("splits a structured answer into headings, paragraphs and lists", () => {
    const text = [
      "The proposal is for a video streaming web application [1].",
      "",
      "### Cost",
      "- Total: **$850** (approx. ₹80,000) [4]",
      "- Advance: **$425** [4]",
      "",
      "### **Timeline**",
      "1. Design [2]",
      "2. Build [3]",
      "Delivery follows testing [3].",
    ].join("\n");
    expect(parseAnswer(text)).toEqual([
      { kind: "paragraph", text: "The proposal is for a video streaming web application [1]." },
      { kind: "heading", text: "Cost" },
      { kind: "list", ordered: false, items: ["Total: **$850** (approx. ₹80,000) [4]", "Advance: **$425** [4]"] },
      { kind: "heading", text: "Timeline" },
      { kind: "list", ordered: true, items: ["Design [2]", "Build [3]"] },
      { kind: "paragraph", text: "Delivery follows testing [3]." },
    ]);
  });

  it("keeps plain one-paragraph answers as they were", () => {
    expect(parseAnswer("Notice is 60 days [1].")).toEqual([{ kind: "paragraph", text: "Notice is 60 days [1]." }]);
    expect(parseAnswer("Line one\nline two")).toEqual([{ kind: "paragraph", text: "Line one line two" }]);
  });
});
