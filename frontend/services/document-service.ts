import { apiRequest } from "@/lib/api-client";
import { config } from "@/lib/config";
import { demoDetail, demoDocuments, demoKeyDates } from "@/lib/demo/fixtures";
import type { ContractDetail, ContractDocument, DocumentStatus, KeyDate } from "@/types";
import { demoDelay } from "./_demo";

export const documentService = {
  list(): Promise<ContractDocument[]> {
    if (config.useDemoData) return demoDelay(demoDocuments);
    return apiRequest<ContractDocument[]>("/documents");
  },

  get(id: string): Promise<ContractDetail> {
    if (config.useDemoData) {
      const doc = demoDocuments.find((d) => d.id === id) ?? demoDocuments[0]!;
      return demoDelay({ ...demoDetail, ...doc, clauses: demoDetail.clauses, keyTerms: demoDetail.keyTerms });
    }
    return apiRequest<ContractDetail>(`/documents/${encodeURIComponent(id)}`);
  },

  status(id: string): Promise<{ status: DocumentStatus; progress: number }> {
    return apiRequest(`/documents/${encodeURIComponent(id)}/status`);
  },

  upload(file: File, onProgress?: (pct: number) => void): Promise<ContractDocument> {
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
    return apiRequest<ContractDocument>("/documents/upload", { method: "POST", body: form, timeoutMs: 120_000 });
  },

  keyDates(): Promise<KeyDate[]> {
    return demoDelay(demoKeyDates);
  },
};
