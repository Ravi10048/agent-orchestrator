import {
  Background,
  BackgroundVariant,
  type Connection,
  Controls,
  type Edge,
  MiniMap,
  type Node,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Bot, CheckCircle2, Flag, GitBranch, LayoutTemplate, MessagesSquare, Play, Plus, Save, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import type { ApiError } from "@/api/client";
import { Workflows } from "@/api/resources";
import { Inspector } from "@/components/builder/Inspector";
import { nodeTypes } from "@/components/builder/nodes";
import { RunModal } from "@/components/RunModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/feedback";
import { useAgents, useTools, useWorkflow } from "@/hooks/queries";
import { type NodeData, newNodeId, toFlow, toGraph } from "@/lib/graphCodec";
import { toast } from "@/lib/toast";
import { useTheme } from "@/lib/theme";

const PALETTE = [
  { type: "agent", label: "Agent", icon: Bot },
  { type: "tool", label: "Tool", icon: Wrench },
  { type: "router", label: "Router", icon: GitBranch },
  { type: "start", label: "Start", icon: Play },
  { type: "end", label: "End", icon: Flag },
] as const;

export default function WorkflowBuilder() {
  const { id } = useParams();
  const wfId = Number(id);
  const navigate = useNavigate();
  const { theme } = useTheme();
  const wf = useWorkflow(wfId);
  const agents = useAgents();
  const tools = useTools();
  const qc = useQueryClient();

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [name, setName] = useState("");
  const [selNodeId, setSelNodeId] = useState<string | null>(null);
  const [selEdgeId, setSelEdgeId] = useState<string | null>(null);
  const [validation, setValidation] = useState<{ valid: boolean; errors: string[] } | null>(null);
  const [saving, setSaving] = useState(false);
  const [runOpen, setRunOpen] = useState(false);
  const loaded = useRef(false);

  const resolve = (ref: number | null | undefined) => {
    const a = agents.data?.items.find((x) => x.id === ref);
    const t = tools.data?.items.find((x) => x.id === ref);
    return { name: a?.name, model: a?.model, toolName: t?.name };
  };

  useEffect(() => {
    if (wf.data && agents.data && tools.data && !loaded.current) {
      const { nodes: n, edges: e } = toFlow(wf.data.graph, resolve);
      setNodes(n);
      setEdges(e);
      setName(wf.data.name);
      loaded.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wf.data, agents.data, tools.data]);

  // live validation (debounced)
  useEffect(() => {
    if (!loaded.current) return;
    const t = setTimeout(() => {
      Workflows.validate(toGraph(nodes, edges))
        .then(setValidation)
        .catch(() => setValidation(null));
    }, 450);
    return () => clearTimeout(t);
  }, [nodes, edges]);

  const onConnect = (c: Connection) =>
    setEdges((es) => addEdge({ ...c, data: { condition: null }, style: { strokeDasharray: "5 5" } }, es));

  const addNode = (type: string) => {
    const newId = newNodeId(type, nodes);
    const offset = nodes.length % 6;
    setNodes((ns) => [
      ...ns,
      {
        id: newId,
        type,
        position: { x: 160 + offset * 36, y: 140 + offset * 36 },
        data: { ref: null } as NodeData,
      },
    ]);
  };

  const updateNode = (nid: string, patch: Partial<NodeData>) =>
    setNodes((ns) => ns.map((n) => (n.id === nid ? { ...n, data: { ...(n.data as NodeData), ...patch } } : n)));

  const updateEdge = (eid: string, condition: string | null) =>
    setEdges((es) =>
      es.map((e) =>
        e.id === eid
          ? {
              ...e,
              data: { ...e.data, condition },
              label: condition ?? undefined,
              animated: !!condition,
              style: condition ? undefined : { strokeDasharray: "5 5" },
            }
          : e,
      ),
    );

  const deleteSelected = () => {
    if (selEdgeId) {
      setEdges((es) => es.filter((e) => e.id !== selEdgeId));
      setSelEdgeId(null);
    } else if (selNodeId) {
      setNodes((ns) => ns.filter((n) => n.id !== selNodeId));
      setEdges((es) => es.filter((e) => e.source !== selNodeId && e.target !== selNodeId));
      setSelNodeId(null);
    }
  };

  const doSave = async (): Promise<boolean> => {
    setSaving(true);
    try {
      await Workflows.update(wfId, { name, graph: toGraph(nodes, edges) });
      toast.success("Workflow saved");
      return true;
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "graph_invalid" && Array.isArray(err.details)) {
        setValidation({ valid: false, errors: err.details as string[] });
      }
      toast.error(err.message ?? "Save failed");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleRun = async () => {
    if (await doSave()) setRunOpen(true);
  };

  // save the edits first, then open the live chat playground for this workflow (so the cockpit
  // reflects what you just changed)
  const handleChat = async () => {
    if (await doSave()) navigate(`/workflows/${wfId}/chat`);
  };

  // publish the current canvas as a reusable template — save first so the template reflects the
  // latest edits, then upsert (idempotent per tenant+name → re-clicking updates, never duplicates).
  // It shows on the Templates page, where "Use template" instantiates a runnable copy.
  const handleSaveAsTemplate = async () => {
    if (!(await doSave())) return;
    setSaving(true);
    try {
      const tpl = await Workflows.saveAsTemplate(wfId);
      qc.invalidateQueries({ queryKey: ["templates"] });
      toast.success(`Saved "${tpl.name}" as a template`);
    } catch (e) {
      toast.error((e as ApiError).message ?? "Couldn't save as template");
    } finally {
      setSaving(false);
    }
  };

  const selNode = nodes.find((n) => n.id === selNodeId) ?? null;
  const selEdge = edges.find((e) => e.id === selEdgeId) ?? null;

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
        <Button variant="ghost" size="icon" onClick={() => navigate("/workflows")} aria-label="Back">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 w-64 font-medium" />
        {validation &&
          (validation.valid ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-success">
              <CheckCircle2 className="h-4 w-4" /> valid
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-xs text-warning" title={validation.errors.join("\n")}>
              <AlertTriangle className="h-4 w-4" /> {validation.errors.length} issue{validation.errors.length > 1 ? "s" : ""}
            </span>
          ))}
        <div className="ml-auto flex items-center gap-2">
          <Button variant="secondary" onClick={doSave} disabled={saving}>
            <Save className="h-4 w-4" /> Save
          </Button>
          <Button variant="secondary" onClick={handleSaveAsTemplate} disabled={saving}
                  title="Publish the current canvas as a reusable template">
            <LayoutTemplate className="h-4 w-4" /> Template
          </Button>
          <Button variant="secondary" onClick={handleChat} disabled={saving}
                  title="Save + open the live chat playground for this workflow">
            <MessagesSquare className="h-4 w-4" /> Chat
          </Button>
          <Button onClick={handleRun} disabled={saving}>
            <Play className="h-4 w-4" /> Run
          </Button>
        </div>
      </div>

      {/* body */}
      <div className="flex min-h-0 flex-1">
        {/* palette */}
        <div className="w-44 shrink-0 space-y-1.5 border-r border-border p-3">
          <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">Add node</div>
          {PALETTE.map(({ type, label, icon: Icon }) => (
            <button
              key={type}
              onClick={() => addNode(type)}
              className="flex w-full items-center gap-2.5 rounded-lg border border-border px-3 py-2 text-sm transition hover:border-border-strong hover:bg-surface"
            >
              <Icon className="h-4 w-4 text-muted" />
              {label}
              <Plus className="ml-auto h-3.5 w-3.5 text-muted" />
            </button>
          ))}
        </div>

        {/* canvas */}
        <div className="relative min-w-0 flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            colorMode={theme}
            onNodeClick={(_, n) => {
              setSelNodeId(n.id);
              setSelEdgeId(null);
            }}
            onEdgeClick={(_, e) => {
              setSelEdgeId(e.id);
              setSelNodeId(null);
            }}
            onPaneClick={() => {
              setSelNodeId(null);
              setSelEdgeId(null);
            }}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className="!bg-surface" />
          </ReactFlow>

          {validation && !validation.valid && (
            <div className="absolute bottom-4 left-4 max-w-sm rounded-lg border border-warning/40 bg-card p-3 shadow-pop">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-warning">
                <AlertTriangle className="h-3.5 w-3.5" /> Validation
              </div>
              <ul className="list-inside list-disc space-y-0.5 text-xs text-muted">
                {validation.errors.map((er, i) => (
                  <li key={i}>{er}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* inspector */}
        <div className="w-80 shrink-0 overflow-y-auto scroll-thin border-l border-border">
          <Inspector
            node={selNode}
            edge={selEdge}
            nodes={nodes}
            edges={edges}
            agents={agents.data?.items ?? []}
            tools={tools.data?.items ?? []}
            onUpdateNode={updateNode}
            onUpdateEdge={updateEdge}
            onDelete={deleteSelected}
          />
        </div>
      </div>

      <RunModal open={runOpen} onClose={() => setRunOpen(false)} workflowId={wfId} workflowName={name} />
    </div>
  );
}
