import { PlayCircle, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/ui/feedback";
import { StatusBadge } from "@/components/ui/status";
import { useRuns, useWorkflows } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { fmtAgo, fmtCost, fmtTokens, isActive } from "@/lib/runFormat";

export default function RunsPage() {
  const { data, isLoading, isError, refetch, isFetching } = useRuns();
  const workflows = useWorkflows();
  const navigate = useNavigate();

  const wfName = useMemo(() => {
    const m = new Map<number, string>();
    workflows.data?.items.forEach((w) => m.set(w.id, w.name));
    return m;
  }, [workflows.data]);

  // open the run's GRAPH directly (the node/edge decision-tree view); the graph header has a
  // "Timeline" button for the event log.
  const open = (id: number) => navigate(`/runs/${id}/graph`);

  return (
    <>
      <PageHeader
        title="Runs"
        subtitle="Every workflow execution — click any run to open its graph (node/edge flow)."
        actions={
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} /> Refresh
          </Button>
        }
      />

      {isLoading ? (
        <ListSkeleton rows={5} />
      ) : isError ? (
        <ErrorState message="Couldn't load runs." onRetry={refetch} />
      ) : data && data.items.length > 0 ? (
        <Card className="overflow-hidden">
          <div className="grid grid-cols-[auto_1fr_auto_auto_auto] items-center gap-x-4 border-b border-border px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted/70 sm:grid-cols-[auto_1fr_auto_auto_auto_auto]">
            <span>Run</span>
            <span>Workflow</span>
            <span className="hidden text-right sm:block">Trigger</span>
            <span className="text-right tabular-nums">Tokens</span>
            <span className="text-right tabular-nums">Cost</span>
            <span className="text-right">Status</span>
          </div>
          <ul className="divide-y divide-border">
            {data.items.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => open(r.id)}
                  className="grid w-full grid-cols-[auto_1fr_auto_auto_auto] items-center gap-x-4 px-4 py-3 text-left transition hover:bg-surface sm:grid-cols-[auto_1fr_auto_auto_auto_auto]"
                >
                  <span className="flex items-center gap-2 font-mono text-sm font-medium">
                    #{r.id}
                    {isActive(r.status) && (
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-info" title="active" />
                    )}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">
                      {wfName.get(r.workflow_id) ?? `workflow ${r.workflow_id}`}
                    </span>
                    <span className="block text-xs text-muted">{fmtAgo(r.started_at)}</span>
                  </span>
                  <span className="hidden text-right text-xs text-muted sm:block">{r.trigger}</span>
                  <span className="text-right text-sm tabular-nums">{fmtTokens(r.total_tokens)}</span>
                  <span className="text-right text-sm tabular-nums text-muted">{fmtCost(r.est_cost)}</span>
                  <span className="flex justify-end">
                    <StatusBadge status={r.status} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <EmptyState
          title="No runs yet"
          hint="Start one from a template or the workflow builder — then watch it run live here."
          action={
            <Button onClick={() => (window.location.href = "/templates")}>
              <PlayCircle className="h-4 w-4" /> Browse templates
            </Button>
          }
        />
      )}
    </>
  );
}
