"use client";

import { useState } from "react";
import { Boxes, Cpu, Database, HardDrive, Layers, MonitorSmartphone, RefreshCw, Server, Zap, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { useAsync } from "@/hooks/use-async";
import { useInterval } from "@/hooks/use-interval";
import { config } from "@/lib/config";
import { healthService } from "@/services/health-service";
import type { DependencyHealth } from "@/types";
import { cn } from "@/utils/cn";

const SERVICES: { name: string; label: string; role: string; prod: string; icon: LucideIcon }[] = [
  { name: "postgres", label: "PostgreSQL", role: "Users, orgs, documents, versions, jobs, audit", prod: "AWS RDS", icon: Database },
  { name: "redis", label: "Redis", role: "Cache, rate limits, job queue", prod: "ElastiCache", icon: Zap },
  { name: "qdrant", label: "Qdrant", role: "Dense + sparse vectors, tenant-indexed", prod: "Qdrant Cloud / self-hosted", icon: Boxes },
];

function Dot({ state }: { state: "up" | "down" | "unknown" }) {
  return (
    <span className="relative flex h-2.5 w-2.5">
      {state === "up" && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ok opacity-40" />}
      <span className={cn("relative inline-flex h-2.5 w-2.5 rounded-full", state === "up" ? "bg-ok" : state === "down" ? "bg-danger" : "bg-ink-3")} />
    </span>
  );
}

export function SystemView() {
  const live = useAsync(() => healthService.liveness(), []);
  const ready = useAsync(() => healthService.readiness(), []);
  const [checkedAt, setCheckedAt] = useState(() => new Date());
  const refresh = () => {
    live.reload();
    ready.reload();
    setCheckedAt(new Date());
  };
  useInterval(refresh, 10_000);

  const apiUp = !!live.data;
  const dep = (name: string): DependencyHealth | undefined => ready.data?.dependencies.find((d) => d.name === name);
  const overall = !apiUp ? "unreachable" : ready.data?.status ?? "checking";
  const overallTone = overall === "ready" ? "bg-ok-soft text-ok" : overall === "degraded" ? "bg-warn-soft text-warn" : overall === "checking" ? "bg-sunken text-ink-3" : "bg-danger-soft text-danger";

  return (
    <>
      <PageHeader
        eyebrow="Platform"
        title="System health"
        description="Live readiness of every service in the stack. This page always talks to the real backend, never demo data."
        actions={<Button variant="secondary" onClick={refresh}><RefreshCw className={cn("h-4 w-4", (live.loading || ready.loading) && "animate-spin")} /> Refresh</Button>}
      />

      <Card className="mb-5 flex flex-wrap items-center gap-4 p-5">
        <span className={cn("rounded-lg px-3 py-1.5 text-[13px] font-semibold uppercase tracking-[0.06em]", overallTone)}>{overall.replace("_", " ")}</span>
        <div className="text-[13px] text-ink-2">
          {apiUp ? (
            <>
              <span className="font-medium text-ink">{live.data!.service} API</span> v{live.data!.version} · environment{" "}
              <span className="font-mono">{live.data!.environment}</span>
            </>
          ) : (
            <>
              Cannot reach <span className="font-mono">{config.apiBaseUrl}</span>. Start the stack with <span className="font-mono">make up</span>.
            </>
          )}
        </div>
        <span className="num ml-auto text-2xs text-ink-3">Checked {checkedAt.toLocaleTimeString()} · auto-refresh 10s</span>
      </Card>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {[
          { label: "Frontend", role: "Next.js · this app", prod: "ECS / Vercel", icon: MonitorSmartphone, state: "up" as const, latency: null },
          { label: "Backend API", role: "FastAPI · /api/v1", prod: "ECS behind ALB", icon: Server, state: apiUp ? ("up" as const) : live.loading ? ("unknown" as const) : ("down" as const), latency: null },
          { label: "Worker", role: "arq · ingestion pipeline", prod: "ECS, scales on queue depth", icon: Cpu, state: dep("worker")?.status ?? ("unknown" as const), latency: null, error: dep("worker")?.error },
          ...SERVICES.map((s) => {
            const d = dep(s.name);
            return { ...s, state: d ? d.status : ("unknown" as const), latency: d?.latency_ms ?? null, error: d?.error };
          }),
        ].map((s) => (
          <Card key={s.label} className="p-5">
            <div className="flex items-start justify-between">
              <span className="grid h-10 w-10 place-items-center rounded-xl border border-line bg-sunken text-ink-2">
                <s.icon className="h-5 w-5" />
              </span>
              <span className="flex items-center gap-2 text-2xs font-semibold uppercase tracking-[0.06em] text-ink-3">
                <Dot state={s.state} /> {s.state === "unknown" ? "n/a" : s.state}
              </span>
            </div>
            <p className="mt-4 font-medium text-ink">{s.label}</p>
            <p className="mt-0.5 text-[13px] text-ink-2">{s.role}</p>
            <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-2xs text-ink-3">
              <span>Prod: {s.prod}</span>
              {s.latency !== null && <span className="num font-mono">{s.latency.toFixed(1)} ms</span>}
              {"error" in s && s.error && <span className="font-mono text-danger">{s.error}</span>}
            </div>
          </Card>
        ))}
      </div>

      <Card className="mt-5">
        <CardHeader eyebrow="Architecture" title="Request and ingestion flows" action={<Layers className="h-4 w-4 text-ink-3" />} />
        <div className="grid gap-6 p-5 lg:grid-cols-2">
          {[
            { title: "Document flow (async)", steps: ["Upload", "Object storage", "Queue", "Worker", "Parse · OCR", "Clause chunking", "Embeddings", "Qdrant"] },
            { title: "Query flow (low latency)", steps: ["Question", "Auth + tenant", "LangGraph", "Hybrid search", "Rerank", "LLM", "Evidence check", "Cited answer"] },
          ].map((flow) => (
            <div key={flow.title}>
              <p className="mb-3 text-[13px] font-medium text-ink">{flow.title}</p>
              <ol className="flex flex-wrap items-center gap-1.5">
                {flow.steps.map((step, i) => (
                  <li key={step} className="flex items-center gap-1.5">
                    <span className="rounded-md border border-line bg-sunken px-2 py-1 text-2xs font-medium text-ink-2">{step}</span>
                    {i < flow.steps.length - 1 && <span className="text-ink-3">→</span>}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2 border-t border-line px-5 py-3 text-2xs text-ink-3">
          <HardDrive className="h-3.5 w-3.5" /> Local: Docker Compose · Production: same images on AWS, configured only through environment variables.
        </div>
      </Card>
    </>
  );
}
