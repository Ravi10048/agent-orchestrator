import {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { User, Wrench } from "lucide-react";

import type { Message } from "@/api/types";
import { AgentAvatar } from "@/components/ui/status";
import { agentHue, cn } from "@/lib/cn";
import { useTheme } from "@/lib/theme";

interface ToolUse {
  tool: string;
  ok: boolean;
}
interface TurnData {
  content: string;
  agentName: string;
  tools: ToolUse[];
  [key: string]: unknown;
}

function UserTurn({ data }: NodeProps) {
  const d = data as TurnData;
  return (
    <div className="w-[260px] rounded-xl border border-primary/40 bg-primary/10 px-3 py-2 shadow-soft">
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-transparent" />
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-primary">
        <User className="h-3 w-3" /> User
      </div>
      <p className="line-clamp-5 whitespace-pre-wrap text-[12px] leading-snug text-fg/90">{d.content}</p>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-2 !border-bg !bg-primary" />
    </div>
  );
}

function AgentTurn({ data }: NodeProps) {
  const d = data as TurnData;
  const hue = agentHue(d.agentName);
  return (
    <div
      className="w-[260px] rounded-xl border border-border bg-card px-3 py-2 shadow-soft"
      style={{ borderLeft: `3px solid hsl(${hue} 60% 55%)` }}
    >
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-2 !border-bg !bg-muted" />
      <div className="mb-1 flex items-center gap-1.5">
        <AgentAvatar name={d.agentName} className="h-4 w-4 text-[8px]" />
        <span className="text-[11px] font-semibold">{d.agentName}</span>
      </div>
      <p className="line-clamp-5 whitespace-pre-wrap text-[12px] leading-snug text-fg/85">{d.content}</p>
      {d.tools.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {d.tools.map((t, i) => (
            <span
              key={i}
              className={cn(
                "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium",
                t.ok ? "bg-info/10 text-info" : "bg-destructive/10 text-destructive",
              )}
            >
              <Wrench className="h-2.5 w-2.5" />
              {t.tool}
              {!t.ok && " ✕"}
            </span>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-transparent" />
    </div>
  );
}

const nodeTypes = { userTurn: UserTurn, agentTurn: AgentTurn };

/** A multi-turn conversation rendered as a vertical turn-DAG (same trace aesthetic): each turn is
 *  a node, agent turns show the tools they invoked, edges show the flow. Lazy-loaded (pulls React Flow). */
export default function ConversationFlow({ messages, agentName }: { messages: Message[]; agentName: string }) {
  const { theme } = useTheme();

  // a routed chat persists each reply under its specialist (from_agent) → each node shows its true
  // author + color, so the Flow view reflects the per-turn routing (fall back to the conv's agent).
  const authorOf = (m: Message) =>
    m.from_agent && m.from_agent !== "user" && m.from_agent !== "system" ? m.from_agent : agentName;

  const nodes: Node[] = messages.map((m, i) => ({
    id: `m${m.id}`,
    type: m.role === "user" ? "userTurn" : "agentTurn",
    position: { x: m.role === "user" ? 0 : 48, y: i * 168 },
    data: {
      content: m.content,
      agentName: authorOf(m),
      tools: Array.isArray(m.tool_calls) ? (m.tool_calls as ToolUse[]) : [],
    } satisfies TurnData,
  }));

  const edges: Edge[] = messages.slice(1).map((m, i) => ({
    id: `ce${i}`,
    source: `m${messages[i].id}`,
    target: `m${m.id}`,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(var(--border-strong))" },
    style: { stroke: "hsl(var(--border-strong))", strokeWidth: 2 },
  }));

  return (
    <div className="h-[58vh]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        colorMode={theme}
        nodesConnectable={false}
        edgesFocusable={false}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
