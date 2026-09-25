import { apiRequest } from "@/lib/api-client";
import { config } from "@/lib/config";
import { demoComparison, demoRiskFindings } from "@/lib/demo/fixtures";
import type { ComparisonRow, RiskFinding } from "@/types";
import { demoDelay } from "./_demo";

export const analysisService = {
  compare(leftVersionId: string, rightVersionId: string): Promise<ComparisonRow[]> {
    if (config.useDemoData) return demoDelay(demoComparison, 600);
    return apiRequest<ComparisonRow[]>("/contracts/compare", {
      method: "POST",
      body: { left_version_id: leftVersionId, right_version_id: rightVersionId },
      timeoutMs: 90_000,
    });
  },

  riskFindings(): Promise<RiskFinding[]> {
    if (config.useDemoData) return demoDelay(demoRiskFindings);
    return apiRequest<RiskFinding[]>("/contracts/risk-analysis", { method: "POST", body: {} });
  },
};
