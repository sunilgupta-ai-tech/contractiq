/**
 * Demo fixtures — fictional organizations and contracts used while the
 * corresponding backend phases are being built (NEXT_PUBLIC_USE_DEMO_DATA).
 * Shapes match the real API types exactly, so switching to live data is a
 * service-layer change only.
 */
import type {
  AgentStep,
  ComparisonRow,
  ContractDetail,
  ContractDocument,
  KeyDate,
  QueryAnswer,
  RiskFinding,
} from "@/types";

const iso = (d: string) => new Date(d).toISOString();

export const demoDocuments: ContractDocument[] = [
  {
    id: "d-100", title: "Master Services Agreement", counterparty: "Northwind Logistics Ltd.", contractType: "MSA",
    status: "COMPLETED", progress: 100, pages: 42, sizeBytes: 3_420_112, version: "v2",
    versions: [
      { id: "v-100-1", label: "v1", uploadedAt: iso("2025-02-11"), pages: 38, status: "COMPLETED" },
      { id: "v-100-2", label: "v2", uploadedAt: iso("2026-08-29"), pages: 42, status: "COMPLETED" },
    ],
    effectiveDate: iso("2025-03-01"), expiryDate: iso("2027-02-28"), riskLevel: "high", riskCount: 4,
    updatedAt: iso("2026-09-24T15:12:00"), isScanned: false, tags: ["vendor", "logistics"],
  },
  {
    id: "d-101", title: "Cloud Hosting Services Agreement", counterparty: "Stratus Compute Inc.", contractType: "VENDOR",
    status: "EMBEDDING", progress: 72, pages: 28, sizeBytes: 1_904_330, version: "v1",
    versions: [{ id: "v-101-1", label: "v1", uploadedAt: iso("2026-09-25T06:58:00"), pages: 28, status: "EMBEDDING" }],
    effectiveDate: iso("2026-10-01"), expiryDate: iso("2029-09-30"), riskLevel: null, riskCount: 0,
    updatedAt: iso("2026-09-25T07:02:00"), isScanned: false, tags: ["vendor", "infrastructure"],
  },
  {
    id: "d-102", title: "Mutual Non-Disclosure Agreement", counterparty: "Helios Biotech GmbH", contractType: "NDA",
    status: "OCR_PROCESSING", progress: 38, pages: 9, sizeBytes: 6_812_004, version: "v1",
    versions: [{ id: "v-102-1", label: "v1", uploadedAt: iso("2026-09-25T06:49:00"), pages: 9, status: "OCR_PROCESSING" }],
    effectiveDate: null, expiryDate: null, riskLevel: null, riskCount: 0,
    updatedAt: iso("2026-09-25T07:01:00"), isScanned: true, tags: ["scanned"],
  },
  {
    id: "d-103", title: "Data Processing Addendum", counterparty: "Northwind Logistics Ltd.", contractType: "DPA",
    status: "COMPLETED", progress: 100, pages: 16, sizeBytes: 902_118, version: "v1",
    versions: [{ id: "v-103-1", label: "v1", uploadedAt: iso("2025-02-11"), pages: 16, status: "COMPLETED" }],
    effectiveDate: iso("2025-03-01"), expiryDate: iso("2027-02-28"), riskLevel: "medium", riskCount: 2,
    updatedAt: iso("2026-09-20T10:30:00"), isScanned: false, tags: ["privacy", "gdpr"],
  },
  {
    id: "d-104", title: "Software License & Support Agreement", counterparty: "Quillon Analytics", contractType: "VENDOR",
    status: "COMPLETED", progress: 100, pages: 31, sizeBytes: 2_210_450, version: "v3",
    versions: [
      { id: "v-104-1", label: "v1", uploadedAt: iso("2024-06-02"), pages: 27, status: "COMPLETED" },
      { id: "v-104-2", label: "Amendment 1", uploadedAt: iso("2025-06-18"), pages: 4, status: "COMPLETED" },
      { id: "v-104-3", label: "v3", uploadedAt: iso("2026-06-01"), pages: 31, status: "COMPLETED" },
    ],
    effectiveDate: iso("2024-07-01"), expiryDate: iso("2026-12-31"), riskLevel: "high", riskCount: 3,
    updatedAt: iso("2026-09-18T09:05:00"), isScanned: false, tags: ["software", "auto-renewal"],
  },
  {
    id: "d-105", title: "Office Lease — Bengaluru HQ", counterparty: "Prestige Estates Pvt. Ltd.", contractType: "LEASE",
    status: "COMPLETED", progress: 100, pages: 58, sizeBytes: 9_880_220, version: "v1",
    versions: [{ id: "v-105-1", label: "v1", uploadedAt: iso("2025-11-04"), pages: 58, status: "COMPLETED" }],
    effectiveDate: iso("2025-12-01"), expiryDate: iso("2030-11-30"), riskLevel: "low", riskCount: 1,
    updatedAt: iso("2026-09-12T14:44:00"), isScanned: true, tags: ["real-estate", "scanned"],
  },
  {
    id: "d-106", title: "Statement of Work #7 — Warehouse Automation", counterparty: "Northwind Logistics Ltd.", contractType: "SOW",
    status: "FAILED", progress: 25, pages: 0, sizeBytes: 14_221_900, version: "v1",
    versions: [{ id: "v-106-1", label: "v1", uploadedAt: iso("2026-09-24T18:20:00"), pages: 0, status: "FAILED" }],
    effectiveDate: null, expiryDate: null, riskLevel: null, riskCount: 0,
    updatedAt: iso("2026-09-24T18:21:00"), isScanned: false, tags: [],
    errorMessage: "The PDF is password-protected. Upload an unlocked copy.",
  },
  {
    id: "d-107", title: "Service Level Agreement", counterparty: "Stratus Compute Inc.", contractType: "SLA",
    status: "QUEUED", progress: 5, pages: 12, sizeBytes: 640_220, version: "v1",
    versions: [{ id: "v-107-1", label: "v1", uploadedAt: iso("2026-09-25T07:03:00"), pages: 12, status: "QUEUED" }],
    effectiveDate: null, expiryDate: null, riskLevel: null, riskCount: 0,
    updatedAt: iso("2026-09-25T07:03:00"), isScanned: false, tags: ["vendor"],
  },
];

