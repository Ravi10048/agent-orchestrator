import {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  MarkerType,
  MiniMap,
  type Node,
  Panel,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowLeft, Loader2, Split, Wrench } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ChatSession, type ChatTurnInfo } from "@/components/ChatBench";
import { traceNodeTypes } from "@/components/trace/TraceNode";
import { Button } from "@/components/ui/button";
import { ErrorState, Spinner } from "@/components/ui/feedback";
import { AgentAvatar } from "@/components/ui/status";
import { pulseEdgeTypes } from "@/components/workflow-chat/PulseEdge";
import { useAgents, useTools, useWorkflow } from "@/hooks/queries";
import { buildChatTrace } from "@/lib/chatTrace";
import { agentHue, cn } from "@/lib/cn";
import { type NodeData, toFlow } from "@/lib/graphCodec";
import { fmtTokens } from "@/lib/runFormat";
import { useTheme } from "@/lib/theme";
import { layoutTrace } from "@/lib/trace";

const EMPTY_GRAPH = { nodes: [], edges: [] };

/** A small radar-ping status dot. */
function PulseDot() {
  return (
    <span className="relative flex h-2 w-2">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
    </span>
  );
}

/** Pans/zooms the canvas to keep the currently-focused node centered as routing moves. Lives INSIDE
 *  <ReactFlow> so it has the flow instance context. */
