import { apiRequest } from "@/lib/api-client";
import { toAnswer, type ApiQueryResponse } from "@/lib/adapters";
import { config } from "@/lib/config";
import { demoAnswer } from "@/lib/demo/fixtures";
import type { QueryAnswer } from "@/types";
import { demoDelay } from "./_demo";

export interface QueryRequest {
  question: string;
  documentIds: string[];
  conversationId?: string;
}

export const queryService = {
  async ask(req: QueryRequest): Promise<QueryAnswer> {
    if (config.useDemoData) {
      return demoDelay({ ...demoAnswer, id: `a-${Date.now()}`, question: req.question }, 2200);
    }
    const response = await apiRequest<ApiQueryResponse>("/query", {
      method: "POST",
      body: { question: req.question, document_ids: req.documentIds, conversation_id: req.conversationId },
      timeoutMs: 120_000, // agent mode may retry searches (AGENT_TIMEOUT_S = 90 s)
    });
    return toAnswer(response);
  },
};
