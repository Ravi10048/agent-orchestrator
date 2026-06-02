import { AlertTriangle, ArrowRight, Bot, Boxes, Building2, Info, PlayCircle, Wrench } from "lucide-react";
import { Suspense, lazy } from "react";
import { Link } from "react-router-dom";

import { ImpactPanel } from "@/components/ImpactPanel";
import { MetricStrip } from "@/components/dashboard/MetricStrip";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ListSkeleton } from "@/components/ui/feedback";
import { StatusBadge } from "@/components/ui/status";
import { useAgents, useConversations, useHealth, useRuns, useTemplates, useTenants, useTools } from "@/hooks/queries";
import { computeDashboardStats } from "@/lib/dashboardStats";
import { useTenant } from "@/lib/tenant";

// charts pull in recharts — keep it out of the initial bundle (Dashboard is the landing page)
const RunCharts = lazy(() => import("@/components/dashboard/RunCharts").then((m) => ({ default: m.RunCharts })));

function PrereqBanner() {
  const { data } = useHealth();
  if (!data) return null;
  if (!data.llm_key_present) {
    return (
      <Card className="mb-6 border-warning/40 bg-warning/5">
        <CardContent className="flex items-center gap-3 py-4">
          <AlertTriangle className="h-5 w-5 shrink-0 text-warning" />
          <div className="text-sm">
            <span className="font-medium">No LLM key detected.</span> Add{" "}
            <code className="font-mono">GROQ_API_KEY</code> to <code className="font-mono">.env</code> and restart to
            run agents. <span className="text-muted">(Free key at console.groq.com)</span>
          </div>
        </CardContent>
      </Card>
    );
  }
  if (!data.telegram_present) {
    return (
      <Card className="mb-6 border-info/40 bg-info/5">
        <CardContent className="flex items-center gap-3 py-4">
          <Info className="h-5 w-5 shrink-0 text-info" />
          <div className="text-sm">
            Set <code className="font-mono">TELEGRAM_BOT_TOKEN</code> to enable the Telegram channel (optional).
          </div>
        </CardContent>
      </Card>
    );
  }
  return null;
}

function TenantPill() {
  const tenants = useTenants();
  const { tenantId } = useTenant();
  const active = tenants.data?.find((t) => t.id === tenantId) ?? tenants.data?.find((t) => t.is_default);
  if (!active) return null;
  return (
    <Badge tone="primary">
      <Building2 className="h-3 w-3" /> {active.name}
    </Badge>
  );
}

function ChartsSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <Card key={i} className="h-[208px] animate-pulse p-4">
          <div className="mb-3 h-3 w-32 rounded bg-surface" />
          <div className="h-40 rounded bg-surface" />
        </Card>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const agents = useAgents();
  const tools = useTools();
  const templates = useTemplates();
  const runs = useRuns();
  const conversations = useConversations();

  const stats = computeDashboardStats(
    runs.data?.items ?? [],
    runs.data?.total ?? 0,
    conversations.data?.items ?? [],
    conversations.data?.total ?? 0,
  );

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Your local agent orchestration platform."
        actions={<TenantPill />}
      />
      <PrereqBanner />

      <Card className="mb-6 overflow-hidden border-primary/20 bg-gradient-to-br from-primary/15 via-card to-card">
        <CardContent className="flex flex-col gap-4 py-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Run a multi-agent workflow</h2>
            <p className="mt-1 max-w-md text-sm text-muted">
              Pick a ready-made template — agents collaborating on a real task — and watch it run live.
            </p>
          </div>
          <Link to="/templates">
            <Button>
              Browse templates <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Agents" value={agents.data?.total ?? "—"} icon={Bot} />
        <StatCard label="Tools" value={tools.data?.total ?? "—"} icon={Wrench} />
        <StatCard label="Templates" value={templates.data?.length ?? "—"} icon={Boxes} />
        <StatCard label="Runs" value={runs.data?.total ?? "—"} icon={PlayCircle} />
      </div>

      <div className="mt-4">
        <MetricStrip stats={stats} />
      </div>

      <div className="mt-6">
        {runs.isLoading ? (
          <ChartsSkeleton />
        ) : stats.sampledRuns > 0 ? (
          <Suspense fallback={<ChartsSkeleton />}>
            <RunCharts stats={stats} />
          </Suspense>
        ) : (
          <Card className="p-8 text-center">
            <p className="text-sm text-muted">
              No runs yet — start one from a template and the analytics charts will appear here.
            </p>
            <Link to="/templates" className="mt-3 inline-block">
              <Button variant="secondary">Browse templates</Button>
            </Link>
          </Card>
        )}
      </div>

      <ImpactPanel />

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          {runs.isLoading ? (
            <ListSkeleton rows={3} />
          ) : runs.data && runs.data.items.length > 0 ? (
            <ul className="divide-y divide-border">
              {runs.data.items.slice(0, 6).map((r) => (
                <li key={r.id} className="flex items-center justify-between py-2.5">
                  <Link to={`/runs?run=${r.id}`} className="text-sm font-medium hover:text-primary">
                    Run #{r.id} <span className="text-muted">· workflow {r.workflow_id}</span>
                  </Link>
                  <div className="flex items-center gap-3 text-xs text-muted">
                    <span className="tabular-nums">{r.total_tokens} tok</span>
                    <StatusBadge status={r.status} />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-muted">
              No runs yet — start one from a template (Templates tab).
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
