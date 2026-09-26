import { apiRequest } from "@/lib/api-client";
import { toComparisonRow, toRiskFinding, type ApiComparisonRow, type ApiRiskFinding } from "@/lib/adapters";
import { queued } from "@/lib/analysis-queue";
import { config } from "@/lib/config";
import { demoComparison, demoRiskFindings } from "@/lib/demo/fixtures";
import type { ComparisonRow, RiskFinding } from "@/types";
import { demoDelay } from "./_demo";

export const analysisService = {
  async compare(leftVersionId: string, rightVersionId: string): Promise<ComparisonRow[]> {
    if (config.useDemoData) return demoDelay(demoComparison, 600);
    const result = await queued(() =>
      apiRequest<{ rows: ApiComparisonRow[] }>("/contracts/compare", {
        method: "POST",
        body: { left_version_id: leftVersionId, right_version_id: rightVersionId },
        timeoutMs: 180_000, // both versions may need analysing the first time
      }),
    );
    return result.rows.map(toComparisonRow);
  },

  async riskFindings(): Promise<RiskFinding[]> {
    if (config.useDemoData) return demoDelay(demoRiskFindings);
    const result = await queued(() =>
      apiRequest<{ findings: ApiRiskFinding[] }>("/contracts/risk-analysis", {
        method: "POST",
        body: {},
        timeoutMs: 180_000,
      }),
    );
    return result.findings.map(toRiskFinding);
  },
};
