import type { GraphJSON } from "@/api/types";
import { type NodeTrace, edgeKey } from "@/lib/trace";

/** One completed assistant turn from a routed chat. */
export interface ChatTurn {
  author: string; // the specialist (or router) that produced the reply
  tools: { tool: string; ok: boolean }[];
}

export interface ChatTrace {
  byNode: Record<string, NodeTrace>;
  traversed: Set<string>; // "from->to" edges ever walked (subtle highlight)
  activeEdges: Set<string>; // the LATEST route's edges (strong pulse)
  routerNodeId?: string;
  routerName?: string;
  spotlightId?: string; // the node to pulse + center the camera on this turn
}

/** Synthesize a per-node trace from a routed chat's turn log, so the SAME polished TraceNode +
 *  edge-highlighting used for run replay can render a LIVE routing view: the supervisor (start's
 *  successor) is the router; each turn lights up the path supervisor → the answering specialist,
 *  the latest specialist shows the tools it called, and the supervisor pulses while a turn is
 *  in flight. Visit counts accumulate across turns (×N on a specialist that answered repeatedly). */
export function buildChatTrace(
  graph: GraphJSON,
  nameById: Record<string, string | undefined>,
  turnLog: ChatTurn[],
  busy: boolean,
): ChatTrace {
  const byNode: Record<string, NodeTrace> = {};
  const traversed = new Set<string>();
  const ensure = (id: string): NodeTrace =>
    (byNode[id] ??= { nodeId: id, ran: false, visits: 0, status: "idle", tokens: 0, tools: [] });

  const startId = graph.nodes.find((n) => n.type === "start")?.id;
  const routerNodeId = startId ? graph.edges.find((e) => e.from === startId)?.to : undefined;
  const routerName = routerNodeId ? nameById[routerNodeId] : undefined;

  const idByName: Record<string, string> = {};
  for (const [id, nm] of Object.entries(nameById)) if (nm) idByName[nm] = id;

  const counts: Record<string, number> = {};
  for (const t of turnLog) counts[t.author] = (counts[t.author] ?? 0) + 1;
  const latest = turnLog[turnLog.length - 1];
  const live = turnLog.length > 0 || busy;

  // start
  if (startId && live) {
    const s = ensure(startId);
    s.ran = true;
    s.status = "done";
  }

  // router / supervisor — consulted every turn
  if (routerNodeId) {
    const r = ensure(routerNodeId);
    if (live) {
      r.ran = true;
      r.visits = turnLog.length;
      if (busy) r.status = "running"; // deciding the route for the in-flight message
      else if (latest && routerName && latest.author !== routerName) {
        r.status = "handoff";
        r.route = latest.author;
      } else r.status = "done"; // it answered itself (or no turns yet)
    }
    if (startId) traversed.add(edgeKey(startId, routerNodeId));
  }

  // specialists that have answered
  for (const [name, count] of Object.entries(counts)) {
    const nid = idByName[name];
    if (!nid || nid === routerNodeId) continue; // the router is handled above
    const t = ensure(nid);
    t.ran = true;
    t.visits = count;
    t.agentName = name;
    t.status = "done";
    if (latest && name === latest.author && !busy) t.tools = latest.tools; // latest turn shows its tools
    if (routerNodeId) traversed.add(edgeKey(routerNodeId, nid));
  }

  // the latest answerer's node (router itself if it answered directly)
  const latestId = latest ? idByName[latest.author] || (routerName === latest.author ? routerNodeId : undefined) : undefined;

  // SPOTLIGHT = the node the camera follows + pulses: the router while a turn is in flight (it's
  // deciding), otherwise the agent that just answered.
  const spotlightId = busy ? routerNodeId : latestId;
  if (spotlightId && byNode[spotlightId]) byNode[spotlightId].spotlight = true;

  // ACTIVE edges = the latest route to pulse a travelling dot along (start→router always; router→the
  // answering specialist when it handed off this turn).
  const activeEdges = new Set<string>();
  if (live && startId && routerNodeId) activeEdges.add(edgeKey(startId, routerNodeId));
  if (!busy && latestId && routerNodeId && latestId !== routerNodeId) activeEdges.add(edgeKey(routerNodeId, latestId));

  return { byNode, traversed, activeEdges, routerNodeId, routerName, spotlightId };
}
