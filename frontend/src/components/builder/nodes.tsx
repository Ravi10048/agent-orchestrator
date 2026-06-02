import { Handle, type NodeProps, Position } from "@xyflow/react";
import { Bot, Flag, GitBranch, Play, Wrench } from "lucide-react";
import { type ReactNode } from "react";

import type { NodeData } from "@/lib/graphCodec";
import { cn } from "@/lib/cn";

/** A builder node rendered as a compact CIRCLE (matches the run-graph decision-tree view): a
 *  status/type-colored ring, an icon, and a name label below. Top/bottom handles for connecting. */
function Chrome({
  selected,
  ring,
  accent,
  icon,
  title,
  subtitle,
  inHandle = true,
  outHandle = true,
}: {
  selected?: boolean;
  ring: string;
  accent: string;
  icon: ReactNode;
  title: string;
  subtitle?: string;
  inHandle?: boolean;
  outHandle?: boolean;
}) {
  return (
    <div className="relative h-16 w-16">
      {inHandle && (
        <Handle type="target" position={Position.Top} className="!h-2.5 !w-2.5 !border-2 !border-bg !bg-muted" />
      )}

      <div
        className={cn(
          "grid h-16 w-16 place-items-center rounded-full border-2 bg-card shadow-soft transition",
          ring,
          selected && "!border-primary ring-4 ring-primary/40",
        )}
      >
        <span className={cn("grid h-10 w-10 place-items-center rounded-full", accent)}>{icon}</span>
      </div>

      {outHandle && (
        <Handle type="source" position={Position.Bottom} className="!h-2.5 !w-2.5 !border-2 !border-bg !bg-primary" />
      )}

      {/* label below the circle (absolute → keeps the circle's handle anchors; bg masks the edge) */}
      <div className="pointer-events-none absolute left-1/2 top-[calc(100%+5px)] flex w-40 -translate-x-1/2 flex-col items-center gap-0.5">
        <div className="inline-flex max-w-full items-center rounded-md bg-bg/90 px-1.5 py-0.5 backdrop-blur-sm">
          <span className="truncate text-[13px] font-semibold">{title}</span>
        </div>
        {subtitle && (
          <div className="max-w-full truncate rounded bg-bg/80 px-1 font-mono text-[10px] text-muted">{subtitle}</div>
        )}
      </div>
    </div>
  );
}

export function StartNode({ selected }: NodeProps) {
  return (
    <Chrome
      selected={selected}
      inHandle={false}
      ring="border-success/60"
      accent="bg-success/15 text-success"
      icon={<Play className="h-5 w-5" />}
      title="Start"
    />
  );
}

export function EndNode({ selected }: NodeProps) {
  return (
    <Chrome
      selected={selected}
      outHandle={false}
      ring="border-destructive/50"
      accent="bg-destructive/15 text-destructive"
      icon={<Flag className="h-5 w-5" />}
      title="End"
    />
  );
}

export function AgentNode({ data, selected }: NodeProps) {
  const d = data as NodeData;
  return (
    <Chrome
      selected={selected}
      ring="border-primary/50"
      accent="bg-primary/15 text-primary"
      icon={<Bot className="h-5 w-5" />}
      title={d.agentName || "(pick agent)"}
      subtitle={d.model}
    />
  );
}

export function ToolNode({ data, selected }: NodeProps) {
  const d = data as NodeData;
  return (
    <Chrome
      selected={selected}
      ring="border-info/50"
      accent="bg-info/15 text-info"
      icon={<Wrench className="h-5 w-5" />}
      title={d.toolName || "(pick tool)"}
    />
  );
}

export function RouterNode({ selected }: NodeProps) {
  return (
    <Chrome
      selected={selected}
      ring="border-warning/50"
      accent="bg-warning/15 text-warning"
      icon={<GitBranch className="h-5 w-5" />}
      title="Router"
    />
  );
}

export const nodeTypes = {
  start: StartNode,
  end: EndNode,
  agent: AgentNode,
  tool: ToolNode,
  router: RouterNode,
};
