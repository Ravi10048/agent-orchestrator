import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ListTree, MessagesSquare, Workflow as WorkflowIcon, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import type { ApiError } from "@/api/client";
import { AgentThread } from "@/components/monitor/AgentThread";
import { Timeline } from "@/components/monitor/Timeline";
import { TokenMeter } from "@/components/monitor/TokenMeter";
import { Button } from "@/components/ui/button";
import { ConnectionDot, StatusBadge } from "@/components/ui/status";
import { useRun, useRunMutations, useWorkflow } from "@/hooks/queries";
import { useMonitorSocket } from "@/hooks/useMonitorSocket";
import { cn } from "@/lib/cn";
import { deriveStatus, isActive } from "@/lib/runFormat";
import { toast } from "@/lib/toast";

type Tab = "timeline" | "agents" | "tokens";

/** Global live-run monitor. Mounted once; opens whenever `?run=<id>` is in the URL.
 *  Drives off useMonitorSocket (subscribe → backfill → live) — works for live AND finished runs. */
export function RunDrawer() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const raw = params.get("run");
  const runId = raw && /^\d+$/.test(raw) ? Number(raw) : null;

  const { data: run, isError: runError } = useRun(runId ?? 0);
  const { data: workflow } = useWorkflow(run?.workflow_id ?? 0);
  const { status: socket, events } = useMonitorSocket(runId);
  const { cancel } = useRunMutations();
  const qc = useQueryClient();

  const [tab, setTab] = useState<Tab>("timeline");
  const finishedRef = useRef(false);
  const panelRef = useRef<HTMLElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);

  const liveStatus = deriveStatus(events, run?.status ?? "pending");
  // a stale/deleted ?run= 404s the REST record AND the WS backfill is empty → show a real error, not a fake "pending"
  const notFound = runError && events.length === 0;
  const active = isActive(liveStatus) && !notFound;
  const agentMsgCount = events.filter((e) => e.type === "agent_message").length;

  const close = () => {
    const next = new URLSearchParams(params);
    next.delete("run");
    setParams(next, { replace: true });
  };

  // when the run completes over the socket, refresh the REST caches (lists, the run record)
  useEffect(() => {
    finishedRef.current = false;
  }, [runId]);
  useEffect(() => {
    if (runId && !active && !finishedRef.current && events.some((e) => e.type === "run_finished")) {
      finishedRef.current = true;
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["run", runId] });
    }
  }, [runId, active, events, qc]);

  // focus management + keyboard: move focus into the dialog on open, restore on close,
  // Esc closes, and Tab is trapped inside the panel (a11y for keyboard/SR users)
  useEffect(() => {
    if (!runId) return;
    const panel = panelRef.current;
    restoreFocus.current = document.activeElement as HTMLElement | null;
    panel?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") return close();
      if (e.key !== "Tab" || !panel) return;
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreFocus.current?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  if (!runId) return null;

  const onCancel = async () => {
    try {
      await cancel.mutateAsync(runId);
      toast.info(`Cancelling run #${runId}…`);
    } catch (e) {
      toast.error((e as ApiError).message ?? "Couldn't cancel run");
    }
  };

  const TABS: { key: Tab; label: string; icon: typeof ListTree; count?: number }[] = [
    { key: "timeline", label: "Timeline", icon: ListTree, count: events.length },
    { key: "agents", label: "Agents", icon: MessagesSquare, count: agentMsgCount },
    { key: "tokens", label: "Tokens", icon: ListTree },
  ];

  return (
    <div className="fixed inset-0 z-[80]">
      <div className="absolute inset-0 bg-black/55 backdrop-blur-sm animate-fade-in" onClick={close} />
      <aside
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal
        aria-label={`Run ${runId} monitor`}
        className="absolute inset-y-0 right-0 flex w-full max-w-[640px] flex-col border-l border-border bg-bg shadow-pop outline-none animate-fade-in"
      >
        {/* header */}
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold tracking-tight">Run #{runId}</h2>
              <StatusBadge status={liveStatus} />
              {active && liveStatus === "running" && (
                <span className="relative flex h-2 w-2" title="live">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-info opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-info" />
                </span>
              )}
            </div>
            <p className="mt-0.5 truncate text-sm text-muted">
              {workflow ? (
                <Link to={`/workflows/${workflow.id}/build`} className="hover:text-primary hover:underline">
                  {workflow.name}
                </Link>
              ) : (
                <>workflow {run?.workflow_id ?? "…"}</>
              )}
              {run?.trigger && <span> · {run.trigger}</span>}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {active && <ConnectionDot status={socket} />}
            {!notFound && (
              <Button variant="outline" size="sm" onClick={() => navigate(`/runs/${runId}/graph`)} title="See the run on the workflow graph">
                <WorkflowIcon className="h-4 w-4" /> Graph
              </Button>
            )}
            {active && (
              <Button variant="destructive" size="sm" onClick={onCancel} disabled={cancel.isPending}>
                Cancel
              </Button>
            )}
            <button
              onClick={close}
              aria-label="Close"
              className="rounded-md p-1.5 text-muted transition hover:bg-surface hover:text-fg"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        {/* tabs */}
        {!notFound && (
          <div role="tablist" aria-label="Run monitor views" className="flex gap-1 border-b border-border px-3">
            {TABS.map(({ key, label, icon: Icon, count }) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn(
                  "relative flex items-center gap-1.5 rounded-md px-3 py-2.5 text-sm font-medium transition",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]",
                  tab === key ? "text-fg" : "text-muted hover:text-fg",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
                {count != null && count > 0 && (
                  <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] tabular-nums text-muted">{count}</span>
                )}
                {tab === key && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />}
              </button>
            ))}
          </div>
        )}

        {/* body */}
        <div className="flex-1 overflow-y-auto scroll-thin px-5 py-4">
          {notFound ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <AlertTriangle className="h-7 w-7 text-warning" />
              <div>
                <p className="font-medium">Run #{runId} not found</p>
                <p className="mt-1 text-sm text-muted">It may have been deleted, or this link is stale.</p>
              </div>
              <Button variant="outline" size="sm" onClick={close}>
                Close
              </Button>
            </div>
          ) : (
            <>
              {tab === "timeline" && <Timeline events={events} />}
              {tab === "agents" && <AgentThread events={events} />}
              {tab === "tokens" && <TokenMeter events={events} run={run} />}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
