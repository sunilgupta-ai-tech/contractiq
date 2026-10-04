"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { ArrowLeft, GitCompareArrows, History, Loader2, MessageSquareText, ScanSearch, ShieldAlert, Upload, Download, Fingerprint } from "lucide-react";
import { personalDataLevel, personalDataText } from "@/utils/personal-data";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { RiskBadge } from "@/components/ui/risk-badge";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { StatusPill } from "@/components/ui/status-pill";
import { useAsync } from "@/hooks/use-async";
import { ApiError } from "@/lib/api-client";
import { config } from "@/lib/config";
import { can, useMe } from "@/lib/session";
import { documentService } from "@/services/document-service";
import type { Citation, Clause } from "@/types";
import { cn } from "@/utils/cn";
import { formatDate } from "@/utils/format";
import { parseMarkdownTable } from "@/utils/markdown-table";
import { ACCEPT_BY_FILE_TYPE } from "@/utils/validation";
import { AccessCard } from "./access-card";
import { fileTypeLabel } from "./file-type";
import { DocumentChat } from "./document-chat";
import { FileViewer } from "./file-viewer";

/** A clause's text, or a real table when the clause is a table. */
function ClauseText({ text }: { text: string }) {
  const rows = parseMarkdownTable(text);
  if (!rows) return <>{text}</>;
  const [header, ...body] = rows;
  return (
    <span className="mt-2 block overflow-x-auto">
      <table className="w-full border-collapse font-sans text-[13px]">
        <thead>
          <tr>{header!.map((cell, i) => <th key={i} className="border-b border-[#D9D3C4] px-2 py-1.5 text-left font-semibold">{cell}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((row, r) => (
            <tr key={r}>{row.map((cell, i) => <td key={i} className="border-b border-[#ECE7DA] px-2 py-1.5">{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </span>
  );
}

function groupBySection(clauses: Clause[]) {
  const map = new Map<string, Clause[]>();
  for (const c of clauses) map.set(c.section, [...(map.get(c.section) ?? []), c]);
  return [...map.entries()];
}

const riskDot = { high: "bg-danger", medium: "bg-warn", low: "bg-ok" } as const;

export function ContractDetailView({ id }: { id: string }) {
  const me = useMe();
  const { data: doc, error, loading, reload } = useAsync(() => documentService.get(id), [id]);
  const [selected, setSelected] = useState<string>("c-8-3");
  const sections = useMemo(() => groupBySection(doc?.clauses ?? []), [doc]);
  const fileInput = useRef<HTMLInputElement>(null);
  // The original file is shown first; clause links switch to the extracted text.
  const [view, setView] = useState<"original" | "extracted">("original");
  const [viewerPage, setViewerPage] = useState<number | undefined>(undefined);
  // Chat beside the document; kept mounted after the first open so closing
  // and reopening it keeps the conversation.
  const [chatOpen, setChatOpen] = useState(false);
  const [chatStarted, setChatStarted] = useState(false);
  function openChat() {
    setChatOpen((open) => !open);
    setChatStarted(true);
  }
  function focusClause(clauseId: string) {
    setSelected(clauseId);
    setView("extracted");
    requestAnimationFrame(() => document.getElementById(clauseId)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<ApiError | null>(null);

  const [reviewed, setReviewed] = useState(false);
  async function markReviewed() {
    try {
      await documentService.markReviewed(id);
      setReviewed(true);
    } catch (err) {
      setUploadError(err instanceof ApiError ? err : new ApiError("Could not update the document.", "UNKNOWN", 0, null));
    }
  }

  async function uploadVersion(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      await documentService.uploadVersion(id, file);
      reload(); // the new version is now processing
    } catch (err) {
      setUploadError(err instanceof ApiError ? err : new ApiError("Upload failed.", "UNKNOWN", 0, null));
    } finally {
      setUploading(false);
    }
  }

  /** A chat citation: a PDF opens at the cited page; otherwise the cited clause is shown. */
  function showCitation(c: Citation) {
    // On a phone the chat covers the page: close it so the cited spot is visible.
    if (window.matchMedia("(max-width: 639px)").matches) setChatOpen(false);
    if (doc?.fileType === "PDF" && c.page) {
      setView("original");
      setViewerPage(c.page);
      return;
    }
    const clause = doc?.clauses.find((x) => x.number === c.clause);
    if (clause) focusClause(clause.id);
  }

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !doc) return <Skeleton className="h-[70vh] rounded-xl" />;

  return (
    <>
      <div className="mb-6 animate-fade-up">
        <Link href="/documents" className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-ink-2 hover:text-ink">
          <ArrowLeft className="h-3.5 w-3.5" /> Documents
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge>{doc.contractType}</Badge>
              <Badge tone="brand">{doc.version} · current</Badge>
              <StatusPill status={doc.status} progress={doc.progress} />
            </div>
            <h1 className="display text-[30px] leading-tight">{doc.title}</h1>
            <p className="mt-1 text-[13.5px] text-ink-2">
              {doc.counterparty !== "—" || doc.effectiveDate || doc.expiryDate
                ? `${doc.counterparty} · effective ${formatDate(doc.effectiveDate)} · expires ${formatDate(doc.expiryDate)}`
                : `${doc.fileName} · ${fileTypeLabel(doc)}`}
            </p>
          </div>
          <div className="flex gap-2">
            {!config.useDemoData && can(me, "document:upload") && (
              <>
                <input
                  ref={fileInput}
                  type="file"
                  accept={ACCEPT_BY_FILE_TYPE[doc.fileType]}
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file) void uploadVersion(file);
                  }}
                />
                <Button variant="secondary" disabled={uploading} onClick={() => fileInput.current?.click()}>
                  {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload new version
                </Button>
              </>
            )}
            {!config.useDemoData && doc.versions.length > 0 && (
              <Button
                variant="secondary"
                onClick={() => void documentService.download(doc.id, doc.versions.at(-1)!.id, doc.fileName).catch((err) => setUploadError(err))}
              >
                <Download className="h-4 w-4" /> Download
              </Button>
            )}
            {can(me, "analysis:run") && (
              <Link href="/compare">
                <Button variant="secondary"><GitCompareArrows className="h-4 w-4" /> Compare versions</Button>
              </Link>
            )}
            {can(me, "query:run") && (
              <Button onClick={openChat} aria-expanded={chatOpen}>
                <MessageSquareText className="h-4 w-4" /> {chatOpen ? "Hide chat" : "Ask this document"}
              </Button>
            )}
          </div>
        </div>
      </div>

      {uploadError && <div className="mb-5"><ErrorState error={uploadError} /></div>}
      {doc.needsReview && !reviewed && (
        <div role="note" className="mb-5 flex flex-wrap items-start gap-3 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-ink">
          <ScanSearch className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <span className="min-w-0 flex-1">
            <strong>Check this document&apos;s text.</strong> {reviewText(doc.reviewReasons)} Answers from it may be incomplete until
            someone compares it with the original.
          </span>
          {can(me, "document:upload") && (
            <Button size="sm" variant="secondary" onClick={() => void markReviewed()}>
              Mark reviewed
            </Button>
          )}
        </div>
      )}
      {doc.injectionFlags > 0 && (
        <div role="note" className="mb-5 flex items-start gap-2.5 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-ink">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <span>
            <strong>{doc.injectionFlags} passage{doc.injectionFlags === 1 ? "" : "s"} in this document read like instructions to an AI.</strong>{" "}
            The Assistant always treats document text as data, never as instructions — but check where this file came from.
          </span>
        </div>
      )}
      {personalDataLevel(doc.personalData) === "sensitive" && (
        <div role="alert" className="mb-5 flex items-start gap-2.5 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-ink">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <span>
            <strong>Sensitive details found: {personalDataText(doc.personalData)}.</strong>{" "}
            {doc.visibility === "ORGANIZATION"
              ? "Everyone in your organization who can view documents can open this file and ask about it. Limit who can see it under Access if they don't all need it."
              : "Access is limited to chosen people."}{" "}
            Every download and question about it is recorded in the audit log.
          </span>
        </div>
      )}
      {personalDataLevel(doc.personalData) === "contact" && (
        <div role="note" className="mb-5 flex items-start gap-2.5 rounded-xl border border-brand/20 bg-brand-soft px-4 py-3 text-[13px] text-ink">
          <Fingerprint className="mt-0.5 h-4 w-4 shrink-0 text-brand-ink" />
          <span>
            <strong>Contains personal data: {personalDataText(doc.personalData)}.</strong>{" "}
            Share it only with people who need it; every download and question about it is recorded in the audit log.
          </span>
        </div>
      )}
      <div
        className={cn(
          "grid grid-cols-1 gap-5 lg:grid-cols-[240px_minmax(0,1fr)]",
          chatOpen ? "xl:grid-cols-[240px_minmax(0,1fr)_400px]" : "2xl:grid-cols-[240px_minmax(0,1fr)_320px]",
        )}
      >
        {/* Outline */}
        <Card className="h-fit lg:sticky lg:top-20">
          <CardHeader eyebrow="Structure" title="Clauses" />
          <nav className="max-h-[60vh] overflow-y-auto scroll-thin p-2">
            {sections.map(([section, clauses]) => (
              <div key={section} className="mb-2">
                <p className="px-2 pb-1 pt-2 text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">{section}</p>
                {clauses.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => focusClause(c.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition",
                      selected === c.id ? "bg-brand-soft text-brand-ink" : "text-ink-2 hover:bg-sunken hover:text-ink",
                    )}
                  >
                    <span className="w-8 shrink-0 font-mono text-2xs text-ink-3">{c.number}</span>
                    <span className="flex-1 truncate">{c.title}</span>
                    {c.risk && <span className={cn("h-1.5 w-1.5 rounded-full", riskDot[c.risk])} />}
                  </button>
                ))}
              </div>
            ))}
          </nav>
        </Card>

        <div className="min-w-0">
        {sections.length > 0 && (
          <div role="tablist" aria-label="Document view" className="mb-3 inline-flex gap-1 rounded-lg bg-sunken p-1">
            {(["original", "extracted"] as const).map((v) => (
              <button
                key={v}
                role="tab"
                aria-selected={view === v}
                onClick={() => setView(v)}
                className={cn(
                  "rounded-md px-3 py-1 text-[13px] font-medium transition",
                  view === v ? "bg-surface text-ink shadow-card" : "text-ink-2 hover:text-ink",
                )}
              >
                {v === "original" ? "Original file" : "Extracted text"}
              </button>
            ))}
          </div>
        )}
        {view === "original" || sections.length === 0 ? (
          <FileViewer doc={doc} page={viewerPage} />
        ) : (
        /* Paper view */
        <div className="rounded-2xl border border-line bg-sunken p-3 sm:p-6">
          <article className="mx-auto max-w-[720px] rounded-sm bg-[#FFFEFB] px-7 py-10 text-[#23252B] shadow-paper sm:px-14 sm:py-14 dark:bg-[#1B2029] dark:text-[#DADDE3]">
            <p className="text-center font-serif text-[13px] uppercase tracking-[0.25em] text-[#8A8577]">{doc.contractType} · {doc.version}</p>
            <h2 className="mt-2 text-center font-serif text-[26px]">{doc.title}</h2>
            <p className="mb-10 mt-1 text-center text-[12.5px] text-[#8A8577]">
              {doc.counterparty !== "—" ? `with ${doc.counterparty}` : "\u00a0"}
            </p>
            {sections.map(([section, clauses]) => (
              <section key={section} className="mb-8">
                <h3 className="mb-3 font-serif text-[15px] font-semibold uppercase tracking-[0.08em]">{section}</h3>
                {clauses.map((c) => (
                  <p
                    id={c.id}
                    key={c.id}
                    onClick={() => setSelected(c.id)}
                    className={cn(
                      "-mx-3 mb-3 cursor-pointer rounded-md px-3 py-2 font-serif text-[15px] leading-7 transition",
                      selected === c.id ? "bg-mark/70 ring-1 ring-[#E3C766]" : "hover:bg-black/[0.025] dark:hover:bg-white/[0.03]",
                    )}
                  >
                    <span className="mr-2 font-sans text-[12px] font-semibold text-[#8A8577]">{c.number}</span>
                    <span className="font-semibold">{c.title}.</span> <ClauseText text={c.text} />
                    <span className="ml-2 font-sans text-2xs text-[#A09A8A]">p.{c.page}</span>
                  </p>
                ))}
              </section>
            ))}
          </article>
        </div>
        )}
        </div>

        {/* Inspector */}
        {/* Chat: a column beside the document on wide screens, a drawer below that.
            While it is open the inspector steps aside so the viewer keeps its width. */}
        {chatStarted && (
          <div
            className={cn(
              "fixed inset-0 z-40 sm:left-auto sm:w-[420px] sm:border-l sm:border-line sm:shadow-lift xl:sticky xl:inset-auto xl:top-20 xl:z-auto xl:h-[calc(100vh-17rem)] xl:min-h-[480px] xl:w-auto xl:border-0 xl:shadow-none",
              !chatOpen && "hidden",
            )}
          >
            <DocumentChat
              documentId={doc.id}
              title={doc.title}
              personalData={doc.personalData}
              onClose={() => setChatOpen(false)}
              onCite={showCitation}
            />
          </div>
        )}

        <div className={cn("space-y-5 lg:col-span-2 2xl:col-span-1", chatOpen && "xl:hidden")}>
          {!config.useDemoData && <AccessCard documentId={doc.id} />}
          <Card>
            <CardHeader eyebrow="Extracted" title="Key terms" />
            <dl className="divide-y divide-line">
              {doc.keyTerms.map((t) => (
                <div key={t.label} className="px-5 py-3">
                  <dt className="text-2xs text-ink-3">{t.label}</dt>
                  <dd className="mt-0.5 flex items-baseline justify-between gap-3 text-[13.5px] font-medium text-ink">
                    {t.value}
                    <span className="shrink-0 font-mono text-2xs font-normal text-ink-3">§{t.clause} · p.{t.page}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card>
            <CardHeader eyebrow="Assessment" title="Risk" action={<RiskBadge level={doc.riskLevel} count={doc.riskCount} />} />
            {doc.findings ? (
              <ul className="space-y-3 px-5 py-4">
                {doc.findings.length === 0 && <li className="text-[13px] text-ink-3">No risks flagged.</li>}
                {doc.findings.map((f) => (
                  <li key={f.id} className="text-[13px]">
                    <button
                      disabled={!f.clauseId}
                      onClick={() => f.clauseId && focusClause(f.clauseId)}
                      className="flex w-full items-center gap-2 text-left font-medium text-ink enabled:hover:text-brand"
                    >
                      <span className={cn("h-2 w-2 shrink-0 rounded-full", riskDot[f.severity])} />
                      {f.title}
                      {!f.clauseId && <span className="ml-auto shrink-0 text-2xs font-normal text-ink-3">not in contract</span>}
                    </button>
                    <p className="mt-0.5 pl-4 text-[12.5px] leading-5 text-ink-2">{f.rationale}</p>
                  </li>
                ))}
              </ul>
            ) : (
            <ul className="space-y-2 px-5 py-4">
              {doc.clauses.filter((c) => c.risk).map((c) => (
                <li key={c.id}>
                  <button onClick={() => focusClause(c.id)} className="flex w-full items-center gap-2 text-left text-[13px] text-ink-2 hover:text-ink">
                    <span className={cn("h-2 w-2 rounded-full", riskDot[c.risk!])} />
                    <span className="font-mono text-2xs text-ink-3">{c.number}</span> {c.title}
                  </button>
                </li>
              ))}
            </ul>
            )}
          </Card>
          <Card>
            <CardHeader eyebrow="Lineage" title="Versions" action={<History className="h-4 w-4 text-ink-3" />} />
            <ol className="px-5 py-4">
              {[...doc.versions].reverse().map((v, i) => (
                <li key={v.id} className="flex items-center justify-between py-1.5 text-[13px]">
                  <span className="flex items-center gap-2">
                    <span className={cn("h-2 w-2 rounded-full", i === 0 ? "bg-brand" : "bg-line-strong")} />
                    <span className="font-medium text-ink">{v.label}</span>
                  </span>
                  <span className="num text-2xs text-ink-3">{formatDate(v.uploadedAt)} · {v.pages}p</span>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
    </>
  );
}

const REVIEW_REASONS: Record<string, string> = {
  low_ocr_confidence: "Some scanned pages were hard to read.",
  no_text_found: "Some scanned pages produced no text.",
  damaged_pdf_recovered: "The PDF was damaged; its text was recovered with a fallback reader.",
};

/** Why a document needs a person to check it (Phase 21). */
function reviewText(reasons: string[]): string {
  return reasons.map((r) => REVIEW_REASONS[r] ?? r).join(" ");
}
