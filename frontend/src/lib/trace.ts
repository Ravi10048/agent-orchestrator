import type { EventEnvelope, GraphJSON, Message } from "@/api/types";

// Reduces a run's event stream (+ persisted messages) into per-node execution data and the
// actual path taken — so the workflow graph can be replayed/debugged visually.

export type TraceStatus = "idle" | "running" | "done" | "handoff" | "error";

export interface ToolRun {
  tool: string;
  ok: boolean;
  error?: string | null;
  latencyMs?: number;
}

export interface NodeTrace {
  nodeId: string;
  ran: boolean;
  visits: number;
  step?: number;
  nodeType?: string;
  agentName?: string;
  model?: string;
  status: TraceStatus;
  stoppedReason?: string;
  route?: string; // handoff target agent name
  tokens: number;
  durationMs?: number;
  tools: ToolRun[];
  error?: string;
  preview?: string; // text_preview from node_finished (truncated)
  fullText?: string; // full reply, matched from persisted messages by agent name
  inputText?: string; // what this node received (the upstream node's output / the user request)
  spotlight?: boolean; // live cockpit: the node to pulse + center the camera on (set by buildChatTrace)
}

export interface RunTrace {
  byNode: Record<string, NodeTrace>;
  order: string[]; // node ids in execution order (by node_started)
  traversed: Set<string>; // "from->to" edges actually walked
  userInput: string;
}

export const edgeKey = (from: string, to: string) => `${from}->${to}`;

const str = (p: Record<string, unknown>, k: string): string | undefined =>
  typeof p[k] === "string" && p[k] ? (p[k] as string) : undefined;
const num = (p: Record<string, unknown>, k: string): number | undefined =>
  typeof p[k] === "number" ? (p[k] as number) : undefined;

export function buildTrace(
  events: EventEnvelope[],
  messages: Message[],
  runInput?: Record<string, unknown> | null,
): RunTrace {
  const byNode: Record<string, NodeTrace> = {};
  const order: string[] = [];
  const traversed = new Set<string>();
  let userInput = typeof runInput?.text === "string" ? (runInput.text as string) : "";

  const ensure = (id: string): NodeTrace =>
    (byNode[id] ??= { nodeId: id, ran: false, visits: 0, status: "idle", tokens: 0, tools: [] });

  // full reply text per agent (node_finished only carries a 200-char preview)
  const msgByAgent: Record<string, string[]> = {};
  for (const m of messages) {
    if (!m.from_agent || m.from_agent === "user" || !m.content) continue;
    (msgByAgent[m.from_agent] ??= []).push(m.content);
  }

  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    const p = e.payload;
    const nid = str(p, "node_id");
    switch (e.type) {
      case "run_started":
        userInput = str(p, "input_preview") || userInput;
        break;
      case "node_started": {
        if (!nid) break;
        const t = ensure(nid);
        t.ran = true;
        t.visits += 1;
        t.status = "running";
        t.step = num(p, "step");
        t.nodeType = str(p, "node_type") ?? t.nodeType;
        t.agentName = str(p, "agent_name") ?? t.agentName;
        order.push(nid);
        break;
      }
      case "node_finished": {
        if (!nid) break;
        const t = ensure(nid);
        if (str(p, "note") === "dead_end_terminal") {
          t.status = "done";
          break;
        }
        t.agentName = str(p, "agent_name") ?? t.agentName;
        t.nodeType = str(p, "node_type") ?? t.nodeType;
        t.stoppedReason = str(p, "stopped_reason");
        t.route = str(p, "route");
        t.tokens = num(p, "tokens") ?? t.tokens;
        t.durationMs = num(p, "duration_ms") ?? t.durationMs;
        t.preview = str(p, "text_preview") ?? t.preview;
        t.status = t.route || t.stoppedReason === "handoff" ? "handoff" : "done";
        if (t.agentName && msgByAgent[t.agentName]) t.fullText = msgByAgent[t.agentName].join("\n\n— — —\n\n");
        break;
      }
      case "token_usage": {
        if (!nid) break;
        ensure(nid).model = str(p, "model") ?? ensure(nid).model;
        break;
      }
      case "tool_call": {
        if (!nid) break;
        ensure(nid).tools.push({
          tool: str(p, "tool") ?? "tool",
          ok: p.ok !== false,
          error: str(p, "error") ?? null,
          latencyMs: num(p, "latency_ms"),
        });
        break;
      }
      case "error": {
        if (!nid) break;
        const t = ensure(nid);
        t.status = "error";
        t.error = str(p, "error");
        break;
      }
    }
  }

  for (let i = 0; i + 1 < order.length; i++) traversed.add(edgeKey(order[i], order[i + 1]));

  // what each node RECEIVED. Normally that's the upstream node's output (the user request on the
  // first hop). But a ROUTER forwards the request it received — its own reply (`r`) is shown as the
  // router's output, while the chosen agent gets the original request — so carry the router's input.
  for (let i = 0; i < order.length; i++) {
    const cur = byNode[order[i]];
    if (i === 0) {
      cur.inputText = userInput;
    } else {
      const prev = byNode[order[i - 1]];
      if (prev.nodeType === "start") cur.inputText = userInput;
      else if (prev.route) cur.inputText = prev.inputText ?? userInput; // router forwards its own input
      else cur.inputText = prev.fullText || prev.preview || "";
    }
  }

  return { byNode, order, traversed, userInput };
}

/** Top-to-bottom layered layout (LangGraph-style flowchart) — levels stack downward,
 *  siblings within a level spread horizontally and centered. */
export function layoutTrace(graph: GraphJSON): Record<string, { x: number; y: number }> {
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
    for (const d of adj[x] ?? [])
      if (level[d] == null) {
        level[d] = level[x] + 1;
        q.push(d);
      }
  }
  for (const n of graph.nodes) if (level[n.id] == null) level[n.id] = 0;
  const byLevel: Record<number, string[]> = {};
  for (const n of graph.nodes) (byLevel[level[n.id]] ??= []).push(n.id);
  const pos: Record<string, { x: number; y: number }> = {};
  for (const [lvl, ids] of Object.entries(byLevel)) {
    const k = ids.length;
    ids.forEach((id, i) => (pos[id] = { x: (i - (k - 1) / 2) * 300, y: Number(lvl) * 200 }));
  }
  return pos;
}
