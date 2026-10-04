// Backend (snake_case, as the Pydantic schemas return it) -> UI domain types.
//
// The pages were built against `types/index.ts` with demo data; the API
// answers in its own shapes. Converting here, in one place, keeps every page
// component unaware of the wire format, and makes the mapping unit-testable.

import type {
  AgentStep,
  AgentStepStatus,
  Citation,
  Clause,
  ComparisonRow,
  ContractDetail,
  ContractDocument,
  ContractType,
  DocumentStatus,
  DocumentVersionSummary,
  FileType,
  KeyDate,
  KeyTerm,
  QueryAnswer,
  RiskFinding,
  RiskLevel,
} from "@/types";

// --- Wire types (subset of the backend schemas actually used) -------------------------

export interface ApiVersion {
  id: string;
  label: string;
  original_filename?: string;
  page_count: number | null;
  size_bytes: number;
  is_scanned: boolean | null;
  status: DocumentStatus;
  error_message: string | null;
  injection_flags?: number;
  pii?: Record<string, number>;
  review_reasons?: string[];
  created_at: string;
}

export interface ApiDocument {
  id: string;
  title: string;
  contract_type: ContractType;
  file_type?: FileType;
  visibility?: "ORGANIZATION" | "RESTRICTED";
  needs_review?: boolean;
  counterparty: string | null;
  status: DocumentStatus;
  effective_date: string | null;
  expiry_date: string | null;
  tags: string[];
  latest_version: ApiVersion | null;
  version_count?: number;
  updated_at: string;
  versions?: ApiVersion[];
}

export interface ApiPage<T> {
  items: T[];
  total: number;
}

export interface ApiCitation {
  index: number;
  chunk_id: string;
  document_id: string;
  document_title: string | null;
  version_label: string;
  page: number;
  section: string | null;
  section_title: string | null;
  clause: string | null;
  quote: string;
  score: number;
  also_found_in?: { document_id: string; document_title: string | null }[];
}

export interface ApiQueryResponse {
  id: string;
  question: string;
  answer: string;
  citations: ApiCitation[];
  steps: { key: string; label: string; detail: string; duration_ms: number; status: string }[];
  cited_fraction: number;
  groundedness?: number | null;
  model: string | null;
  latency_ms: number;
}

export interface ApiExtractedClause {
  topic: string;
  label: string;
  found: boolean;
  quote: string | null;
  clause: string | null;
  page: number | null;
  evidence: { section: string | null; section_title: string | null } | null;
}

export interface ApiRiskFinding {
  id: string;
  rule: string;
  title: string;
  severity: RiskLevel;
  topic: string;
  rationale: string;
  missing: boolean;
  document_id: string;
  document_title: string | null;
  clause: string | null;
  page: number | null;
  excerpt: string | null;
  status: "open";
}

export interface ApiKeyTerm {
  label: string;
  value: string;
  clause: string | null;
  page: number | null;
}

export interface ApiKeyDate {
  date: string;
  label: string;
  kind: "start" | "expiry" | "renewal" | "notice";
  document_title: string;
}

export interface ApiComparisonRow {
  label: string;
  diff: ComparisonRow["diff"];
  note: string;
  left: { clause: string | null; page: number | null; text: string } | null;
  right: { clause: string | null; page: number | null; text: string } | null;
  risk: RiskLevel | null;
}

// --- Documents -----------------------------------------------------------------------------

// Processing progress by pipeline status, for the list's progress bars
// (the precise per-job value comes from /documents/{id}/status).
const PROGRESS: Record<DocumentStatus, number> = {
  UPLOADED: 0,
  QUEUED: 5,
  PROCESSING: 15,
  OCR_PROCESSING: 35,
  CHUNKING: 60,
  EMBEDDING: 75,
  INDEXING: 90,
  COMPLETED: 100,
  FAILED: 0,
};

function toVersion(v: ApiVersion): DocumentVersionSummary {
  return { id: v.id, label: v.label, uploadedAt: v.created_at, pages: v.page_count ?? 0, status: v.status };
}

export function toDocument(d: ApiDocument): ContractDocument {
  const latest = d.latest_version;
  const versions = (d.versions ?? (latest ? [latest] : [])).map(toVersion);
  return {
    id: d.id,
    title: d.title,
    counterparty: d.counterparty ?? "—",
    contractType: d.contract_type,
    fileType: d.file_type ?? "PDF",
    fileName: latest?.original_filename ?? d.title,
    visibility: d.visibility ?? "ORGANIZATION",
    injectionFlags: latest?.injection_flags ?? 0,
    personalData: latest?.pii ?? {},
    needsReview: d.needs_review ?? false,
    reviewReasons: latest?.review_reasons ?? [],
    status: d.status,
    progress: PROGRESS[d.status] ?? 0,
    pages: latest?.page_count ?? 0,
    sizeBytes: latest?.size_bytes ?? 0,
    version: latest?.label ?? "v1",
    versions,
    effectiveDate: d.effective_date,
    expiryDate: d.expiry_date,
    riskLevel: null, // filled on the detail page from risk analysis
    riskCount: 0,
    updatedAt: d.updated_at,
    isScanned: latest?.is_scanned ?? false,
    tags: d.tags,
    errorMessage: latest?.error_message ?? undefined,
  };
}

