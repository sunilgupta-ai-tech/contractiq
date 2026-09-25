"use client";

import { Skeleton, ErrorState } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { useAsync } from "@/hooks/use-async";
import { analysisService } from "@/services/analysis-service";
import { documentService } from "@/services/document-service";
import { AskPanel } from "./ask-panel";
import { KeyDates } from "./key-dates";
import { KpiRow, computeKpis } from "./kpi-row";
import { ProcessingQueue } from "./processing-queue";
import { RiskExposure } from "./risk-exposure";

function greeting(hour = new Date().getHours()) {
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

export function DashboardView() {
  const { data, error, loading, reload } = useAsync(
    () => Promise.all([documentService.list(), analysisService.riskFindings(), documentService.keyDates()]),
    [],
  );

  return (
    <>
      <PageHeader
        eyebrow="Acme Legal · Overview"
        title={`${greeting()}, Sunil`}
        description="Portfolio health across your contracts: what's being processed, what's risky, and which deadlines are close."
      />
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading || !data ? (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[132px] rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="space-y-5">
          <KpiRow kpis={computeKpis(data[0], data[1], data[2])} />
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-5">
              <AskPanel />
              <ProcessingQueue docs={data[0]} />
            </div>
            <div className="min-w-0 space-y-5">
              <KeyDates dates={data[2]} />
              <RiskExposure findings={data[1]} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
