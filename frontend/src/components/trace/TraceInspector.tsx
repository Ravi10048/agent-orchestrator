import { ArrowRight, GitBranch, MousePointerClick, Wrench } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { AgentAvatar } from "@/components/ui/status";
import { fmtDuration, fmtTokens } from "@/lib/runFormat";
import type { NodeTrace, TraceStatus } from "@/lib/trace";

const TONE: Record<TraceStatus, "default" | "info" | "success" | "primary" | "destructive"> = {
  idle: "default",
  running: "info",
  done: "success",
  handoff: "primary",
  error: "destructive",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">{title}</div>
      {children}
    </div>
  );
}

/** Detail panel for a clicked node — the full reply, tools, decision, and meta. */
export function TraceInspector({ trace, nodeLabel }: { trace: NodeTrace | null; nodeLabel: string }) {
  if (!trace) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-muted">
        <MousePointerClick className="h-6 w-6" />
        <p className="text-sm font-medium text-fg">Click a node</p>
        <p className="text-xs">Inspect what each agent received, replied, and decided.</p>
      </div>
    );
  }

  if (!trace.ran) {
    return (
      <div className="p-5">
        <h3 className="text-sm font-semibold">{nodeLabel}</h3>
        <p className="mt-2 text-sm text-muted">This node was not reached in this run.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5 p-5">
      <div className="flex items-center gap-2.5">
        {trace.agentName && <AgentAvatar name={trace.agentName} className="h-8 w-8 text-[11px]" />}
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold">{trace.agentName || nodeLabel}</h3>
          {trace.model && <div className="truncate font-mono text-[10px] text-muted">{trace.model}</div>}
        </div>
        <Badge tone={TONE[trace.status]}>{trace.status}</Badge>
      </div>

      {trace.inputText && (
        <Section title="Input received">
          <p className="max-h-40 overflow-y-auto scroll-thin whitespace-pre-wrap rounded-md border border-border bg-surface/50 px-3 py-2 text-[13px] leading-relaxed text-fg/80">
            {trace.inputText}
          </p>
        </Section>
      )}

      {(trace.fullText || trace.preview) && (
        <Section title={trace.route ? "Reply to the user" : "Reply / output"}>
          <p className="max-h-72 overflow-y-auto scroll-thin whitespace-pre-wrap rounded-md border border-border bg-bg/60 px-3 py-2 text-[13px] leading-relaxed text-fg/90">
            {trace.fullText || trace.preview}
          </p>
        </Section>
      )}

      {(trace.route || trace.stoppedReason) && (
        <Section title={trace.route ? "Routing decision" : "Outcome"}>
          <div className="flex items-center gap-1.5 text-sm">
            {trace.route ? (
              <>
                <GitBranch className="h-3.5 w-3.5 text-primary" />
                <span className="text-muted">next agent</span>
                <ArrowRight className="h-3.5 w-3.5 text-primary" />
                <span className="font-medium text-primary">{trace.route}</span>
              </>
            ) : (
              <span>
                stopped: <span className="font-medium">{trace.stoppedReason}</span>
              </span>
            )}
          </div>
        </Section>
      )}

      {trace.tools.length > 0 && (
        <Section title="Tools used">
          <div className="space-y-1.5">
            {trace.tools.map((t, i) => (
              <div key={i} className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs">
                <Wrench className={`h-3.5 w-3.5 ${t.ok ? "text-info" : "text-destructive"}`} />
                <span className="font-medium">{t.tool}</span>
                <span className={t.ok ? "text-success" : "text-destructive"}>{t.ok ? "ok" : "failed"}</span>
                {t.latencyMs != null && <span className="ml-auto tabular-nums text-muted">{fmtDuration(t.latencyMs)}</span>}
                {!t.ok && t.error && <span className="w-full truncate text-destructive/80">{t.error}</span>}
              </div>
            ))}
          </div>
        </Section>
      )}

      {trace.error && (
        <Section title="Error">
          <p className="whitespace-pre-wrap rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">
            {trace.error}
          </p>
        </Section>
      )}

      <Section title="Metrics">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted">
          <span>{fmtTokens(trace.tokens)} tokens</span>
          {trace.durationMs != null && <span>{fmtDuration(trace.durationMs)}</span>}
          {trace.visits > 1 && <span className="text-warning">{trace.visits} visits</span>}
          {trace.step != null && <span>step {trace.step}</span>}
        </div>
      </Section>
    </div>
  );
}
