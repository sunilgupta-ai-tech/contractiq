"use client";

import { useEffect, useMemo, useState } from "react";
import { FileSearch, Filter } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { useInterval } from "@/hooks/use-interval";
import { config } from "@/lib/config";
import { documentService } from "@/services/document-service";
import type { ContractDocument, DocumentStatus } from "@/types";
import { cn } from "@/utils/cn";
import { isProcessing } from "@/utils/format";
import { DocumentsTable } from "./documents-table";
import { UploadDropzone } from "./upload-dropzone";

type Tab = "all" | "processing" | "ready" | "failed";
const TABS: { key: Tab; label: string; match: (s: DocumentStatus) => boolean }[] = [
  { key: "all", label: "All", match: () => true },
  { key: "processing", label: "Processing", match: isProcessing },
  { key: "ready", label: "Ready", match: (s) => s === "COMPLETED" },
  { key: "failed", label: "Failed", match: (s) => s === "FAILED" },
];

const NEXT: Partial<Record<DocumentStatus, DocumentStatus>> = {
  UPLOADED: "QUEUED", QUEUED: "PROCESSING", PROCESSING: "OCR_PROCESSING", OCR_PROCESSING: "CHUNKING",
  CHUNKING: "EMBEDDING", EMBEDDING: "INDEXING", INDEXING: "COMPLETED",
};

export function DocumentsView() {
  const { data, error, loading, reload } = useAsync(() => documentService.list(), []);
  const [docs, setDocs] = useState<ContractDocument[]>([]);
  const [tab, setTab] = useState<Tab>("all");

  useEffect(() => {
    if (data) setDocs(data);
  }, [data]);

  // Poll while anything is in flight. In demo mode we advance the pipeline
  // locally; against the API this re-fetches `/documents/{id}/status`.
  const inFlight = docs.some((d) => isProcessing(d.status));
  useInterval(
    () => {
      if (!config.useDemoData) return reload();
      setDocs((list) =>
        list.map((d) => {
          if (!isProcessing(d.status)) return d;
          const progress = Math.min(100, d.progress + 7);
          const status = progress >= 100 ? "COMPLETED" : progress % 21 < 7 ? (NEXT[d.status] ?? d.status) : d.status;
          return { ...d, progress, status, pages: d.pages || 12, updatedAt: new Date().toISOString() };
        }),
      );
    },
    inFlight ? 1500 : null,
  );

  const counts = useMemo(() => Object.fromEntries(TABS.map((t) => [t.key, docs.filter((d) => t.match(d.status)).length])), [docs]);
  const visible = docs.filter((d) => TABS.find((t) => t.key === tab)!.match(d.status));

  return (
    <>
      <PageHeader
        eyebrow="Repository"
        title="Contracts"
        description="Upload agreements, amendments and new versions. Each one is parsed, OCR'd where needed, split along its clause structure and indexed for cited retrieval."
      />
      <div className="space-y-5">
        <UploadDropzone onUploaded={(doc) => setDocs((list) => [doc, ...list])} />
        {error && <ErrorState error={error} onRetry={reload} />}
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
            <div role="tablist" className="flex gap-1 rounded-lg bg-sunken p-1">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={tab === t.key}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "rounded-md px-3 py-1 text-[13px] font-medium transition",
                    tab === t.key ? "bg-surface text-ink shadow-card" : "text-ink-2 hover:text-ink",
                  )}
                >
                  {t.label} <span className="num ml-1 text-ink-3">{counts[t.key] ?? 0}</span>
                </button>
              ))}
            </div>
            <button className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] text-ink-2 hover:bg-sunken">
              <Filter className="h-3.5 w-3.5" /> Type, counterparty, risk
            </button>
          </div>
          {loading && !docs.length ? (
            <div className="space-y-3 p-5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : visible.length ? (
            <DocumentsTable docs={visible} />
          ) : (
            <EmptyState icon={FileSearch} title="Nothing here yet" body="No contracts match this filter." />
          )}
        </Card>
      </div>
    </>
  );
}
