import { apiRequest } from "@/lib/api-client";
import {
  toDetail,
  toDocument,
  toKeyDates,
  type ApiDocument,
  type ApiExtractedClause,
  type ApiKeyDate,
  type ApiKeyTerm,
  type ApiPage,
  type ApiRiskFinding,
} from "@/lib/adapters";
import { queued } from "@/lib/analysis-queue";
import { config } from "@/lib/config";
import { demoDetail, demoDocuments, demoKeyDates } from "@/lib/demo/fixtures";
import type { ContractDetail, ContractDocument, DocumentStatus, KeyDate } from "@/types";
import { demoDelay } from "./_demo";

// Contract analysis can take a while the first time a document is opened
// (one model call per clause topic); afterwards it is served from cache.
const ANALYSIS_TIMEOUT_MS = 120_000;

function analysisFor(id: string) {
  const post = <T,>(path: string, body: unknown) =>
    queued(() => apiRequest<T>(path, { method: "POST", body, timeoutMs: ANALYSIS_TIMEOUT_MS }));
  // Queued one after another: extraction fills the per-version cache first,
  // so the portfolio and risk requests reuse it instead of re-extracting.
  return Promise.all([
    post<{ clauses: ApiExtractedClause[] }>("/contracts/extract-clauses", { document_id: id }),
    post<{ documents: { key_terms: ApiKeyTerm[] }[] }>("/contracts/portfolio-summary", { document_ids: [id] }),
    post<{ findings: ApiRiskFinding[] }>("/contracts/risk-analysis", { document_ids: [id] }),
  ]).then(([clauses, portfolio, risk]) => ({
    clauses: clauses.clauses,
    keyTerms: portfolio.documents[0]?.key_terms ?? [],
    findings: risk.findings,
  }));
}

export const documentService = {
  async list(): Promise<ContractDocument[]> {
    if (config.useDemoData) return demoDelay(demoDocuments);
    const page = await apiRequest<ApiPage<ApiDocument>>("/documents?limit=200");
    return page.items.map(toDocument);
  },

  async get(id: string): Promise<ContractDetail> {
    if (config.useDemoData) {
      const doc = demoDocuments.find((d) => d.id === id) ?? demoDocuments[0]!;
      return demoDelay({ ...demoDetail, ...doc, clauses: demoDetail.clauses, keyTerms: demoDetail.keyTerms });
    }
    const doc = await apiRequest<ApiDocument>(`/documents/${encodeURIComponent(id)}`);
    if (doc.status !== "COMPLETED") return toDetail(doc, null);
    // The document is shown even if analysis is unavailable (e.g. model not configured).
    const analysis = await analysisFor(id).catch(() => null);
    return toDetail(doc, analysis);
  },

  async status(id: string): Promise<{ status: DocumentStatus; progress: number }> {
    const s = await apiRequest<{ status: DocumentStatus; progress: number }>(
      `/documents/${encodeURIComponent(id)}/status`,
    );
    return { status: s.status, progress: s.progress };
  },

  async upload(file: File, onProgress?: (pct: number) => void): Promise<ContractDocument> {
    if (config.useDemoData) {
      // Simulate upload progress, then return a queued document.
      return new Promise((resolve) => {
        let pct = 0;
        const timer = setInterval(() => {
          pct = Math.min(100, pct + 20);
          onProgress?.(pct);
          if (pct === 100) {
            clearInterval(timer);
            resolve({
              ...demoDocuments[7]!,
              id: `d-${Date.now()}`,
              title: file.name.replace(/\.pdf$/i, ""),
              counterparty: "Pending extraction",
              sizeBytes: file.size,
              status: "QUEUED",
              progress: 5,
              updatedAt: new Date().toISOString(),
            });
          }
        }, 180);
      });
    }
    const form = new FormData();
    form.append("file", file);
    const result = await apiRequest<{ document: ApiDocument }>("/documents/upload", {
      method: "POST",
      body: form,
      timeoutMs: 120_000,
    });
    onProgress?.(100);
    return toDocument(result.document);
  },

  /** Documents with at least two versions, each with its full version list
   *  (for the compare page). No contract analysis is triggered. */
  async comparable(): Promise<ContractDocument[]> {
    if (config.useDemoData) return demoDelay(demoDocuments.filter((d) => d.versions.length > 1));
    const page = await apiRequest<ApiPage<ApiDocument>>("/documents?limit=200");
    const versioned = page.items.filter((d) => (d.version_count ?? 1) > 1);
    const details = await Promise.all(
      versioned.map((d) => apiRequest<ApiDocument>(`/documents/${encodeURIComponent(d.id)}`)),
    );
    return details.map(toDocument);
  },

  async keyDates(): Promise<KeyDate[]> {
    if (config.useDemoData) return demoDelay(demoKeyDates);
    const portfolio = await queued(() =>
      apiRequest<{ upcoming_dates: ApiKeyDate[] }>("/contracts/portfolio-summary", {
        method: "POST",
        body: {},
        timeoutMs: ANALYSIS_TIMEOUT_MS,
      }),
    );
    return toKeyDates(portfolio.upcoming_dates);
  },
};
