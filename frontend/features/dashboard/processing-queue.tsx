import Link from "next/link";
import { FileText, ScanText } from "lucide-react";
import { Card, CardHeader } from "@/components/ui/card";
import { PipelineStepper } from "@/components/ui/pipeline-stepper";
import type { ContractDocument } from "@/types";
import { relativeTime } from "@/utils/format";

export function ProcessingQueue({ docs }: { docs: ContractDocument[] }) {
  const recent = [...docs].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 5);
  return (
    <Card>
      <CardHeader
        eyebrow="Ingestion"
        title="Document pipeline"
        action={<Link href="/documents" className="text-[13px] font-medium text-brand hover:underline">View all</Link>}
      />
      <ul className="divide-y divide-line">
        {recent.map((doc) => (
          <li key={doc.id}>
            <Link href={`/documents/${doc.id}`} className="flex flex-col gap-2.5 px-5 py-3.5 transition-colors hover:bg-sunken">
              <div className="flex min-w-0 flex-1 items-center gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-sunken text-ink-2">
                  {doc.isScanned ? <ScanText className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[13.5px] font-medium text-ink">{doc.title}</p>
                  <p className="truncate text-2xs text-ink-3">
                    {doc.counterparty} · {relativeTime(doc.updatedAt)}
                  </p>
                </div>
              </div>
              <div className="overflow-x-auto pl-12 scroll-thin">
                <PipelineStepper status={doc.status} failedAt={doc.status === "FAILED" ? "PROCESSING" : undefined} />
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