export const demoDetail: ContractDetail = {
  ...(demoDocuments[0] as ContractDocument),
  keyTerms: [
    { label: "Termination notice", value: "60 days (was 30 in v1)", clause: "8.3", page: 25 },
    { label: "Liability cap", value: "Fees paid in prior 12 months", clause: "11.2", page: 31 },
    { label: "Renewal", value: "Auto-renews for 12 months", clause: "3.2", page: 6 },
    { label: "Payment terms", value: "Net 45 from invoice", clause: "6.1", page: 14 },
    { label: "Governing law", value: "England & Wales", clause: "17.1", page: 40 },
  ],
  clauses: [
    { id: "c-3-1", number: "3.1", title: "Initial Term", section: "Term", page: 6,
      text: "This Agreement commences on the Effective Date and continues for an initial term of twenty-four (24) months (the \"Initial Term\")." },
    { id: "c-3-2", number: "3.2", title: "Automatic Renewal", section: "Term", page: 6, risk: "medium",
      text: "Upon expiry of the Initial Term, this Agreement shall automatically renew for successive periods of twelve (12) months unless either Party gives written notice of non-renewal no later than ninety (90) days before the end of the then-current term." },
    { id: "c-6-1", number: "6.1", title: "Invoicing and Payment", section: "Fees and Payment", page: 14,
      text: "The Supplier shall invoice monthly in arrears. The Customer shall pay each undisputed invoice within forty-five (45) days of receipt." },
    { id: "c-8-1", number: "8.1", title: "Termination for Convenience", section: "Termination", page: 24,
      text: "The Customer may terminate this Agreement for convenience at any time by giving the Supplier written notice in accordance with clause 8.3." },
    { id: "c-8-2", number: "8.2", title: "Termination for Cause", section: "Termination", page: 24,
      text: "Either Party may terminate this Agreement with immediate effect by written notice if the other Party commits a material breach which is not remedied within thirty (30) days of notice requiring it to do so." },
    { id: "c-8-3", number: "8.3", title: "Notice Period", section: "Termination", page: 25, risk: "medium",
      text: "Any notice of termination under clause 8.1 shall be given not less than sixty (60) days prior to the intended date of termination." },
    { id: "c-11-1", number: "11.1", title: "Exclusions", section: "Limitation of Liability", page: 31,
      text: "Nothing in this Agreement limits either Party's liability for death or personal injury caused by negligence, or for fraud." },
    { id: "c-11-2", number: "11.2", title: "Liability Cap", section: "Limitation of Liability", page: 31, risk: "high",
      text: "Subject to clause 11.1, each Party's total aggregate liability arising under or in connection with this Agreement shall not exceed the Fees paid in the twelve (12) months preceding the event giving rise to the claim." },
    { id: "c-12-1", number: "12.1", title: "Indemnification", section: "Indemnities", page: 33, risk: "high",
      text: "The Customer shall indemnify the Supplier against all losses arising from any third-party claim relating to data supplied by the Customer, without limitation." },
    { id: "c-17-1", number: "17.1", title: "Governing Law", section: "General", page: 40,
      text: "This Agreement and any dispute arising out of it shall be governed by the laws of England and Wales." },
  ],
};

