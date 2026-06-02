import { useQuery } from "@tanstack/react-query";
import {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  MarkerType,
  MiniMap,
  type Node,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowLeft, ListTree } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Runs } from "@/api/resources";
import { TraceInspector } from "@/components/trace/TraceInspector";
import { traceNodeTypes } from "@/components/trace/TraceNode";
import { Button } from "@/components/ui/button";
import { ConnectionDot, StatusBadge } from "@/components/ui/status";
import { ErrorState, Spinner } from "@/components/ui/feedback";
import { useAgents, useRun, useTools, useWorkflow } from "@/hooks/queries";
import { useMonitorSocket } from "@/hooks/useMonitorSocket";
import { type NodeData, toFlow } from "@/lib/graphCodec";
import { deriveStatus, fmtCost, fmtTokens, isActive } from "@/lib/runFormat";
import { useTheme } from "@/lib/theme";
import { buildTrace, layoutTrace } from "@/lib/trace";

export default function RunGraph() {
  const { id } = useParams();
  const runId = Number(id);
  const navigate = useNavigate();
  const { theme } = useTheme();

  const run = useRun(runId);
  const wf = useWorkflow(run.data?.workflow_id ?? 0);
  const agents = useAgents();
  const tools = useTools();
  const { events, status: socket } = useMonitorSocket(Number.isFinite(runId) ? runId : null);
  const messages = useQuery({
    queryKey: ["run", runId, "messages"],
    queryFn: () => Runs.messages(runId),
    enabled: runId > 0,
  });

  const trace = useMemo(
    () => buildTrace(events, messages.data?.items ?? [], run.data?.input),
    [events, messages.data, run.data?.input],
  );

  const [baseNodes, setBaseNodes, onNodesChange] = useNodesState<Node>([]);
  const [baseEdges, setBaseEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selId, setSelId] = useState<string | null>(null);
  const loaded = useRef(false);

  useEffect(() => {
    if (wf.data && agents.data && tools.data && !loaded.current) {
      const resolve = (ref: number | null | undefined) => {
        const a = agents.data!.items.find((x) => x.id === ref);
        const t = tools.data!.items.find((x) => x.id === ref);
        return { name: a?.name, model: a?.model, toolName: t?.name };
      };
      const { nodes, edges } = toFlow(wf.data.graph, resolve);
      const pos = layoutTrace(wf.data.graph); // fresh top-to-bottom layout (ignore builder positions)
      setBaseNodes(nodes.map((n) => ({ ...n, position: pos[n.id] ?? n.position })));
      setBaseEdges(edges);
      loaded.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wf.data, agents.data, tools.data]);

  // overlay live trace onto the base graph (positions preserved; recomputed as events stream)
  const nodes = useMemo(
    () =>
      baseNodes.map((n) => ({
        ...n,
        selected: n.id === selId,
        data: { ...(n.data as NodeData), trace: trace.byNode[n.id] },
      })),
    [baseNodes, trace, selId],
  );
  const edges = useMemo(
    () =>
      baseEdges.map((e) => {
        const walked = trace.traversed.has(`${e.source}->${e.target}`);
        return {
          ...e,
          type: "smoothstep",
          animated: walked,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 18,
            height: 18,
            color: walked ? "hsl(var(--primary))" : "hsl(var(--muted))",
          },
          style: walked
            ? { stroke: "hsl(var(--primary))", strokeWidth: 2.5 }
            : { strokeDasharray: "4 4", opacity: 0.35 },
        };
      }),
    [baseEdges, trace],
  );

  const liveStatus = deriveStatus(events, run.data?.status ?? "pending");
  const selTrace = selId ? (trace.byNode[selId] ?? null) : null;
  const selBase = baseNodes.find((n) => n.id === selId);
  const selLabel =
    (selBase?.data as NodeData | undefined)?.agentName ||
    (selBase?.data as NodeData | undefined)?.toolName ||
    (selBase?.type ? selBase.type.charAt(0).toUpperCase() + selBase.type.slice(1) : "Node");

  if (run.isError) {
    return (
      <div className="grid h-screen place-items-center p-8">
        <ErrorState message={`Run #${runId} not found.`} onRetry={() => navigate("/runs")} />
      </div>
    );
  }
  if (run.isLoading || wf.isLoading || agents.isLoading || tools.isLoading) {
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
        <Button variant="ghost" size="icon" onClick={() => navigate("/runs")} aria-label="Back to runs">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-2">
          <span className="font-semibold">Run #{runId}</span>
          <StatusBadge status={liveStatus} />
          {isActive(liveStatus) && <ConnectionDot status={socket} />}
        </div>
        <span className="truncate text-sm text-muted">{wf.data?.name}</span>
        <div className="ml-auto flex items-center gap-4">
          <span className="text-xs tabular-nums text-muted">
            {fmtTokens(run.data?.total_tokens ?? 0)} tok · {fmtCost(run.data?.est_cost ?? 0)}
          </span>
          <Button variant="secondary" size="sm" onClick={() => navigate(`/runs?run=${runId}`)}>
            <ListTree className="h-4 w-4" /> Timeline
          </Button>
        </div>
      </div>

      {/* the user's request — the thing that kicked off the whole flow */}
      {trace.userInput && (
        <div className="flex shrink-0 items-start gap-2 border-b border-border bg-surface/50 px-4 py-2.5 text-sm">
          <span className="mt-0.5 shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
            Request
          </span>
          <span className="text-fg/90">{trace.userInput}</span>
        </div>
      )}

      {/* body: canvas + inspector */}
      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={traceNodeTypes}
            colorMode={theme}
            nodesConnectable={false}
            edgesFocusable={false}
            onNodeClick={(_, n) => setSelId(n.id)}
            onPaneClick={() => setSelId(null)}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className="!bg-surface" />
          </ReactFlow>
        </div>

        <div className="w-80 shrink-0 overflow-y-auto scroll-thin border-l border-border">
          <TraceInspector trace={selTrace} nodeLabel={selLabel} />
        </div>
      </div>
    </div>
  );
}
