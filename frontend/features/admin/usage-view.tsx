"use client";

import { Bot, FileText, HardDrive, Hash, UsersRound } from "lucide-react";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { UsageBar } from "@/features/platform/usage-bar";
import { useAsync } from "@/hooks/use-async";
import { adminService, tokensOf } from "@/services/admin-service";
import { formatBytes } from "@/utils/format";

const compact = (n: number) => new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);

/** Phase 22: what the organization uses against its plan. */
export function UsageView() {
  const { data, error, reload } = useAsync(() => adminService.usage(), []);
  const month = data?.months[0];

  return (
    <>
      <PageHeader eyebrow="Organization" title="Usage" description="Storage, documents, people and AI usage against your plan. AI usage resets on the 1st of each month (UTC)." />
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data || !month ? (
        !error && <Skeleton className="h-64 rounded-xl" />
      ) : (
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <Tile icon={Bot} label="AI questions this month">
              <UsageBar used={month.queries} max={data.limits.max_ai_queries_month} />
            </Tile>
            <Tile icon={Hash} label="AI tokens this month">
              <UsageBar used={tokensOf(month)} max={data.limits.max_ai_tokens_month} format={compact} />
            </Tile>
            <Tile icon={HardDrive} label="Storage">
              <UsageBar
                used={data.current.storage_bytes}
                max={data.limits.max_storage_mb === null ? null : data.limits.max_storage_mb * 1024 * 1024}
                format={formatBytes}
              />
            </Tile>
            <Tile icon={FileText} label="Documents">
              <UsageBar used={data.current.documents} max={data.limits.max_documents} />
            </Tile>
            <Tile icon={UsersRound} label="Active users">
              <UsageBar used={data.current.active_users} max={data.limits.max_users} />
            </Tile>
          </div>
          <Card>
            <CardHeader title={`Plan: ${data.plan}`} eyebrow="By month" />
            <div className="overflow-x-auto scroll-thin">
              <table className="w-full min-w-[640px] text-left">
                <thead>
                  <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">
                    <th className="px-5 py-3">Month</th>
                    <th className="px-3 py-3 text-right">Questions</th>
                    <th className="px-3 py-3 text-right">Model calls</th>
                    <th className="px-3 py-3 text-right">Input tokens</th>
                    <th className="px-3 py-3 text-right">Output tokens</th>
                    <th className="px-5 py-3 text-right">Embedding tokens</th>
                  </tr>
                </thead>
                <tbody className="num divide-y divide-line text-[13px] text-ink-2">
                  {data.months.map((m) => (
                    <tr key={m.period}>
                      <td className="px-5 py-2.5 font-medium text-ink">{m.period}</td>
                      <td className="px-3 py-2.5 text-right">{m.queries.toLocaleString()}</td>
                      <td className="px-3 py-2.5 text-right">{m.model_calls.toLocaleString()}</td>
                      <td className="px-3 py-2.5 text-right">{m.prompt_tokens.toLocaleString()}</td>
                      <td className="px-3 py-2.5 text-right">{m.completion_tokens.toLocaleString()}</td>
                      <td className="px-5 py-2.5 text-right">{m.embedding_tokens.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}

function Tile({ icon: Icon, label, children }: { icon: typeof Bot; label: string; children: React.ReactNode }) {
  return (
    <Card className="p-5">
      <p className="mb-3 flex items-center gap-2 text-[13px] text-ink-2">
        <Icon className="h-4 w-4 text-ink-3" /> {label}
      </p>
      {children}
    </Card>
  );
}
