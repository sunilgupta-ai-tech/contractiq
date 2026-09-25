import { apiRequest } from "@/lib/api-client";
import type { LivenessReport, ReadinessReport } from "@/types";

// Health is always live — never demo data — so the System page tells the truth
// about the running stack.
export const healthService = {
  liveness: () => apiRequest<LivenessReport>("/health", { timeoutMs: 5_000 }),
  readiness: () => apiRequest<ReadinessReport>("/ready", { timeoutMs: 8_000, acceptErrorData: true }),
};
