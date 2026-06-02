import { FileJson, Plus, Trash2, Wrench } from "lucide-react";
import { useState } from "react";

import type { ApiError } from "@/api/client";
import type { Tool } from "@/api/types";
import { ImportToolsModal } from "@/components/ImportToolsModal";
import { PageHeader } from "@/components/PageHeader";
import { ToolEditor } from "@/components/ToolEditor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/ui/feedback";
import { ConfirmDialog } from "@/components/ui/modal";
import { useToolMutations, useTools } from "@/hooks/queries";
import { toast } from "@/lib/toast";

export default function ToolsPage() {
  const { data, isLoading, isError, refetch } = useTools();
  const { remove } = useToolMutations();
  const [editorOpen, setEditorOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [editTool, setEditTool] = useState<Tool | null>(null);
  const [confirm, setConfirm] = useState<{ id: number; force: boolean; body: string } | null>(null);

  const openNew = () => {
    setEditTool(null);
    setEditorOpen(true);
  };

  const askDelete = (t: Tool) =>
    setConfirm({ id: t.id, force: false, body: `Delete "${t.name}"? This can't be undone.` });

  const doDelete = async () => {
    if (!confirm) return;
    try {
      await remove.mutateAsync({ id: confirm.id, force: confirm.force });
      toast.success("Tool deleted");
      setConfirm(null);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409 && !confirm.force) {
        // mapped to agents → re-ask with force
        setConfirm({ id: confirm.id, force: true, body: `${err.message} Delete anyway?` });
      } else {
        toast.error(err.message ?? "Delete failed");
        setConfirm(null);
      }
    }
  };

  return (
    <>
      <PageHeader
        title="Tools"
        subtitle="Built-in tools + no-code HTTP tools (build one, or import an API spec). Map them to agents as skills."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setImportOpen(true)}>
              <FileJson className="h-4 w-4" /> Import API
            </Button>
            <Button onClick={openNew}>
              <Plus className="h-4 w-4" /> New HTTP tool
            </Button>
          </div>
        }
      />

      {isLoading ? (
        <ListSkeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Couldn't load tools." onRetry={refetch} />
      ) : data && data.items.length > 0 ? (
        <div className="space-y-2.5">
          {data.items.map((t) => (
            <Card
              key={t.id}
              onClick={() => {
                setEditTool(t);
                setEditorOpen(true);
              }}
              className="flex cursor-pointer items-center gap-4 px-4 py-3 transition hover:border-border-strong hover:bg-surface"
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface text-muted">
                <Wrench className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium">{t.name}</span>
                  <Badge tone={t.type === "builtin" ? "info" : "primary"}>{t.type}</Badge>
                </div>
                <p className="mt-0.5 truncate text-sm text-muted">{t.description || "—"}</p>
              </div>
              {t.type === "http" && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    askDelete(t);
                  }}
                  aria-label="Delete tool"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState title="No tools yet" hint="The 3 built-ins seed on startup; add your own HTTP tool with no code." />
      )}

      <ToolEditor open={editorOpen} onClose={() => setEditorOpen(false)} tool={editTool} />
      <ImportToolsModal open={importOpen} onClose={() => setImportOpen(false)} />
      <ConfirmDialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        onConfirm={doDelete}
        title="Delete tool?"
        body={confirm?.body ?? ""}
        confirmLabel={confirm?.force ? "Force delete" : "Delete"}
        destructive
      />
    </>
  );
}
