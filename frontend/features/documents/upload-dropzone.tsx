"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { FileUp, Lock, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { config } from "@/lib/config";
import { ApiError } from "@/lib/api-client";
import { documentService } from "@/services/document-service";
import type { ContractDocument } from "@/types";
import { cn } from "@/utils/cn";
import { UPLOAD_ACCEPT, validateUploadFile } from "@/utils/validation";

interface Upload {
  name: string;
  pct: number;
  error?: string;
  /** Set when the file already exists in the organization (409 DUPLICATE_DOCUMENT). */
  existing?: { id: string; title: string };
}

/** The organization's own copy of a duplicate upload, if that is the error. */
function existingCopy(err: unknown): Upload["existing"] {
  if (!(err instanceof ApiError) || err.code !== "DUPLICATE_DOCUMENT") return undefined;
  const details = (err.details ?? {}) as { document_id?: string; document_title?: string };
  return details.document_id ? { id: details.document_id, title: details.document_title ?? "" } : undefined;
}

export function UploadDropzone({ onUploaded }: { onUploaded: (doc: ContractDocument) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<Upload[]>([]);
  // Phase 20: keep new uploads private to the uploader until shared.
  const [onlyMe, setOnlyMe] = useState(false);

  const update = (name: string, patch: Partial<Upload>) =>
    setUploads((list) => list.map((u) => (u.name === name ? { ...u, ...patch } : u)));

  async function handleFiles(files: FileList | null) {
    for (const file of Array.from(files ?? [])) {
      const check = validateUploadFile(file, config.maxUploadMb);
      setUploads((list) => [{ name: file.name, pct: 0, error: check.ok ? undefined : check.reason }, ...list].slice(0, 4));
      if (!check.ok) continue;
      try {
        const doc = await documentService.upload(file, (pct) => update(file.name, { pct }), { private: onlyMe });
        onUploaded(doc);
        setTimeout(() => setUploads((list) => list.filter((u) => u.name !== file.name)), 1200);
      } catch (err) {
        update(file.name, { error: err instanceof Error ? err.message : "Upload failed", existing: existingCopy(err) });
      }
    }
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        void handleFiles(e.dataTransfer.files);
      }}
      className={cn(
        "card relative flex flex-col gap-5 border-dashed p-5 transition-colors sm:flex-row sm:items-center",
        dragging ? "border-brand bg-brand-soft/60" : "border-line-strong",
      )}
    >
      <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
        <UploadCloud className="h-6 w-6" />
      </span>
      <div className="flex-1">
        <p className="font-medium text-ink">Drop documents here</p>
        <p className="mt-0.5 text-[13px] text-ink-2">
          PDF (digital or scanned), JPG, PNG, Word (.docx) or Excel (.xlsx) · up to {config.maxUploadMb} MB · handwriting and registers are read too.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-ink-3">
          <span className="inline-flex items-center gap-1.5">
            <Lock className="h-3 w-3" /> Stored per organization and visible only to your organization.
          </span>
          {!config.useDemoData && (
            <label className="inline-flex cursor-pointer items-center gap-1.5 font-medium text-ink-2">
              <input type="checkbox" checked={onlyMe} onChange={(e) => setOnlyMe(e.target.checked)} className="h-3.5 w-3.5 accent-[rgb(var(--brand))]" />
              Only me — share it later
            </label>
          )}
        </div>
      </div>
      <input ref={input} type="file" accept={UPLOAD_ACCEPT} multiple hidden onChange={(e) => void handleFiles(e.target.files)} />
      <Button onClick={() => input.current?.click()}>
        <FileUp className="h-4 w-4" /> Choose files
      </Button>

      {uploads.length > 0 && (
        <ul className="w-full space-y-2 sm:absolute sm:bottom-3 sm:left-[88px] sm:right-5 sm:w-auto" aria-live="polite">
          {uploads.map((u) => (
            <li key={u.name} className="flex items-center gap-3 text-2xs">
              <span className="max-w-[40%] truncate font-medium text-ink">{u.name}</span>
              {u.error ? (
                <span className={u.existing ? "text-warn" : "text-danger"}>
                  {u.error}
                  {u.existing && (
                    <Link href={`/documents/${u.existing.id}`} className="ml-1.5 font-medium text-brand underline-offset-2 hover:underline">
                      Open {u.existing.title ? `“${u.existing.title}”` : "it"}
                    </Link>
                  )}
                </span>
              ) : (
                <span className="h-1 flex-1 overflow-hidden rounded-full bg-line">
                  <span className="block h-full bg-brand transition-[width]" style={{ width: `${u.pct}%` }} />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
