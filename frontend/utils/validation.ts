/**
 * Client-side upload validation — a UX convenience only. The backend
 * re-validates type, size and the file's content (magic bytes, ZIP
 * structure, macros); never trust the browser.
 */

import type { FileType } from "@/types";

export type FileValidation = { ok: true } | { ok: false; reason: string };

/** Phase 16: what the upload accepts (mirrors backend formats.py). */
export const UPLOAD_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx"] as const;
export const UPLOAD_ACCEPT = [
  ...UPLOAD_EXTENSIONS,
  "application/pdf",
  "image/jpeg",
  "image/png",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
].join(",");

/** What a new version of a document may be: the same kind of file. */
export const ACCEPT_BY_FILE_TYPE: Record<FileType, string> = {
  PDF: ".pdf,application/pdf",
  IMAGE: ".jpg,.jpeg,.png,image/jpeg,image/png",
  WORD: ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  EXCEL: ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

const LEGACY: Record<string, string> = {
  ".doc": "Old Word files (.doc) aren't supported. Save it as .docx and upload again.",
  ".xls": "Old Excel files (.xls) aren't supported. Save it as .xlsx and upload again.",
  ".docm": "Macro-enabled Word files aren't accepted. Save it as a regular .docx.",
  ".xlsm": "Macro-enabled Excel files aren't accepted. Save it as a regular .xlsx.",
};

// Browsers report these for files that are clearly not documents.
const REJECTED_TYPES = ["text/html", "application/javascript", "text/javascript"];

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

export function validateUploadFile(file: { name: string; type: string; size: number }, maxMb: number): FileValidation {
  const ext = extension(file.name);
  if (LEGACY[ext]) return { ok: false, reason: LEGACY[ext] };
  if (!(UPLOAD_EXTENSIONS as readonly string[]).includes(ext) || REJECTED_TYPES.includes(file.type)) {
    return { ok: false, reason: "Upload a PDF, JPG, PNG, Word (.docx) or Excel (.xlsx) file." };
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
