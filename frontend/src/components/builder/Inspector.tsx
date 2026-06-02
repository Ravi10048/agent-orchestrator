import type { Edge, Node } from "@xyflow/react";
import { GitBranch, Trash2 } from "lucide-react";

import type { Agent, Tool } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import type { NodeData } from "@/lib/graphCodec";

const CONDITION_EXAMPLES = [
  'last.intent == "billing"',
  "last.resolved == false",
  "last.needs_more == true",
  "attempts < 3",
];

export function Inspector({
  node,
  edge,
  nodes,
  edges,
  agents,
  tools,
  onUpdateNode,
  onUpdateEdge,
  onDelete,
}: {
  node: Node | null;
  edge: Edge | null;
  nodes: Node[];
  edges: Edge[];
  agents: Agent[];
  tools: Tool[];
  onUpdateNode: (id: string, patch: Partial<NodeData>) => void;
  onUpdateEdge: (id: string, condition: string | null) => void;
  onDelete: () => void;
}) {
  if (!node && !edge) {
    return (
      <div className="p-5 text-sm text-muted">
        Select a node or edge to edit it. Drag from a node's bottom handle to connect; add a{" "}
        <span className="font-medium text-fg">condition</span> on an edge for branching or feedback loops.
      </div>
    );
  }

  if (edge) {
    const condition = (edge.data?.condition as string | null) ?? "";
    return (
      <div className="space-y-4 p-5">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">Edge</h3>
          <Button variant="ghost" size="icon" onClick={onDelete} aria-label="Delete edge">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
        <p className="text-xs text-muted">
          {edge.source} → {edge.target}
        </p>
        <div className="space-y-1.5">
          <Label>Condition</Label>
          <Input
            value={condition}
            placeholder="empty = default (else) edge"
            className="font-mono text-xs"
            onChange={(e) => onUpdateEdge(edge.id, e.target.value || null)}
          />
          <p className="text-xs text-muted">
            First matching edge wins; leave empty for the fallback. Reads <code>last.*</code> (the node's output),{" "}
            <code>input.*</code>, and <code>attempts</code>.
          </p>
          <div className="flex flex-wrap gap-1.5 pt-1">
            {CONDITION_EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => onUpdateEdge(edge.id, ex)}
                className="rounded-md border border-border bg-surface px-2 py-1 font-mono text-[11px] text-muted transition hover:border-border-strong hover:text-fg"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // node
  const d = node!.data as NodeData;
  const type = node!.type;
  return (
    <div className="space-y-4 p-5">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold capitalize">{type} node</h3>
        {type !== "start" && type !== "end" && (
          <Button variant="ghost" size="icon" onClick={onDelete} aria-label="Delete node">
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>
      <p className="text-xs text-muted">
        id: <code className="font-mono">{node!.id}</code>
      </p>

      {type === "agent" && (
        <>
          <div className="space-y-1.5">
            <Label>Agent</Label>
            <Select
              value={d.ref ?? ""}
              onChange={(e) => {
                const ref = e.target.value ? Number(e.target.value) : null;
                const a = agents.find((x) => x.id === ref);
                onUpdateNode(node!.id, { ref, agentName: a?.name, model: a?.model });
              }}
            >
              <option value="">— pick an agent —</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Max visits <span className="font-normal text-muted">— loop cap</span></Label>
            <Input
              type="number"
              value={d.maxVisits ?? ""}
              placeholder="default (8)"
              onChange={(e) => onUpdateNode(node!.id, { maxVisits: e.target.value ? Number(e.target.value) : undefined })}
            />
          </div>

          {(() => {
            // Routing targets = this node's UNCONDITIONAL out-edges to agent nodes (the same rule the
            // executor uses to offer `handoff`). >= 2 ⇒ a supervisor/router: at runtime it's handed
            // this roster + each agent's role, and returns the next agent (n) + a reply (r).
            const targets = edges
              .filter((e) => {
                const c = ((e.data?.condition as string | null) ?? "").trim();
                return e.source === node!.id && (!c || c === "else");
              })
              .map((e) => nodes.find((n) => n.id === e.target))
              .filter((n): n is Node => !!n && n.type === "agent")
              .map((n) => agents.find((a) => a.id === (n.data as NodeData).ref))
              .filter((a): a is Agent => !!a);
            if (targets.length < 2) return null;
            return (
              <div className="space-y-2 rounded-lg border border-primary/30 bg-primary/[0.04] p-3">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
                  <GitBranch className="h-3.5 w-3.5" /> Supervisor router
                </div>
                <p className="text-xs leading-relaxed text-muted">
                  At runtime this agent is handed the agents below <span className="text-fg">with their roles</span>,
                  and returns the next agent (<code>n</code>) + a reply (<code>r</code>) via the{" "}
                  <code>handoff</code> tool. The chosen agent receives the original request.
                </p>
                <div className="space-y-1 border-t border-border pt-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">Routes to</div>
                  {targets.map((a) => (
                    <div key={a.id} className="flex items-baseline gap-1.5 text-xs">
                      <span className="font-medium text-fg">{a.name}</span>
                      <span className="truncate text-muted">— {a.role || "specialist"}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
        </>
      )}

      {type === "tool" && (
        <div className="space-y-1.5">
          <Label>Tool</Label>
          <Select
            value={d.ref ?? ""}
            onChange={(e) => {
              const ref = e.target.value ? Number(e.target.value) : null;
              const t = tools.find((x) => x.id === ref);
              onUpdateNode(node!.id, { ref, toolName: t?.name });
            }}
          >
            <option value="">— pick a tool —</option>
            {tools.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </Select>
        </div>
      )}

      {(type === "start" || type === "end" || type === "router") && (
        <p className="text-sm text-muted">
          {type === "router"
            ? "A decision node — put conditions on its outgoing edges."
            : `The ${type} of the workflow.`}
        </p>
      )}
    </div>
  );
}
