import { ArrowRight, Boxes, GitBranch, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { ApiError } from "@/api/client";
import type { Workflow } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { RunModal } from "@/components/RunModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/ui/feedback";
import { ConfirmDialog } from "@/components/ui/modal";
import { AgentAvatar } from "@/components/ui/status";
import { useAgents, useTemplates, useWorkflowMutations } from "@/hooks/queries";
import { toast } from "@/lib/toast";

// a blank template = start → end; you build it out on the canvas, then it's reusable via "Use template"
const STARTER = {
  nodes: [
    { id: "start", type: "start" as const },
    { id: "end", type: "end" as const },
  ],
  edges: [{ from: "start", to: "end" }],
};

export default function TemplatesPage() {
  const { data, isLoading, isError, refetch } = useTemplates();
  const agents = useAgents();
  const { instantiate, create, remove } = useWorkflowMutations();
  const navigate = useNavigate();
  const [runTarget, setRunTarget] = useState<{ id: number; name: string } | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);

  // create a blank template in the current org, then open the builder to design it
  const newTemplate = async () => {
    try {
      const tpl = await create.mutateAsync({ name: "Untitled template", graph: STARTER, is_template: true });
      navigate(`/workflows/${tpl.id}/build`);
    } catch (e) {
      toast.error((e as ApiError).message ?? "Couldn't create template");
    }
  };

  const doDelete = async (id: number) => {
    try {
      await remove.mutateAsync(id);
      toast.success("Template deleted");
    } catch (e) {
      toast.error((e as ApiError).message ?? "Delete failed");
    }
  };

  const agentNamesOf = (wf: Workflow): string[] => {
    const names = (wf.graph?.nodes ?? [])
      .filter((n) => n.type === "agent")
      .map((n) => agents.data?.items.find((a) => a.id === n.ref)?.name)
      .filter((n): n is string => !!n);
    return [...new Set(names)];
  };

  // A template is a "supervisor router" if one agent has >= 2 UNCONDITIONAL out-edges to other
  // agents (a genuine routing choice) — the same rule the executor uses to offer the `handoff` tool.
  const isRouter = (wf: Workflow): boolean => {
    const agentIds = new Set((wf.graph?.nodes ?? []).filter((n) => n.type === "agent").map((n) => n.id));
    const fanout: Record<string, number> = {};
    for (const e of wf.graph?.edges ?? []) {
      const unconditional = !e.condition || e.condition === "else";
      if (unconditional && agentIds.has(e.from) && agentIds.has(e.to)) fanout[e.from] = (fanout[e.from] ?? 0) + 1;
    }
    return Object.values(fanout).some((c) => c >= 2);
  };

  const onUse = async (tpl: Workflow) => {
    try {
      const wf = await instantiate.mutateAsync({ id: tpl.id, name: `${tpl.name} run` });
      toast.success(`Created "${wf.name}"`);
      setRunTarget({ id: wf.id, name: wf.name });
    } catch (e) {
      toast.error((e as ApiError).message ?? "Failed to instantiate template");
    }
  };

  return (
    <>
      <PageHeader
        title="Templates"
        subtitle="Ready-to-run multi-agent workflows — one click to a live run."
        actions={
          <Button onClick={newTemplate} disabled={create.isPending}>
            <Plus className="h-4 w-4" /> New template
          </Button>
        }
      />

      {isLoading ? (
        <ListSkeleton rows={2} />
      ) : isError ? (
        <ErrorState message="Couldn't load templates." onRetry={refetch} />
      ) : data && data.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2">
          {data.map((tpl) => {
            const names = agentNamesOf(tpl);
            const nodeCount = tpl.graph?.nodes?.length ?? 0;
            const router = isRouter(tpl);
            return (
              <Card
                key={tpl.id}
                className={`flex flex-col transition hover:border-border-strong ${router ? "ring-1 ring-primary/30" : ""}`}
              >
                <CardContent className="flex flex-1 flex-col gap-4 pt-5">
                  <div className="flex items-start gap-3">
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
                      {router ? <GitBranch className="h-5 w-5" /> : <Boxes className="h-5 w-5" />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold tracking-tight">{tpl.name}</h3>
                        {router && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                            <GitBranch className="h-3 w-3" /> supervisor routing
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-sm text-muted">
                        {tpl.description || "A multi-agent workflow."}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setConfirmId(tpl.id)}
                      aria-label="Delete template"
                      title="Delete template"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {names.map((n) => (
                      <span
                        key={n}
                        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2 py-1 text-xs"
                      >
                        <AgentAvatar name={n} className="h-4 w-4 text-[9px]" />
                        {n}
                      </span>
                    ))}
                    <Badge>{nodeCount} nodes</Badge>
                  </div>

                  <div className="mt-auto flex justify-end">
                    <Button onClick={() => onUse(tpl)} disabled={instantiate.isPending}>
                      Use template <ArrowRight className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : (
        <EmptyState
          title="No templates in this org yet"
          hint="Create one here, or switch orgs — the starter templates (Support Router, Collaborative Brief, Research→Report→Notify) are seeded into the default org. You can also build a workflow and ‘Save as template’ from the builder."
          action={
            <Button onClick={newTemplate} disabled={create.isPending}>
              <Plus className="h-4 w-4" /> New template
            </Button>
          }
        />
      )}

      <RunModal
        open={!!runTarget}
        onClose={() => setRunTarget(null)}
        workflowId={runTarget?.id ?? 0}
        workflowName={runTarget?.name ?? ""}
        defaultInput="Research the latest on small language models and write a concise brief."
      />

      <ConfirmDialog
        open={confirmId !== null}
        onClose={() => setConfirmId(null)}
        onConfirm={() => confirmId && doDelete(confirmId)}
        title="Delete template?"
        body="This removes the template. Workflows you already created from it are kept."
        confirmLabel="Delete"
        destructive
      />
    </>
  );
}
