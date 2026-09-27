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

/** Library tabs (Phase 15). A scanned PDF is still "PDF" (see `isScanned`). */
export const FILE_TYPES = ["PDF", "IMAGE", "WORD", "EXCEL"] as const;
export type FileType = (typeof FILE_TYPES)[number];

export type RiskLevel = "high" | "medium" | "low";
/** Phase 17: what a role may do (mirrors backend `Permission`). */
export const PERMISSIONS = [
  "document:read",
  "document:upload",
  "document:delete",
  "document:share",
  "document:read_all",
  "query:run",
  "analysis:run",
  "evaluation:run",
  "user:manage",
  "role:manage",
] as const;
export type Permission = (typeof PERMISSIONS)[number];

export interface PermissionInfo {
  key: Permission;
  group: string;
  label: string;
  description: string;
}

export interface RoleDef {
  id: string;
  name: string;
  description: string;
  permissions: Permission[];
  isSystem: boolean;
  memberCount: number;
}

export interface TeamMember {
  id: string;
  email: string;
  name: string;
  roleId: string;
  roleName: string;
  isActive: boolean;
  lastLoginAt: string | null;
  createdAt: string;
}

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
  fileType: FileType;
  fileName: string; // original name of the latest version
  /** Phase 20: RESTRICTED = only the uploader, chosen people/roles and admins. */
  visibility: "ORGANIZATION" | "RESTRICTED";
  /** Phase 20: passages in the latest version that read like instructions to an AI. */
  injectionFlags: number;
  /** Phase 24: personal data found in the latest version — distinct values per kind
   *  (aadhaar, pan, card, email, phone). Counts only; never the values. */
  personalData: Record<string, number>;
  /** Phase 21: the recovered text may be unreliable; a person should check it. */
  needsReview: boolean;
  reviewReasons: string[];
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
  /** Live data only: every risk finding, including missing protective clauses. */
  findings?: { id: string; title: string; severity: RiskLevel; rationale: string; clauseId?: string }[];
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
  /** A protective clause was not found, so there is no clause or page to cite. */
  missing?: boolean;
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
