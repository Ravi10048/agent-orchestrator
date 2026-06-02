import { Handle, type NodeProps, Position } from "@xyflow/react";
import { AlertTriangle, Bot, CheckCircle2, Flag, GitBranch, Loader2, Play, Wrench } from "lucide-react";

import { agentHue, cn } from "@/lib/cn";
import type { NodeData } from "@/lib/graphCodec";
import { fmtDuration, fmtTokens } from "@/lib/runFormat";
import type { NodeTrace, TraceStatus } from "@/lib/trace";

const ICONS = { start: Play, end: Flag, agent: Bot, tool: Wrench, router: GitBranch } as const;

// the circle's border ring, by execution status
const RING: Record<TraceStatus, string> = {
  idle: "border-border-strong",
  running: "border-info ring-4 ring-info/20",
  done: "border-success/70 ring-4 ring-success/15",
  handoff: "border-primary ring-4 ring-primary/20",
  error: "border-destructive ring-4 ring-destructive/20",
};

// the inner icon-badge tint, by status
const ACCENT: Record<TraceStatus, string> = {
  idle: "bg-surface text-muted",
  running: "bg-info/15 text-info",
  done: "bg-success/15 text-success",
  handoff: "bg-primary/15 text-primary",
  error: "bg-destructive/15 text-destructive",
};

/** A workflow node rendered as a compact CIRCLE (decision-tree style) with its execution trace —
 *  status ring, the routing decision, tokens, and tool chips. Click it for the full inspector. */
export function TraceNode({ type, data, selected }: NodeProps) {
  const d = data as NodeData & { trace?: NodeTrace };
  const t = d.trace;
  const kind = (type ?? "agent") as keyof typeof ICONS;
  const Icon = ICONS[kind] ?? Bot;
  const status: TraceStatus = t?.status ?? "idle";
  const title = d.agentName || d.toolName || kind.charAt(0).toUpperCase() + kind.slice(1);

  return (
    <div className={cn("relative h-16 w-16", !t?.ran && "opacity-40")}>
      {/* live cockpit: a radar ping behind the node the workflow is currently focused on */}
      {t?.spotlight && (
        <>
          <span className="pointer-events-none absolute -inset-1 animate-ping rounded-full bg-primary/25" />
          <span className="pointer-events-none absolute -inset-1 rounded-full ring-2 ring-primary/40" />
        </>
      )}
      {kind !== "start" && (
        <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-2 !border-bg !bg-muted" />
      )}

      {/* the circular node */}
      <div
        className={cn(
          "relative grid h-16 w-16 place-items-center rounded-full border-2 bg-card shadow-soft transition",
          RING[status],
          selected && "!border-primary ring-4 ring-primary/40",
        )}
      >
        <span className={cn("grid h-10 w-10 place-items-center rounded-full", ACCENT[status])}>
          <Icon className="h-5 w-5" />
        </span>
        {t?.ran && (
          <span className="absolute -bottom-1 -right-1 grid h-5 w-5 place-items-center rounded-full border border-border bg-card">
            {status === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin text-info" />}
            {status === "done" && <CheckCircle2 className="h-3.5 w-3.5 text-success" />}
            {status === "handoff" && <GitBranch className="h-3.5 w-3.5 text-primary" />}
            {status === "error" && <AlertTriangle className="h-3.5 w-3.5 text-destructive" />}
          </span>
        )}
        {t && t.visits > 1 && (
          <span
            className="absolute -left-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full border border-border bg-warning/15 px-1 text-[10px] font-semibold text-warning"
            title={`${t.visits} visits (looped)`}
          >
            ×{t.visits}
          </span>
        )}
      </div>

      {kind !== "end" && (
        <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-2 !border-bg !bg-primary" />
      )}

      {/* label below the circle — absolutely positioned so it doesn't move the edge anchors; its
          solid background masks the edge passing behind it (keeps the tree clean). */}
      <div className="pointer-events-none absolute left-1/2 top-[calc(100%+5px)] flex w-44 -translate-x-1/2 flex-col items-center gap-1">
        <div className="inline-flex max-w-full items-center gap-1 rounded-md bg-bg/90 px-1.5 py-0.5 backdrop-blur-sm">
          {d.agentName && (
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: `hsl(${agentHue(d.agentName)} 60% 55%)` }}
            />
          )}
          <span className="truncate text-[13px] font-semibold">{title}</span>
        </div>

        {t?.route ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
            <GitBranch className="h-2.5 w-2.5" /> routes to {t.route}
          </span>
        ) : t?.ran && (t.tokens > 0 || t.durationMs != null) ? (
          <div className="rounded bg-bg/80 px-1 text-[10px] tabular-nums text-muted">
            {t.tokens > 0 && `${fmtTokens(t.tokens)} tok`}
            {t.durationMs != null && ` · ${fmtDuration(t.durationMs)}`}
          </div>
        ) : null}

        {t && t.tools.length > 0 && (
          <div className="flex max-w-full flex-wrap justify-center gap-1">
            {t.tools.map((tl, i) => (
              <span
                key={i}
                title={tl.error ?? tl.tool}
                className={cn(
                  "inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] font-medium",
                  tl.ok ? "bg-info/10 text-info" : "bg-destructive/10 text-destructive",
                )}
              >
                <Wrench className="h-2 w-2" />
                {tl.tool}
                {!tl.ok && " ✕"}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export const traceNodeTypes = { start: TraceNode, end: TraceNode, agent: TraceNode, tool: TraceNode, router: TraceNode };
