import { describe, expect, it } from "vitest";
import { validateContractFile, validateQuestion } from "@/utils/validation";

describe("validateContractFile", () => {
  const pdf = { name: "msa.pdf", type: "application/pdf", size: 1024 };
  it("accepts a PDF under the limit", () => expect(validateContractFile(pdf, 50).ok).toBe(true));
  it("rejects non-PDF extensions", () => expect(validateContractFile({ ...pdf, name: "msa.docx" }, 50).ok).toBe(false));
  it("rejects a spoofed MIME type", () => expect(validateContractFile({ ...pdf, type: "text/html" }, 50).ok).toBe(false));
  it("rejects empty files", () => expect(validateContractFile({ ...pdf, size: 0 }, 50).ok).toBe(false));
  it("rejects files over the limit", () => expect(validateContractFile({ ...pdf, size: 51 * 1024 * 1024 }, 50).ok).toBe(false));
});

describe("validateQuestion", () => {
  it("rejects very short input", () => expect(validateQuestion("hi").ok).toBe(false));
  it("rejects overly long input", () => expect(validateQuestion("x".repeat(2001)).ok).toBe(false));
  it("accepts a normal question", () => expect(validateQuestion("What is the liability cap?").ok).toBe(true));
});
