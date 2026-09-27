"use client";

import Link from "next/link";
import { AlertTriangle, ArrowRight, Building2, FileText, HardDrive, UsersRound } from "lucide-react";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useAsync } from "@/hooks/use-async";
import { PLANS, platformService } from "@/services/platform-service";
import { formatBytes } from "@/utils/format";

export function PlatformOverviewView() {
  const { data, error, reload } = useAsync(() => platformService.overview(), []);

  return (
    <>
      <PageHeader eyebrow="Platform" title="Overview" description="Every organization on DocuNexa AI at a glance." />
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat icon={Building2} label="Organizations" value={data.organizations.toLocaleString()} note={`${data.active_organizations} active · ${data.suspended_organizations} suspended`} />
            <Stat icon={UsersRound} label="Users" value={data.users.toLocaleString()} note={`${data.active_users.toLocaleString()} active`} />
            <Stat icon={FileText} label="Documents" value={data.documents.toLocaleString()} note={`${data.failed_documents_24h} failed in 24 h`} warn={data.failed_documents_24h > 0} />
            <Stat icon={HardDrive} label="Storage" value={formatBytes(data.storage_bytes)} note={`${data.new_organizations_30d} new organizations in 30 days`} />
          </div>
          <Card>
            <CardHeader
              title="Organizations by plan"
              action={
                <Link href="/platform/organizations" className="inline-flex items-center gap-1 text-[13px] font-medium text-brand">
                  All organizations <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              }
            />
            <div className="grid gap-4 p-5 sm:grid-cols-4">
              {PLANS.map((plan) => {
                const count = data.organizations_by_plan[plan] ?? 0;
                const share = data.organizations ? (count / data.organizations) * 100 : 0;
                return (
                  <Link key={plan} href={`/platform/organizations?plan=${plan}`} className="rounded-xl border border-line p-4 transition hover:border-line-strong">
                    <p className="text-2xs font-semibold uppercase tracking-[0.08em] text-ink-3">{plan}</p>
                    <p className="num mt-1 text-[24px] font-semibold text-ink">{count}</p>
                    <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-sunken">
                      <span className="block h-full bg-brand" style={{ width: `${share}%` }} />
                    </span>
                  </Link>
                );
              })}
            </div>
          </Card>
        </div>
      )}
    </>
  );
}

function Stat({ icon: Icon, label, value, note, warn }: { icon: typeof Building2; label: string; value: string; note: string; warn?: boolean }) {
  return (
    <Card className="p-5">
      <p className="flex items-center gap-2 text-[13px] text-ink-2">
        <Icon className="h-4 w-4 text-ink-3" /> {label}
      </p>
      <p className="num mt-2 text-[28px] font-semibold leading-none text-ink">{value}</p>
      <p className={warn ? "mt-2 flex items-center gap-1 text-2xs text-warn" : "mt-2 text-2xs text-ink-3"}>
        {warn && <AlertTriangle className="h-3 w-3" />} {note}
      </p>
    </Card>
  );
}
