"use client";

import Link from "next/link";
import { ChevronRight, FileText, ScanText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { RiskBadge } from "@/components/ui/risk-badge";
import { StatusPill } from "@/components/ui/status-pill";
import type { ContractDocument } from "@/types";
import { formatBytes, relativeTime } from "@/utils/format";

export function DocumentsTable({ docs }: { docs: ContractDocument[] }) {
  return (
    <div className="overflow-x-auto scroll-thin">
      <table className="w-full min-w-[860px] text-left">
        <thead>
          <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">
            <th className="px-5 py-3 font-semibold">Contract</th>
            <th className="px-3 py-3 font-semibold">Type</th>
            <th className="px-3 py-3 font-semibold">Version</th>
            <th className="px-3 py-3 font-semibold">Status</th>
            <th className="px-3 py-3 font-semibold">Risk</th>
            <th className="px-3 py-3 text-right font-semibold">Updated</th>
            <th className="w-10" />
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {docs.map((doc) => (
            <tr key={doc.id} className="group transition-colors hover:bg-sunken">
              <td className="px-5 py-3.5">
                <Link href={`/documents/${doc.id}`} className="flex items-center gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-surface text-ink-2">
                    {doc.isScanned ? <ScanText className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-[13.5px] font-medium text-ink group-hover:text-brand">{doc.title}</span>
                    <span className="block truncate text-2xs text-ink-3">
                      {doc.counterparty} · {doc.pages ? `${doc.pages} pages · ` : ""}
                      {formatBytes(doc.sizeBytes)}
                    </span>
                    {doc.errorMessage && <span className="mt-0.5 block text-2xs text-danger">{doc.errorMessage}</span>}
                  </span>
                </Link>
              </td>
              <td className="px-3 py-3.5">
                <Badge>{doc.contractType}</Badge>
              </td>
              <td className="px-3 py-3.5 font-mono text-[12px] text-ink-2">
                {doc.version}
                {doc.versions.length > 1 && <span className="ml-1 text-ink-3">/ {doc.versions.length}</span>}
              </td>
              <td className="px-3 py-3.5">
                <StatusPill status={doc.status} progress={doc.progress} />
              </td>
              <td className="px-3 py-3.5">
                <RiskBadge level={doc.riskLevel} count={doc.riskCount} />
              </td>
              <td className="num px-3 py-3.5 text-right text-[12.5px] text-ink-3">{relativeTime(doc.updatedAt)}</td>
              <td className="pr-4">
                <ChevronRight className="h-4 w-4 text-ink-3 opacity-0 transition group-hover:opacity-100" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