const ORDER: Record<RiskLevel, number> = { high: 0, medium: 1, low: 2 };

export function worstRisk(findings: { severity: RiskLevel }[]): RiskLevel | null {
  return findings.reduce<RiskLevel | null>(
    (worst, f) => (worst === null || ORDER[f.severity] < ORDER[worst] ? f.severity : worst),
    null,
  );
}

/** Document detail + (optional) analysis: clauses, key terms, risk. */
export function toDetail(
  d: ApiDocument,
  analysis: { clauses: ApiExtractedClause[]; keyTerms: ApiKeyTerm[]; findings: ApiRiskFinding[] } | null,
): ContractDetail {
  const base = toDocument(d);
  if (!analysis) return { ...base, clauses: [], keyTerms: [] };
  const riskByTopic = new Map<string, RiskLevel>();
  for (const f of analysis.findings) {
    const current = riskByTopic.get(f.topic);
    if (!current || ORDER[f.severity] < ORDER[current]) riskByTopic.set(f.topic, f.severity);
  }
  const clauses: Clause[] = analysis.clauses
    .filter((c) => c.found)
    .map((c) => ({
      id: c.topic,
      number: c.clause ?? "",
      title: c.label,
      section: c.evidence?.section_title ?? c.evidence?.section ?? "",
      page: c.page ?? 0,
      text: c.quote ?? "",
      risk: riskByTopic.get(c.topic),
    }));
  const keyTerms: KeyTerm[] = analysis.keyTerms.map((t) => ({
    label: t.label,
    value: t.value,
    clause: t.clause ?? "",
    page: t.page ?? 0,
  }));
  const found = new Set(clauses.map((c) => c.id));
  return {
    ...base,
    clauses,
    keyTerms,
    findings: analysis.findings.map((f) => ({
      id: f.id,
      title: f.title,
      severity: f.severity,
      rationale: f.rationale,
      clauseId: !f.missing && found.has(f.topic) ? f.topic : undefined,
    })),
    riskLevel: worstRisk(analysis.findings),
    riskCount: analysis.findings.length,
  };
}

// --- Q&A -----------------------------------------------------------------------------------

const STEP_STATUS: Record<string, AgentStepStatus> = { done: "done", retry: "retry", running: "running" };

export function toAnswer(r: ApiQueryResponse): QueryAnswer {
  const citations: Citation[] = r.citations.map((c) => ({
    id: `${c.chunk_id}-${c.index}`,
    index: c.index,
    documentId: c.document_id,
    documentTitle: c.document_title ?? "",
    version: c.version_label,
    page: c.page,
    section: c.section_title ?? c.section ?? "",
    clause: c.clause ?? "",
    quote: c.quote,
    score: c.score,
    alsoFoundIn: (c.also_found_in ?? []).map((d) => ({ documentId: d.document_id, title: d.document_title || "Untitled document" })),
  }));
  const steps: AgentStep[] = r.steps.map((s) => ({
    key: s.key,
    label: s.label,
    detail: s.detail,
    durationMs: s.duration_ms,
    status: STEP_STATUS[s.status] ?? "done",
  }));
  return {
    id: r.id,
    question: r.question,
    answer: r.answer,
    citations,
    steps,
    // Phase 11 groundedness when an answer was generated; citation coverage otherwise.
    groundedness: r.groundedness ?? r.cited_fraction,
    latencyMs: r.latency_ms,
    model: r.model ?? "—",
  };
}

// --- Analysis ------------------------------------------------------------------------------

export function toRiskFinding(f: ApiRiskFinding): RiskFinding {
  return {
    id: f.id,
    severity: f.severity,
    rule: f.title,
    documentId: f.document_id,
    documentTitle: f.document_title ?? "",
    clause: f.clause ?? "—",
    page: f.page ?? 0,
    excerpt: f.excerpt ?? (f.missing ? "No such clause was found in this contract." : ""),
    rationale: f.rationale,
    status: f.status,
    missing: f.missing,
  };
}

export function toComparisonRow(r: ApiComparisonRow): ComparisonRow {
  const side = (s: ApiComparisonRow["left"]) =>
    s ? { clause: s.clause ?? "—", text: s.text, page: s.page ?? 0 } : null;
  return {
    topic: r.label,
    left: side(r.left),
    right: side(r.right),
    diff: r.diff,
    note: r.note,
    risk: r.risk ?? undefined,
  };
}

export function toKeyDates(dates: ApiKeyDate[]): KeyDate[] {
  // The dashboard shows deadlines; a contract's start date is not one.
  return dates
    .filter((d): d is ApiKeyDate & { kind: KeyDate["kind"] } => d.kind !== "start")
    .map((d) => ({ date: d.date, label: d.label, documentTitle: d.document_title, kind: d.kind }));
}