export const demoKeyDates: KeyDate[] = [
  { date: iso("2026-10-02"), label: "Non-renewal notice deadline", documentTitle: "Software License & Support Agreement", kind: "notice" },
  { date: iso("2026-11-30"), label: "Rent review window opens", documentTitle: "Office Lease — Bengaluru HQ", kind: "notice" },
  { date: iso("2026-12-01"), label: "Non-renewal notice deadline", documentTitle: "Master Services Agreement", kind: "notice" },
  { date: iso("2026-12-31"), label: "Auto-renews for 12 months", documentTitle: "Software License & Support Agreement", kind: "renewal" },
  { date: iso("2027-02-28"), label: "Initial term expires", documentTitle: "Data Processing Addendum", kind: "expiry" },
];

export const demoRiskFindings: RiskFinding[] = [
  { id: "r1", severity: "high", rule: "Uncapped indemnity", documentId: "d-100", documentTitle: "Master Services Agreement",
    clause: "12.1", page: 33, status: "open",
    excerpt: "The Customer shall indemnify the Supplier against all losses arising from any third-party claim relating to data supplied by the Customer, without limitation.",
    rationale: "Indemnity is expressly excluded from the liability cap in 11.2, creating unlimited exposure for data-related claims." },
  { id: "r2", severity: "high", rule: "Low liability cap", documentId: "d-100", documentTitle: "Master Services Agreement",
    clause: "11.2", page: 31, status: "reviewing",
    excerpt: "…shall not exceed the Fees paid in the twelve (12) months preceding the event giving rise to the claim.",
    rationale: "Cap tied to trailing 12-month fees can fall near zero early in the term or after a billing dispute." },
  { id: "r3", severity: "high", rule: "Automatic renewal", documentId: "d-104", documentTitle: "Software License & Support Agreement",
    clause: "14.1", page: 22, status: "open",
    excerpt: "This Agreement shall renew automatically for successive twelve (12) month terms at the then-current list price.",
    rationale: "Renewal at list price removes negotiated discounts; notice deadline is 2 Oct 2026." },
  { id: "r4", severity: "medium", rule: "Extended termination notice", documentId: "d-100", documentTitle: "Master Services Agreement",
    clause: "8.3", page: 25, status: "open",
    excerpt: "…not less than sixty (60) days prior to the intended date of termination.",
    rationale: "Notice period doubled from 30 to 60 days between v1 and v2." },
  { id: "r5", severity: "medium", rule: "Sub-processor approval", documentId: "d-103", documentTitle: "Data Processing Addendum",
    clause: "5.2", page: 7, status: "accepted",
    excerpt: "The Processor may engage sub-processors upon providing ten (10) days' notice to the Controller.",
    rationale: "Notice-only model with no right to object; below standard for GDPR Art. 28(2) general authorisation." },
  { id: "r6", severity: "medium", rule: "Unilateral price change", documentId: "d-104", documentTitle: "Software License & Support Agreement",
    clause: "7.4", page: 12, status: "open",
    excerpt: "The Licensor may adjust Support Fees annually upon thirty (30) days' notice.",
    rationale: "No ceiling on annual increases (e.g. CPI-linked cap)." },
  { id: "r7", severity: "low", rule: "Foreign governing law", documentId: "d-100", documentTitle: "Master Services Agreement",
    clause: "17.1", page: 40, status: "accepted",
    excerpt: "…governed by the laws of England and Wales.",
    rationale: "Differs from the organization's default (India). Consider enforcement costs." },
];

