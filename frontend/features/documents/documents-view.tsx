"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, FileSearch, Search, ShieldAlert, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { useInterval } from "@/hooks/use-interval";
import {
  documentService,
  type LibrarySort,
  type LibraryStatus,
} from "@/services/document-service";
import { can, useMe } from "@/lib/session";
import type { FileType } from "@/types";
import { cn } from "@/utils/cn";
import { isProcessing } from "@/utils/format";
import { personalDataLevel, sensitiveText } from "@/utils/personal-data";
import { DocumentsTable } from "./documents-table";
import { FILE_TYPE_META } from "./file-type";
import { UploadDropzone } from "./upload-dropzone";

const PAGE_SIZE = 50;

const TABS: { key: FileType | "ALL"; label: string }[] = [
  { key: "ALL", label: "All" },
  { key: "PDF", label: FILE_TYPE_META.PDF.plural },
  { key: "IMAGE", label: FILE_TYPE_META.IMAGE.plural },
  { key: "WORD", label: FILE_TYPE_META.WORD.plural },
  { key: "EXCEL", label: FILE_TYPE_META.EXCEL.plural },
];

const STATUSES: { key: LibraryStatus; label: string }[] = [
  { key: "all", label: "Any status" },
  { key: "processing", label: "Processing" },
  { key: "ready", label: "Ready" },
  { key: "failed", label: "Failed" },
  { key: "review", label: "Needs review" },
];

const SORTS: { key: LibrarySort; label: string }[] = [
  { key: "newest", label: "Newest first" },
  { key: "oldest", label: "Oldest first" },
  { key: "name", label: "Name A–Z" },
];

/** The organization's document library (Phase 15): every file type in one
 *  place, filtered, searched, sorted and paged on the server so it stays
 *  fast with thousands of documents. */
export function DocumentsView() {
  const me = useMe();
  const [fileType, setFileType] = useState<FileType | "ALL">("ALL");
  const [status, setStatus] = useState<LibraryStatus>("all");
  const [sort, setSort] = useState<LibrarySort>("newest");
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);

  // Any change of filter starts again from the first page.
  const refilter =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      set(value);
      setPage(0);
    };

  // Search as you type, once typing pauses.
  useEffect(() => {
    const next = input.trim();
    if (next === q) return;
    const timer = setTimeout(() => {
      setQ(next);
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [input, q]);

  const list = useAsync(
    () => documentService.library({ fileType, status, q, sort, offset: page * PAGE_SIZE, limit: PAGE_SIZE }),
    [fileType, status, q, sort, page],
  );
  const counts = useAsync(() => documentService.libraryCounts({ status, q }), [status, q]);

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const reload = () => {
    list.reload();
    counts.reload();
  };

  // Files uploaded on this page are watched until processed; any found to hold
  // sensitive details are called out once, until dismissed.
  const [uploadedIds, setUploadedIds] = useState<string[]>([]);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const sensitiveUploads = items.filter(
    (d) =>
      uploadedIds.includes(d.id) &&
      !dismissed.includes(d.id) &&
      d.status === "COMPLETED" &&
      personalDataLevel(d.personalData) === "sensitive",
  );

  // Keep processing documents' status current.
  useInterval(reload, items.some((d) => isProcessing(d.status)) ? 3000 : null);

  const filtered = Boolean(q) || status !== "all" || fileType !== "ALL";
  const first = total ? page * PAGE_SIZE + 1 : 0;
  const last = Math.min(total, (page + 1) * PAGE_SIZE);

  return (
    <>
      <PageHeader
        eyebrow="Library"
        title="Documents"
        description="Every file your organization has uploaded, in one place. Only members of your organization can see them."
      />
      <div className="space-y-5">
        {can(me, "document:upload") && (
          <UploadDropzone
            onUploaded={(doc) => {
              setUploadedIds((ids) => [...ids, doc.id]);
              reload();
            }}
          />
        )}
        {sensitiveUploads.map((d) => (
          <div key={d.id} role="alert" className="flex items-start gap-2.5 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-ink">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
            <span className="min-w-0 flex-1">
              <strong>{d.title} contains sensitive details: {sensitiveText(d.personalData)}.</strong>{" "}
              {d.visibility === "ORGANIZATION" ? "Everyone in your organization can open it. " : ""}
              <Link href={`/documents/${d.id}`} className="font-medium text-brand hover:underline">
                Review who can see it →
              </Link>
            </span>
            <button
              onClick={() => setDismissed((ids) => [...ids, d.id])}
              aria-label={`Dismiss warning for ${d.title}`}
              className="rounded p-0.5 text-ink-3 hover:text-ink"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        {list.error && <ErrorState error={list.error} onRetry={reload} />}
        <Card>
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
            <div role="tablist" aria-label="File type" className="flex flex-wrap gap-1 rounded-lg bg-sunken p-1">
              {TABS.map((t) => (
                <TabButton
                  key={t.key}
                  active={fileType === t.key}
                  onClick={() => refilter(setFileType)(t.key)}
                  label={t.label}
                  count={counts.data?.[t.key]}
                />
              ))}
            </div>

            <div className="ml-auto flex flex-wrap items-center gap-2">
              <label className="group flex h-9 w-full items-center gap-2 rounded-lg border border-line bg-surface px-3 text-ink-3 focus-within:border-brand/50 sm:w-64">
                <Search className="h-4 w-4 shrink-0" />
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Search name or file…"
                  aria-label="Search documents"
                  className="h-full w-full bg-transparent text-[13px] text-ink placeholder:text-ink-3 focus:outline-none focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0"
                />
                {input && (
                  <button onClick={() => setInput("")} aria-label="Clear search" className="rounded p-0.5 hover:text-ink">
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </label>
              <Select label="Status" value={status} options={STATUSES} onChange={refilter(setStatus)} />
              <Select label="Sort" value={sort} options={SORTS} onChange={refilter(setSort)} />
            </div>
          </div>

          {list.loading && !list.data ? (
            <div className="space-y-3 p-5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : items.length ? (
            <DocumentsTable docs={items} />
          ) : (
            <EmptyState
              icon={FileSearch}
              title={filtered ? "No matching documents" : "No documents yet"}
              body={filtered ? "Try another tab, status or search." : "Upload a file above to start your library."}
            />
          )}

          {total > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-[12.5px] text-ink-3">
              <span className="num">
                {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()}
              </span>
              <div className="flex items-center gap-1">
                <PageButton label="Previous page" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  <ChevronLeft className="h-4 w-4" />
                </PageButton>
                <PageButton label="Next page" disabled={last >= total} onClick={() => setPage((p) => p + 1)}>
                  <ChevronRight className="h-4 w-4" />
                </PageButton>
              </div>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function TabButton({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count?: number }) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-1 text-[13px] font-medium transition",
        active ? "bg-surface text-ink shadow-card" : "text-ink-2 hover:text-ink",
      )}
    >
      {label}
      <span className="num ml-1.5 text-ink-3">{count === undefined ? "·" : count.toLocaleString()}</span>
    </button>
  );
}

function Select<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { key: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="h-9 rounded-lg border border-line bg-surface px-2.5 text-[13px] text-ink-2 focus:border-brand/50 focus:outline-none"
    >
      {options.map((o) => (
        <option key={o.key} value={o.key}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function PageButton({ label, disabled, onClick, children }: { label: string; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-8 w-8 place-items-center rounded-lg border border-line text-ink-2 transition hover:bg-sunken disabled:pointer-events-none disabled:opacity-40"
    >
      {children}
    </button>
  );
}
