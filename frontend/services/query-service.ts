import { apiRequest } from "@/lib/api-client";
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
  ask(req: QueryRequest): Promise<QueryAnswer> {
    if (config.useDemoData) {
      return demoDelay({ ...demoAnswer, id: `a-${Date.now()}`, question: req.question }, 2200);
    }
    return apiRequest<QueryAnswer>("/query", {
      method: "POST",
      body: { question: req.question, document_ids: req.documentIds, conversation_id: req.conversationId },
      timeoutMs: 60_000,
    });
  },
};