export const demoComparison: ComparisonRow[] = [
  { topic: "Termination notice", diff: "changed", risk: "medium",
    left: { clause: "8.3", page: 23, text: "…not less than thirty (30) days prior to the intended date of termination." },
    right: { clause: "8.3", page: 25, text: "…not less than sixty (60) days prior to the intended date of termination." },
    note: "Notice period doubled from 30 to 60 days." },
  { topic: "Liability cap", diff: "changed", risk: "high",
    left: { clause: "11.2", page: 29, text: "…shall not exceed the greater of ₹5 crore or the Fees paid in the twelve (12) months preceding the claim." },
    right: { clause: "11.2", page: 31, text: "…shall not exceed the Fees paid in the twelve (12) months preceding the event giving rise to the claim." },
    note: "₹5 crore floor removed — cap now depends only on trailing fees." },
  { topic: "Payment terms", diff: "changed",
    left: { clause: "6.1", page: 13, text: "…within thirty (30) days of receipt." },
    right: { clause: "6.1", page: 14, text: "…within forty-five (45) days of receipt." },
    note: "Payment window extended from Net 30 to Net 45 (favourable to Customer)." },
  { topic: "Automatic renewal", diff: "same",
    left: { clause: "3.2", page: 6, text: "…automatically renew for successive periods of twelve (12) months unless… ninety (90) days…" },
    right: { clause: "3.2", page: 6, text: "…automatically renew for successive periods of twelve (12) months unless… ninety (90) days…" },
    note: "No change." },
  { topic: "Data indemnity", diff: "missing", risk: "high",
    left: null,
    right: { clause: "12.1", page: 33, text: "The Customer shall indemnify the Supplier against all losses arising from any third-party claim relating to data supplied by the Customer, without limitation." },
    note: "New uncapped indemnity introduced in v2." },
  { topic: "Governing law", diff: "same",
    left: { clause: "17.1", page: 36, text: "…governed by the laws of England and Wales." },
    right: { clause: "17.1", page: 40, text: "…governed by the laws of England and Wales." },
    note: "No change." },
];

export const demoAgentSteps: AgentStep[] = [
  { key: "understand", label: "Query understanding", detail: "Intent: clause Q&A · entity: termination notice", durationMs: 180, status: "done" },
  { key: "select", label: "Document selection", detail: "1 contract · version v2 (current)", durationMs: 40, status: "done" },
  { key: "retrieve", label: "Hybrid retrieval", detail: "24 candidates · dense + BM25 · tenant filter applied", durationMs: 210, status: "done" },
  { key: "rerank", label: "Reranking", detail: "Top 6 kept · cross-encoder", durationMs: 160, status: "done" },
  { key: "extract", label: "Clause extraction", detail: "Clauses 8.1, 8.3 identified", durationMs: 90, status: "done" },
  { key: "validate", label: "Evidence validation", detail: "3/3 claims supported", durationMs: 120, status: "done" },
  { key: "answer", label: "Answer + citations", detail: "llama3.1:8b · 612 tokens", durationMs: 1340, status: "done" },
];

export const demoAnswer: QueryAnswer = {
  id: "a1",
  question: "What is the termination notice period in the Northwind MSA?",
  answer:
    "Under the current version (v2), the Customer may terminate for convenience at any time [1], but must give **not less than 60 days' written notice** before the intended termination date [2]. " +
    "This is a change from v1, which required only 30 days [3]. Termination for cause is separate: either party may terminate immediately if a material breach is not remedied within 30 days of notice [1].",
  citations: [
    { id: "c1", index: 1, documentId: "d-100", documentTitle: "Master Services Agreement", version: "v2", page: 24, section: "Termination", clause: "8.1–8.2",
      quote: "The Customer may terminate this Agreement for convenience at any time by giving the Supplier written notice in accordance with clause 8.3.", score: 0.91 },
    { id: "c2", index: 2, documentId: "d-100", documentTitle: "Master Services Agreement", version: "v2", page: 25, section: "Termination", clause: "8.3",
      quote: "Any notice of termination under clause 8.1 shall be given not less than sixty (60) days prior to the intended date of termination.", score: 0.96 },
    { id: "c3", index: 3, documentId: "d-100", documentTitle: "Master Services Agreement", version: "v1", page: 23, section: "Termination", clause: "8.3",
      quote: "…not less than thirty (30) days prior to the intended date of termination.", score: 0.84 },
  ],
  steps: demoAgentSteps,
  groundedness: 0.97,
  latencyMs: 2140,
  model: "llama3.1:8b (Ollama)",
};

export const suggestedQuestions = [
  "What is the termination notice period in the Northwind MSA?",
  "Which contracts renew automatically in the next 90 days?",
  "Identify contracts without an explicit liability cap.",
  "Compare payment terms across all active vendor contracts.",
  "Summarize the obligations of each party in the DPA.",
];
