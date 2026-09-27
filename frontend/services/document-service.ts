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
import { FILE_TYPES, type ContractDetail, type ContractDocument, type DocumentStatus, type FileType, type KeyDate } from "@/types";
import { isProcessing } from "@/utils/format";
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

const ANALYSED_TYPES = new Set<FileType>(["PDF", "WORD"]);

export type LibrarySort = "newest" | "oldest" | "name";
export type LibraryStatus = "all" | "processing" | "ready" | "failed";

export interface LibraryQuery {
  fileType: FileType | "ALL";
  status: LibraryStatus;
  q: string;
  sort: LibrarySort;
  offset: number;
  limit: number;
}

export interface LibraryPage {
  items: ContractDocument[];
  total: number;
}

export type LibraryCounts = Record<FileType | "ALL", number>;

const IN_PROGRESS: DocumentStatus[] = ["UPLOADED", "QUEUED", "PROCESSING", "OCR_PROCESSING", "CHUNKING", "EMBEDDING", "INDEXING"];
const STATUS_PARAMS: Record<LibraryStatus, DocumentStatus[]> = {
  all: [],
  processing: IN_PROGRESS,
  ready: ["COMPLETED"],
  failed: ["FAILED"],
};

function libraryParams(query: Pick<LibraryQuery, "status" | "q">): URLSearchParams {
  const params = new URLSearchParams();
  for (const s of STATUS_PARAMS[query.status]) params.append("status", s);
  if (query.q.trim()) params.set("q", query.q.trim());
  return params;
}

/** Demo mode: the same filters, applied to the fixtures. */
function demoMatches(d: ContractDocument, query: Pick<LibraryQuery, "status" | "q">): boolean {
  const statusOk =
    query.status === "all" ||
    (query.status === "processing" ? isProcessing(d.status) : STATUS_PARAMS[query.status].includes(d.status));
  const q = query.q.trim().toLowerCase();
  return statusOk && (!q || [d.title, d.counterparty, d.fileName].some((v) => v.toLowerCase().includes(q)));
}

export interface AccessGrant {
  kind: "user" | "role";
  id: string;
  name: string;
  email: string | null;
}

export interface DocumentAccessInfo {
  visibility: "ORGANIZATION" | "RESTRICTED";
  ownerId: string | null;
  ownerName: string | null;
  grants: AccessGrant[];
  canManage: boolean;
}

export interface Directory {
  users: { id: string; name: string; email: string }[];
  roles: { id: string; name: string }[];
}

interface ApiAccess {
  visibility: "ORGANIZATION" | "RESTRICTED";
  owner_id: string | null;
  owner_name: string | null;
  grants: AccessGrant[];
  can_manage: boolean;
}

const toAccess = (a: ApiAccess): DocumentAccessInfo => ({
  visibility: a.visibility,
  ownerId: a.owner_id,
  ownerName: a.owner_name,
  grants: a.grants,
  canManage: a.can_manage,
});

/** Who can see a document, and changing it (Phase 20). */
export const accessService = {
  async get(id: string): Promise<DocumentAccessInfo> {
    return toAccess(await apiRequest<ApiAccess>(`/documents/${encodeURIComponent(id)}/access`));
  },
  async set(id: string, visibility: "ORGANIZATION" | "RESTRICTED", userIds: string[], roleIds: string[]) {
    return toAccess(
      await apiRequest<ApiAccess>(`/documents/${encodeURIComponent(id)}/access`, {
        method: "PUT",
        body: { visibility, user_ids: userIds, role_ids: roleIds },
      }),
    );
  },
  async directory(): Promise<Directory> {
    const d = await apiRequest<{ users: { id: string; full_name: string; email: string }[]; roles: Directory["roles"] }>(
      "/documents/directory",
    );
    return { users: d.users.map((u) => ({ id: u.id, name: u.full_name, email: u.email })), roles: d.roles };
  },
};

export const documentService = {
  /** One page of the organization's library (Phase 15): filtered by file
   *  type, status and search, sorted and paged on the server. */
  async library(query: LibraryQuery): Promise<LibraryPage> {
    if (config.useDemoData) {
      const rows = demoDocuments
        .filter((d) => demoMatches(d, query) && (query.fileType === "ALL" || d.fileType === query.fileType))
        .sort((a, b) =>
          query.sort === "name"
            ? a.title.localeCompare(b.title)
            : (query.sort === "oldest" ? 1 : -1) * a.updatedAt.localeCompare(b.updatedAt),
        );
      return demoDelay({ items: rows.slice(query.offset, query.offset + query.limit), total: rows.length });
    }
    const params = libraryParams(query);
    if (query.fileType !== "ALL") params.set("file_type", query.fileType);
    params.set("sort", query.sort);
    params.set("offset", String(query.offset));
    params.set("limit", String(query.limit));
    const page = await apiRequest<ApiPage<ApiDocument>>(`/documents?${params}`);
    return { items: page.items.map(toDocument), total: page.total };
  },

  /** Documents per file type, for the library tabs. */
  async libraryCounts(query: Pick<LibraryQuery, "status" | "q">): Promise<LibraryCounts> {
    if (config.useDemoData) {
      const rows = demoDocuments.filter((d) => demoMatches(d, query));
      const counts = Object.fromEntries(FILE_TYPES.map((t) => [t, rows.filter((d) => d.fileType === t).length]));
      return demoDelay({ ALL: rows.length, ...counts } as LibraryCounts);
    }
    const facets = await apiRequest<{ all: number; by_file_type: Partial<Record<FileType, number>> }>(
      `/documents/facets?${libraryParams(query)}`,
    );
    const counts = Object.fromEntries(FILE_TYPES.map((t) => [t, facets.by_file_type[t] ?? 0]));
    return { ALL: facets.all, ...counts } as LibraryCounts;
  },

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
    // Clause and risk analysis is for agreements (PDF or Word). A photo or a
    // spreadsheet is searchable in the Assistant, but "missing indemnity
    // clause" findings would be noise — and cost model calls.
    if (doc.status !== "COMPLETED" || !ANALYSED_TYPES.has(doc.file_type ?? "PDF")) return toDetail(doc, null);
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

  async upload(
    file: File,
    onProgress?: (pct: number) => void,
    options: { private?: boolean } = {},
  ): Promise<ContractDocument> {
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
    if (options.private) form.append("visibility", "RESTRICTED");
    const result = await apiRequest<{ document: ApiDocument }>("/documents/upload", {
      method: "POST",
      body: form,
      timeoutMs: 120_000,
    });
    onProgress?.(100);
    return toDocument(result.document);
  },

  /** A document's title only (for labels); never triggers contract analysis. */
  async title(id: string): Promise<string> {
    if (config.useDemoData) return demoDocuments.find((d) => d.id === id)?.title ?? "Selected contract";
    const doc = await apiRequest<ApiDocument>(`/documents/${encodeURIComponent(id)}`);
    return doc.title;
  },

  /** Upload a new version of an existing document (processed like any upload). */
  async uploadVersion(documentId: string, file: File): Promise<ContractDocument> {
    const form = new FormData();
    form.append("file", file);
    form.append("document_id", documentId);
    const result = await apiRequest<{ document: ApiDocument }>("/documents/upload", {
      method: "POST",
      body: form,
      timeoutMs: 120_000,
    });
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
