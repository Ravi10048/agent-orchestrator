import { Bot, CalendarClock, MessageSquare, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import type { ApiError } from "@/api/client";
import { AgentEditor } from "@/components/AgentEditor";
import { ChatBench } from "@/components/ChatBench";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/ui/feedback";
import { ConfirmDialog } from "@/components/ui/modal";
import { AgentAvatar, ProviderPill } from "@/components/ui/status";
import { useAgentMutations, useAgents } from "@/hooks/queries";
import { toast } from "@/lib/toast";

export default function AgentsPage() {
  const { data, isLoading, isError, refetch } = useAgents();
  const { remove } = useAgentMutations();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [chatAgent, setChatAgent] = useState<{ id: number; name: string } | null>(null);

  const openNew = () => {
    setEditId(null);
    setEditorOpen(true);
  };
  const openEdit = (id: number) => {
    setEditId(id);
    setEditorOpen(true);
  };

  const doDelete = async (id: number) => {
    try {
      await remove.mutateAsync(id);
      toast.success("Agent deleted");
    } catch (e) {
      toast.error((e as ApiError).message ?? "Delete failed");
    }
  };

  return (
    <>
      <PageHeader
        title="Agents"
        subtitle="Create agents and configure every dimension."
        actions={
          <Button onClick={openNew}>
            <Plus className="h-4 w-4" /> New agent
          </Button>
        }
      />

      {isLoading ? (
        <ListSkeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Couldn't load agents." onRetry={refetch} />
      ) : data && data.items.length > 0 ? (
        <div className="space-y-2.5">
          {data.items.map((a) => (
            <Card
              key={a.id}
              onClick={() => openEdit(a.id)}
              className="flex cursor-pointer items-center gap-4 px-4 py-3 transition hover:border-border-strong hover:bg-surface"
            >
              <AgentAvatar name={a.name} className="h-9 w-9 text-xs" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{a.name}</span>
                  {a.role && <span className="truncate text-sm text-muted">· {a.role}</span>}
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <ProviderPill provider={a.provider} />
                  <span className="font-mono text-xs text-muted">{a.model}</span>
                  {a.schedule && (a.schedule as { enabled?: boolean }).enabled && (
                    <span className="inline-flex items-center gap-1 text-xs text-info">
                      <CalendarClock className="h-3 w-3" /> scheduled
                    </span>
                  )}
                </div>
              </div>
              <span className="text-xs text-muted">{a.tools.length} tools</span>
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.stopPropagation();
                  setChatAgent({ id: a.id, name: a.name });
                }}
                aria-label="Chat with agent"
                title="Chat"
              >
                <MessageSquare className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.stopPropagation();
                  setConfirmId(a.id);
                }}
                aria-label="Delete agent"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No agents yet"
          hint="Create your first agent, or run a template (it seeds a set of agents)."
          action={
            <Button onClick={openNew}>
              <Bot className="h-4 w-4" /> Create your first agent
            </Button>
          }
        />
      )}

      <AgentEditor open={editorOpen} onClose={() => setEditorOpen(false)} agentId={editId} />
      <ChatBench
        open={chatAgent !== null}
        onClose={() => setChatAgent(null)}
        agentId={chatAgent?.id ?? 0}
        agentName={chatAgent?.name ?? ""}
      />
      <ConfirmDialog
        open={confirmId !== null}
        onClose={() => setConfirmId(null)}
        onConfirm={() => confirmId && doDelete(confirmId)}
        title="Delete agent?"
        body="This removes the agent and its tool mappings. This cannot be undone."
        confirmLabel="Delete"
        destructive
      />
    </>
  );
}
