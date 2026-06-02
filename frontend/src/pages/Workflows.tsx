import { LayoutTemplate, MessagesSquare, Plus, Trash2, Workflow as WorkflowIcon } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { ApiError } from "@/api/client";
import type { Workflow } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/ui/feedback";
import { ConfirmDialog } from "@/components/ui/modal";
import { useWorkflowMutations, useWorkflows } from "@/hooks/queries";
import { toast } from "@/lib/toast";

const STARTER = {
  nodes: [
    { id: "start", type: "start" as const },
    { id: "end", type: "end" as const },
  ],
  edges: [{ from: "start", to: "end" }],
};

export default function WorkflowsPage() {
  const { data, isLoading, isError, refetch } = useWorkflows(false);
  const { create, remove, saveAsTemplate: saveTpl } = useWorkflowMutations();
  const navigate = useNavigate();
  const [confirmId, setConfirmId] = useState<number | null>(null);

  const newWorkflow = async () => {
    try {
      const wf = await create.mutateAsync({ name: "Untitled workflow", graph: STARTER });
      navigate(`/workflows/${wf.id}/build`);
    } catch (e) {
      toast.error((e as ApiError).message ?? "Couldn't create workflow");
    }
  };

  const doDelete = async (id: number) => {
    try {
      await remove.mutateAsync(id);
      toast.success("Workflow deleted");
    } catch (e) {
      toast.error((e as ApiError).message ?? "Delete failed");
    }
  };

  // publish a COPY of this workflow as a reusable template (non-destructive: the original stays a
  // runnable workflow, so its runs + channel routing bindings are untouched). IDEMPOTENT per
  // (tenant, name) — re-clicking updates the same template, never duplicates. Appears on Templates.
  const saveAsTemplate = async (w: Workflow) => {
    try {
      const tpl = await saveTpl.mutateAsync(w.id);
      toast.success(`Saved "${tpl.name}" as a template`);
    } catch (e) {
      toast.error((e as ApiError).message ?? "Couldn't save as template");
    }
  };

  return (
    <>
      <PageHeader
        title="Workflows"
        subtitle="Visual multi-agent workflows — build on the canvas, then run."
        actions={
          <Button onClick={newWorkflow} disabled={create.isPending}>
            <Plus className="h-4 w-4" /> New workflow
          </Button>
        }
      />

      {isLoading ? (
        <ListSkeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Couldn't load workflows." onRetry={refetch} />
      ) : data && data.items.length > 0 ? (
        <div className="space-y-2.5">
          {data.items.map((w) => (
            <Card
              key={w.id}
              onClick={() => navigate(`/workflows/${w.id}/build`)}
              className="flex cursor-pointer items-center gap-4 px-4 py-3 transition hover:border-border-strong hover:bg-surface"
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface text-muted">
                <WorkflowIcon className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-medium">{w.name}</div>
                <p className="mt-0.5 truncate text-sm text-muted">{w.description || "—"}</p>
              </div>
              <Badge>{w.graph?.nodes?.length ?? 0} nodes</Badge>
              <Button
                variant="secondary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/workflows/${w.id}/chat`);
                }}
                aria-label="Open chat with workflow"
                title="Open chat — routed per turn through this workflow's supervisor (live graph)"
              >
                <MessagesSquare className="h-4 w-4" /> Chat
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  saveAsTemplate(w);
                }}
                disabled={saveTpl.isPending}
                aria-label="Save as template"
                title="Save a copy as a reusable template (shows on the Templates page)"
              >
                <LayoutTemplate className="h-4 w-4" /> Template
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmId(w.id);
                }}
                aria-label="Delete workflow"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No workflows yet"
          hint="Build one on the canvas, or start from a template (Templates tab)."
          action={
            <Button onClick={newWorkflow}>
              <Plus className="h-4 w-4" /> New workflow
            </Button>
          }
        />
      )}

      <ConfirmDialog
        open={confirmId !== null}
        onClose={() => setConfirmId(null)}
        onConfirm={() => confirmId && doDelete(confirmId)}
        title="Delete workflow?"
        body="This removes the workflow. Past runs are kept."
        confirmLabel="Delete"
        destructive
      />
    </>
  );
}
