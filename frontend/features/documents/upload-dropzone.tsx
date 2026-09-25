"use client";

import { useRef, useState } from "react";
import { FileUp, Lock, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { config } from "@/lib/config";
import { documentService } from "@/services/document-service";
import type { ContractDocument } from "@/types";
import { cn } from "@/utils/cn";
import { validateContractFile } from "@/utils/validation";

interface Upload {
  name: string;
  pct: number;
  error?: string;
}

export function UploadDropzone({ onUploaded }: { onUploaded: (doc: ContractDocument) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<Upload[]>([]);

  const update = (name: string, patch: Partial<Upload>) =>
    setUploads((list) => list.map((u) => (u.name === name ? { ...u, ...patch } : u)));

  async function handleFiles(files: FileList | null) {
    for (const file of Array.from(files ?? [])) {
      const check = validateContractFile(file, config.maxUploadMb);
      setUploads((list) => [{ name: file.name, pct: 0, error: check.ok ? undefined : check.reason }, ...list].slice(0, 4));
      if (!check.ok) continue;
      try {
        const doc = await documentService.upload(file, (pct) => update(file.name, { pct }));
        onUploaded(doc);
        setTimeout(() => setUploads((list) => list.filter((u) => u.name !== file.name)), 1200);
      } catch (err) {
        update(file.name, { error: err instanceof Error ? err.message : "Upload failed" });
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
        <p className="font-medium text-ink">Drop contract PDFs here</p>
        <p className="mt-0.5 text-[13px] text-ink-2">
          Digital or scanned · up to {config.maxUploadMb} MB · processed in the background with OCR, clause detection and indexing.
        </p>
        <p className="mt-2 inline-flex items-center gap-1.5 text-2xs text-ink-3">
          <Lock className="h-3 w-3" /> Encrypted at rest and visible only to Acme Legal.
        </p>
      </div>
      <input ref={input} type="file" accept="application/pdf,.pdf" multiple hidden onChange={(e) => void handleFiles(e.target.files)} />
      <Button onClick={() => input.current?.click()}>
        <FileUp className="h-4 w-4" /> Choose files
      </Button>

      {uploads.length > 0 && (
        <ul className="w-full space-y-2 sm:absolute sm:bottom-3 sm:left-[88px] sm:right-5 sm:w-auto" aria-live="polite">
          {uploads.map((u) => (
            <li key={u.name} className="flex items-center gap-3 text-2xs">
              <span className="max-w-[40%] truncate font-medium text-ink">{u.name}</span>
              {u.error ? (
                <span className="text-danger">{u.error}</span>
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
