// Domain types mirror the backend's Pydantic schemas and enums.

export const DOCUMENT_STATUSES = [
  "UPLOADED",
  "QUEUED",
  "PROCESSING",
  "OCR_PROCESSING",
  "CHUNKING",
  "EMBEDDING",
  "INDEXING",
  "COMPLETED",
  "FAILED",
] as const;
export type DocumentStatus = (typeof DOCUMENT_STATUSES)[number];

export type ContractType =
  | "MSA" | "NDA" | "SOW" | "SLA" | "DPA" | "LEASE" | "EMPLOYMENT" | "VENDOR" | "AMENDMENT" | "OTHER";

export type RiskLevel = "high" | "medium" | "low";
export type Role = "ADMIN" | "LEGAL_MANAGER" | "ANALYST" | "VIEWER";

export interface DocumentVersionSummary {
  id: string;
  label: string;
  uploadedAt: string;
  pages: number;
  status: DocumentStatus;
}

export interface ContractDocument {
  id: string;
  title: string;
  counterparty: string;
  contractType: ContractType;
  status: DocumentStatus;
  progress: number; // 0-100 while processing
  pages: number;
  sizeBytes: number;
  version: string;
  versions: DocumentVersionSummary[];
  effectiveDate: string | null;
  expiryDate: string | null;
  riskLevel: RiskLevel | null;
  riskCount: number;
  updatedAt: string;
  isScanned: boolean;
  tags: string[];
  errorMessage?: string;
}

export interface Clause {
  id: string;
  number: string; // "8.3"
  title: string;
  section: string;
  page: number;
  text: string;
  risk?: RiskLevel;
}

export interface KeyTerm {
  label: string;
  value: string;
  clause: string;
  page: number;
}

export interface ContractDetail extends ContractDocument {
  clauses: Clause[];
  keyTerms: KeyTerm[];
}

export interface Citation {
  id: string;
  index: number;
  documentId: string;
  documentTitle: string;
  version: string;
  page: number;
  section: string;
  clause: string;
  quote: string;
  score: number;
}

export type AgentStepStatus = "pending" | "running" | "done" | "retry";

export interface AgentStep {
  key: string;
  label: string;
  detail: string;
  durationMs: number;
  status: AgentStepStatus;
}

export interface QueryAnswer {
  id: string;
  question: string;
  answer: string; // may contain [n] citation markers
  citations: Citation[];
  steps: AgentStep[];
  groundedness: number; // 0-1
  latencyMs: number;
  model: string;
}

export type DiffKind = "same" | "changed" | "missing";

export interface ComparisonRow {
  topic: string;
  left: { clause: string; text: string; page: number } | null;
  right: { clause: string; text: string; page: number } | null;
  diff: DiffKind;
  note: string;
  risk?: RiskLevel;
}

export interface RiskFinding {
  id: string;
  severity: RiskLevel;
  rule: string;
  documentId: string;
  documentTitle: string;
  clause: string;
  page: number;
  excerpt: string;
  rationale: string;
  status: "open" | "reviewing" | "accepted";
}

export interface KeyDate {
  date: string;
  label: string;
  documentTitle: string;
  kind: "renewal" | "expiry" | "notice";
}

export interface DependencyHealth {
  name: string;
  status: "up" | "down";
  latency_ms: number;
  critical: boolean;
  error: string | null;
}

export interface ReadinessReport {
  status: "ready" | "degraded" | "not_ready";
  dependencies: DependencyHealth[];
}

export interface LivenessReport {
  status: "ok";
  service: string;
  version: string;
  environment: string;
}
