import type { Edge, Node } from "@xyflow/react";

import type { GraphJSON } from "@/api/types";

export interface NodeData {
  ref: number | null;
  maxVisits?: number;
  agentName?: string;
  model?: string;
  toolName?: string;
  [key: string]: unknown;
}

type Resolve = (ref: number | null | undefined) => { name?: string; model?: string; toolName?: string };

/** Top→bottom layered layout (BFS from start) for graphs without saved positions — matches the
 *  run-graph decision-tree view (levels stack downward, siblings spread + centered horizontally). */
function layout(graph: GraphJSON): Record<string, { x: number; y: number }> {
  const adj: Record<string, string[]> = {};
  for (const e of graph.edges) (adj[e.from] ??= []).push(e.to);
  const start = graph.nodes.find((n) => n.type === "start")?.id;
  const level: Record<string, number> = {};
  const q: string[] = [];
  if (start) {
    level[start] = 0;
    q.push(start);
  }
  while (q.length) {
    const x = q.shift()!;
    for (const d of adj[x] ?? []) if (level[d] == null) ((level[d] = level[x] + 1), q.push(d));
  }
  for (const n of graph.nodes) if (level[n.id] == null) level[n.id] = 0;
  const byLevel: Record<number, string[]> = {};
  for (const n of graph.nodes) (byLevel[level[n.id]] ??= []).push(n.id);
  const pos: Record<string, { x: number; y: number }> = {};
  for (const [lvl, ids] of Object.entries(byLevel)) {
    const k = ids.length;
    ids.forEach((id, i) => (pos[id] = { x: (i - (k - 1) / 2) * 300, y: Number(lvl) * 190 }));
  }
  return pos;
}

export function toFlow(graph: GraphJSON, resolve: Resolve): { nodes: Node[]; edges: Edge[] } {
  const auto = layout(graph);
  const nodes: Node[] = (graph.nodes ?? []).map((n) => {
    const cfg = (n.config ?? {}) as Record<string, unknown>;
    const meta = resolve(n.ref);
    return {
      id: n.id,
      type: n.type,
      position: (cfg.position as { x: number; y: number }) ?? auto[n.id] ?? { x: 40, y: 40 },
      data: {
        ref: n.ref ?? null,
        maxVisits: cfg.max_visits as number | undefined,
        agentName: meta.name,
        model: meta.model,
        toolName: meta.toolName,
      } satisfies NodeData,
    };
  });
  const edges: Edge[] = (graph.edges ?? []).map((e, i) => ({
    id: `e${i}-${e.from}-${e.to}`,
    source: e.from,
    target: e.to,
    label: e.condition ?? undefined,
    data: { condition: e.condition ?? null },
    animated: !!e.condition,
    style: e.condition ? undefined : { strokeDasharray: "5 5" },
  }));
  return { nodes, edges };
}

export function toGraph(nodes: Node[], edges: Edge[]): GraphJSON {
  return {
    nodes: nodes.map((n) => {
      const d = n.data as NodeData;
      const config: Record<string, unknown> = { position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } };
      if (n.type === "agent" && d.maxVisits != null) config.max_visits = d.maxVisits;
      return { id: n.id, type: (n.type ?? "agent") as GraphJSON["nodes"][number]["type"], ref: d.ref ?? null, config };
    }),
    edges: edges.map((e) => ({
      from: e.source,
      to: e.target,
      condition: ((e.data?.condition as string | null) ?? null) || null,
    })),
  };
}

export function newNodeId(type: string, nodes: Node[]): string {
  const ids = new Set(nodes.map((n) => n.id));
  let i = 1;
  while (ids.has(`${type}_${i}`)) i++;
  return `${type}_${i}`;
}
