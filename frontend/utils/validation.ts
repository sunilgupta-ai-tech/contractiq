/**
 * Client-side upload validation — a UX convenience only. The backend
 * re-validates type, size and PDF magic bytes; never trust the browser.
 */

export type FileValidation = { ok: true } | { ok: false; reason: string };

const PDF_MIME = "application/pdf";

export function validateContractFile(file: { name: string; type: string; size: number }, maxMb: number): FileValidation {
  if (!file.name.toLowerCase().endsWith(".pdf") || (file.type && file.type !== PDF_MIME)) {
    return { ok: false, reason: "Only PDF contracts are supported." };
  }
  if (file.size === 0) return { ok: false, reason: "The file is empty." };
  if (file.size > maxMb * 1024 * 1024) {
    return { ok: false, reason: `Files must be ${maxMb} MB or smaller.` };
  }
  return { ok: true };
}

export const MAX_QUERY_LENGTH = 2000;

export function validateQuestion(question: string): FileValidation {
  const q = question.trim();
  if (q.length < 3) return { ok: false, reason: "Ask a complete question." };
  if (q.length > MAX_QUERY_LENGTH) return { ok: false, reason: `Keep questions under ${MAX_QUERY_LENGTH} characters.` };
  return { ok: true };
}
