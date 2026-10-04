"use client";

import { useEffect, useState } from "react";
import { Download, FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { ApiError } from "@/lib/api-client";
import { config } from "@/lib/config";
import { documentService } from "@/services/document-service";
import type { ContractDocument } from "@/types";

/** Browsers render PDFs and images themselves; Word and Excel need a download. */
const PREVIEWABLE = new Set(["PDF", "IMAGE"]);

/** The latest version's original file, shown in the page. `page` opens a PDF at that page. */
export function FileViewer({ doc, page }: { doc: ContractDocument; page?: number }) {
  const version = doc.versions.at(-1);
  const previewable = PREVIEWABLE.has(doc.fileType) && !config.useDemoData && !!version;
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!previewable || !version) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    setUrl(null);
    setError(null);
    documentService
      .file(doc.id, version.id)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err : new ApiError("The file could not be loaded.", "UNKNOWN", 0, null));
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [doc.id, version, previewable, attempt]);

  async function download() {
    if (!version) return;
    setDownloading(true);
    try {
      await documentService.download(doc.id, version.id, doc.fileName);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("The file could not be downloaded.", "UNKNOWN", 0, null));
    } finally {
      setDownloading(false);
    }
  }

  // The page header already has a Download button; the viewer adds one only
  // where the file can't be shown.
  const toolbar = (
    <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
      <span className="min-w-0 truncate text-[13px] text-ink-2">
        {doc.fileName} <span className="text-ink-3">· {doc.version}</span>
      </span>
    </div>
  );

  let body;
  if (error) {
    body = <div className="p-5"><ErrorState error={error} onRetry={() => setAttempt((n) => n + 1)} /></div>;
  } else if (!previewable) {
    body = (
      <div className="flex flex-col items-center gap-2 px-6 py-16 text-center">
        <FileText className="h-8 w-8 text-ink-3" />
        <p className="text-[13.5px] font-medium text-ink">
          {config.useDemoData ? "Previews need the live API." : "This file type can't be previewed in the browser."}
        </p>
        {!config.useDemoData && version && (
          <>
            <p className="text-[12.5px] text-ink-3">Download it to open it in Word or Excel.</p>
            <Button size="sm" variant="secondary" className="mt-2" disabled={downloading} onClick={() => void download()}>
              {downloading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />} Download
            </Button>
          </>
        )}
      </div>
    );
  } else if (!url) {
    body = <Skeleton className="m-4 h-[70vh] rounded-lg" />;
  } else if (doc.fileType === "IMAGE") {
    body = (
      <div className="flex justify-center bg-sunken p-4">
        {/* eslint-disable-next-line @next/next/no-img-element -- a local blob URL, not an optimisable asset */}
        <img src={url} alt={doc.title} className="max-h-[75vh] max-w-full rounded-sm object-contain shadow-paper" />
      </div>
    );
  } else {
    // Keyed by page: a new #page fragment reloads the (local) blob at that page.
    body = (
      <iframe
        key={page ?? 0}
        src={page ? `${url}#page=${page}` : url}
        title={doc.title}
        className="block h-[78vh] w-full bg-sunken"
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      {toolbar}
      {body}
    </div>
  );
}
