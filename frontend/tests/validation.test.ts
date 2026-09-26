import { describe, expect, it } from "vitest";
import { validateQuestion, validateUploadFile } from "@/utils/validation";

describe("validateUploadFile", () => {
  const pdf = { name: "msa.pdf", type: "application/pdf", size: 1024 };
  it("accepts a PDF under the limit", () => expect(validateUploadFile(pdf, 50).ok).toBe(true));
  it.each(["scan.JPG", "receipt.jpeg", "photo.png", "policy.docx", "data.xlsx"])("accepts %s", (name) =>
    expect(validateUploadFile({ ...pdf, name, type: "" }, 50).ok).toBe(true),
  );
  it("rejects unsupported extensions", () => expect(validateUploadFile({ ...pdf, name: "tool.exe" }, 50).ok).toBe(false));
  it("explains legacy Office formats", () => {
    const result = validateUploadFile({ ...pdf, name: "old.doc" }, 50);
    expect(result.ok ? "" : result.reason).toContain(".docx");
  });
  it("rejects a spoofed MIME type", () => expect(validateUploadFile({ ...pdf, type: "text/html" }, 50).ok).toBe(false));
  it("rejects empty files", () => expect(validateUploadFile({ ...pdf, size: 0 }, 50).ok).toBe(false));
  it("rejects files over the limit", () => expect(validateUploadFile({ ...pdf, size: 51 * 1024 * 1024 }, 50).ok).toBe(false));
});

describe("validateQuestion", () => {
  it("rejects very short input", () => expect(validateQuestion("hi").ok).toBe(false));
  it("rejects overly long input", () => expect(validateQuestion("x".repeat(2001)).ok).toBe(false));
  it("accepts a normal question", () => expect(validateQuestion("What is the liability cap?").ok).toBe(true));
});