function CameraFollow({ targetId, nodes }: { targetId?: string; nodes: Node[] }) {
  const rf = useReactFlow();
  useEffect(() => {
    if (!targetId) return;
    const n = nodes.find((x) => x.id === targetId);
    if (n) rf.setCenter(n.position.x + 32, n.position.y + 40, { zoom: 0.85, duration: 700 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetId]);
  return null;
}

/** Full-screen orchestrator cockpit for a workflow: chat on the RIGHT, the workflow graph lighting up
 *  LIVE on the LEFT — a dot travels the route the supervisor took, the answering agent pulses and the
 *  camera follows it, a "Now running" badge + an active-agent inspector + a step ticker narrate it.
 *  Every session is also saved to Conversations. Reuses the run-replay node + trace machinery. */
export default function WorkflowChat() {
  const { id } = useParams();
  const workflowId = Number(id);
  const navigate = useNavigate();
  const { theme } = useTheme();

  const wf = useWorkflow(workflowId);
  const agents = useAgents();
  const tools = useTools();

  const [baseNodes, setBaseNodes, onNodesChange] = useNodesState<Node>([]);
  const [baseEdges, setBaseEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [turnLog, setTurnLog] = useState<ChatTurnInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const loaded = useRef(false);

  useEffect(() => {
    if (wf.data && agents.data && tools.data && !loaded.current) {
      const resolve = (ref: number | null | undefined) => {
        const a = agents.data!.items.find((x) => x.id === ref);
        const t = tools.data!.items.find((x) => x.id === ref);
        return { name: a?.name, model: a?.model, toolName: t?.name };
      };
      const { nodes, edges } = toFlow(wf.data.graph, resolve);
      const pos = layoutTrace(wf.data.graph); // fresh top-to-bottom decision-tree layout
      setBaseNodes(nodes.map((n) => ({ ...n, position: pos[n.id] ?? n.position })));
      setBaseEdges(edges);
      loaded.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wf.data, agents.data, tools.data]);

  const nameById = useMemo(() => {
    const m: Record<string, string | undefined> = {};
    for (const n of baseNodes) m[n.id] = (n.data as NodeData).agentName;
    return m;
  }, [baseNodes]);

  const roleByName = useMemo(() => {
    const m: Record<string, string> = {};
    for (const a of agents.data?.items ?? []) m[a.name] = a.role;
    return m;
  }, [agents.data]);

  const trace = useMemo(
    () => buildChatTrace(wf.data?.graph ?? EMPTY_GRAPH, nameById, turnLog, busy),
    [wf.data?.graph, nameById, turnLog, busy],
  );

  const nodes = useMemo(
    () => baseNodes.map((n) => ({ ...n, data: { ...(n.data as NodeData), trace: trace.byNode[n.id] } })),
    [baseNodes, trace],
  );
  const edges = useMemo(
    () =>
      baseEdges.map((e) => {
        const key = `${e.source}->${e.target}`;
        const state = trace.activeEdges.has(key) ? "active" : trace.traversed.has(key) ? "traversed" : "idle";
        return {
          ...e,
          type: "pulse",
          data: { ...(e.data ?? {}), state },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 16,
            height: 16,
            color: state === "idle" ? "hsl(var(--muted))" : "hsl(var(--primary))",
          },
        };
      }),
    [baseEdges, trace],
  );

  const last = turnLog.length ? turnLog[turnLog.length - 1] : undefined;
  const lastTool = last?.tools?.length ? last.tools[last.tools.length - 1].tool : undefined;

  if (wf.isError) {
    return (
      <div className="grid h-screen place-items-center p-8">
        <ErrorState message={`Workflow #${workflowId} not found.`} onRetry={() => navigate("/workflows")} />
      </div>
    );
  }
  if (wf.isLoading || agents.isLoading || tools.isLoading) {
    return (
      <div className="grid h-screen place-items-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-bg">
      {/* toolbar */}
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
        <Button variant="ghost" size="icon" onClick={() => navigate("/workflows")} aria-label="Back to workflows">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <span className="font-semibold">{wf.data?.name}</span>
        <span className="hidden text-sm text-muted sm:inline">· chat playground (routed per turn)</span>
        {(busy || last) && (
          <span className="ml-auto inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary">
            <PulseDot />
            {busy
              ? `${trace.routerName ?? "Supervisor"} is routing…`
              : `Now running: ${last!.author}${lastTool ? ` · ${lastTool}` : ""}`}
          </span>
        )}
      </div>

      {/* body: live workflow graph (left) + chat (right) */}
      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={traceNodeTypes}
            edgeTypes={pulseEdgeTypes}
            colorMode={theme}
            nodesConnectable={false}
            edgesFocusable={false}
            fitView
            fitViewOptions={{ padding: 0.3 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className="!bg-surface" />
            <CameraFollow targetId={trace.spotlightId} nodes={baseNodes} />

            {/* legend */}
            <Panel position="top-left">
              <div className="flex items-center gap-3 rounded-lg border border-border bg-card/90 px-3 py-1.5 text-[10px] text-muted backdrop-blur">
                {[
                  ["bg-info", "running"],
                  ["bg-primary", "routed"],
                  ["bg-success", "answered"],
                  ["bg-border-strong", "idle"],
                ].map(([c, label]) => (
                  <span key={label} className="flex items-center gap-1">
                    <span className={cn("inline-block h-2 w-2 rounded-full", c)} /> {label}
                  </span>
                ))}
              </div>
            </Panel>

            {/* active-agent inspector */}
            {last && (
              <Panel position="top-right">
                <div className="w-64 rounded-xl border border-border bg-card/95 p-3 shadow-soft backdrop-blur">
                  <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted">
                    Active agent
                  </div>
                  <div className="flex items-center gap-2">
                    <AgentAvatar name={last.author} className="h-7 w-7 text-[10px]" />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold">{last.author}</div>
                      <div className="truncate text-[11px] text-muted">{roleByName[last.author] ?? "specialist"}</div>
                    </div>
                  </div>
                  {last.input && (
                    <>
                      <div className="mt-2 text-[10px] uppercase tracking-wide text-muted">Handling</div>
                      <div className="line-clamp-2 text-xs text-fg/85">“{last.input}”</div>
                    </>
                  )}
                  {last.tools && last.tools.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {last.tools.map((t, i) => (
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
                  <div className="mt-2 flex items-center gap-3 text-[11px] tabular-nums text-muted">
                    {typeof last.tokens === "number" && <span>{fmtTokens(last.tokens)} tok</span>}
                    {last.reason && <span>· {last.reason}</span>}
                  </div>
                </div>
              </Panel>
            )}

            {/* activity ticker */}
            {(turnLog.length > 0 || busy) && (
              <Panel position="bottom-center">
                <div className="scroll-thin flex max-w-[58vw] items-center gap-2 overflow-x-auto rounded-full border border-border bg-card/95 px-3 py-1.5 text-[11px] shadow-soft backdrop-blur">
                  <span className="shrink-0 font-semibold text-muted">Activity</span>
                  {turnLog.map((t, i) => (
                    <span key={i} className="flex shrink-0 items-center gap-1">
                      <span className="text-muted">›</span>
                      <span className="font-medium" style={{ color: `hsl(${agentHue(t.author)} 60% 45%)` }}>
                        {t.author}
                      </span>
                      {t.tools && t.tools.length > 0 && (
                        <span className="text-muted">({t.tools.map((x) => x.tool).join(", ")})</span>
                      )}
                    </span>
                  ))}
                  {busy && (
                    <span className="flex shrink-0 items-center gap-1 text-primary">
                      <Loader2 className="h-3 w-3 animate-spin" /> routing…
                    </span>
                  )}
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>

        <div className="flex w-[420px] shrink-0 flex-col border-l border-border p-4">
          <div className="mb-3 flex items-center gap-2.5">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
              <Split className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">{wf.data?.name}</div>
              <div className="text-xs text-muted">Live chat · routed per turn · saved to Conversations</div>
            </div>
          </div>
          <ChatSession
            workflowId={workflowId}
            headerName={wf.data?.name ?? "Workflow"}
            fill
            onTurn={(t) => setTurnLog((l) => [...l, t])}
            onBusyChange={setBusy}
          />
        </div>
      </div>
    </div>
  );
}
