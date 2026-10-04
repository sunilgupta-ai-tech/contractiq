"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronRight, Download, Loader2, Lock, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { StatusPill } from "@/components/ui/status-pill";
import { config } from "@/lib/config";
import { documentService } from "@/services/document-service";
import type { ContractDocument } from "@/types";
import { formatBytes, formatDate, relativeTime } from "@/utils/format";
import { personalDataLevel, personalDataText } from "@/utils/personal-data";
import { FileTypeIcon, fileTypeLabel } from "./file-type";

/** " · 12 pages", " · 3 sheets"; nothing for a single image. */
function extent(doc: ContractDocument): string {
  if (!doc.pages || doc.fileType === "IMAGE") return "";
  const unit = doc.fileType === "EXCEL" ? "sheet" : "page";
  return ` · ${doc.pages} ${unit}${doc.pages === 1 ? "" : "s"}`;
}

/** Downloads the latest version's original file straight from the list. */
function RowDownload({ doc }: { doc: ContractDocument }) {
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  const version = doc.versions.at(-1);
  if (config.useDemoData || !version) return null;
  return (
    <button
      type="button"
      aria-label={`Download ${doc.fileName}`}
      title={state === "failed" ? "Download failed — try again" : "Download"}
      disabled={state === "busy"}
      onClick={() => {
        setState("busy");
        documentService.download(doc.id, version.id, doc.fileName).then(
          () => setState("idle"),
          () => setState("failed"),
        );
      }}
      className={
        state === "failed"
          ? "rounded-md p-1.5 text-danger hover:bg-surface"
          : "rounded-md p-1.5 text-ink-3 opacity-0 transition hover:bg-surface hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
      }
    >
      {state === "busy" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
    </button>
  );
}

export function DocumentsTable({ docs }: { docs: ContractDocument[] }) {
  return (
    <div className="overflow-x-auto scroll-thin">
      <table className="w-full min-w-[860px] text-left">
        <thead>
          <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">
            <th className="w-[44%] px-5 py-3 font-semibold">Name</th>
            <th className="px-3 py-3 font-semibold">Type</th>
            <th className="px-3 py-3 text-right font-semibold">Size</th>
            <th className="px-3 py-3 font-semibold">Version</th>
            <th className="px-3 py-3 font-semibold">Status</th>
            <th className="px-3 py-3 text-right font-semibold">Updated</th>
            <th className="w-20" />
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {docs.map((doc) => (
            <tr key={doc.id} className="group transition-colors hover:bg-sunken">
              <td className="max-w-0 px-5 py-3.5">
                <Link href={`/documents/${doc.id}`} className="flex items-center gap-3">
                  <FileTypeIcon doc={doc} />
                  <span className="min-w-0">
                    <span className="block truncate text-[13.5px] font-medium text-ink group-hover:text-brand">{doc.title}</span>
                    <span className="block truncate text-2xs text-ink-3">
                      {doc.fileName}
                      {doc.counterparty !== "—" && ` · ${doc.counterparty}`}
                      {extent(doc)}
                    </span>
                    {doc.errorMessage && <span className="mt-0.5 block text-2xs text-danger">{doc.errorMessage}</span>}
                  </span>
                </Link>
              </td>
              <td className="px-3 py-3.5">
                <span className="flex flex-wrap items-center gap-1">
                  <Badge>{fileTypeLabel(doc)}</Badge>
                  {doc.needsReview && <Badge tone="warn">Needs review</Badge>}
                  {personalDataLevel(doc.personalData) === "sensitive" && (
                    <span title={`Sensitive details: ${personalDataText(doc.personalData)}`}>
                      <Badge tone="warn">
                        <ShieldAlert className="h-3 w-3" /> Sensitive
                      </Badge>
                    </span>
                  )}
                  {doc.visibility === "RESTRICTED" && (
                    <Badge tone="warn">
                      <Lock className="h-3 w-3" /> Restricted
                    </Badge>
                  )}
                  {doc.contractType !== "OTHER" && <Badge tone="brand">{doc.contractType}</Badge>}
                </span>
              </td>
              <td className="num px-3 py-3.5 text-right text-[12.5px] text-ink-2">{formatBytes(doc.sizeBytes)}</td>
              <td className="px-3 py-3.5 font-mono text-[12px] text-ink-2">
                {doc.version}
                {doc.versions.length > 1 && <span className="ml-1 text-ink-3">/ {doc.versions.length}</span>}
              </td>
              <td className="px-3 py-3.5">
                <StatusPill status={doc.status} progress={doc.progress} />
              </td>
              <td className="num px-3 py-3.5 text-right text-[12.5px] text-ink-3" title={formatDate(doc.updatedAt)}>
                {relativeTime(doc.updatedAt)}
              </td>
              <td className="pr-4">
                <span className="flex items-center justify-end gap-1">
                  <RowDownload doc={doc} />
                  <ChevronRight className="h-4 w-4 text-ink-3 opacity-0 transition group-hover:opacity-100" />
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
