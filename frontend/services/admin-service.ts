import { apiRequest } from "@/lib/api-client";

// Usage and audit log of the organization (Phase 22), for administrators.

export interface UsageMonth {
  period: string;
  queries: number;
  prompt_tokens: number;
  completion_tokens: number;
  embedding_tokens: number;
  model_calls: number;
}

export interface OrgUsage {
  plan: string;
  limits: {
    max_users: number | null;
    max_documents: number | null;
    max_storage_mb: number | null;
    max_ai_queries_month: number | null;
    max_ai_tokens_month: number | null;
  };
  current: { active_users: number; documents: number; storage_bytes: number };
  months: UsageMonth[];
}

export interface AuditEntry {
  id: string;
  action: string;
  actor_name: string | null;
  actor_email: string | null;
  resource_type: string;
  resource_id: string | null;
  ip_address: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export const tokensOf = (m: UsageMonth) => m.prompt_tokens + m.completion_tokens + m.embedding_tokens;

export const adminService = {
  usage: () => apiRequest<OrgUsage>("/usage"),
  audit(params: { action?: string; offset: number; limit: number }) {
    const q = new URLSearchParams({ offset: String(params.offset), limit: String(params.limit) });
    if (params.action) q.set("action", params.action);
    return apiRequest<{ items: AuditEntry[]; total: number }>(`/audit-logs?${q}`);
  },
};
