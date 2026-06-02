import { useQuery } from "@tanstack/react-query";
import { ListTree, MessagesSquare, Share2 } from "lucide-react";
import { Suspense, lazy, useEffect, useState } from "react";

import { Conversations } from "@/api/resources";
import type { Conversation, Message } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, ListSkeleton, Spinner } from "@/components/ui/feedback";
import { AgentAvatar } from "@/components/ui/status";
import { useAgents, useConversations, useHealth } from "@/hooks/queries";
import { agentHue, cn } from "@/lib/cn";
import { fmtAgo, fmtTime, fmtTokens } from "@/lib/runFormat";

// lazy — React Flow only loads when the user opens the Flow view
const ConversationFlow = lazy(() => import("@/components/conversation/ConversationFlow"));

export default function ConversationsPage() {
  const { data, isLoading, isError, refetch } = useConversations();
  const agents = useAgents();
  const health = useHealth();
  const [selected, setSelected] = useState<number | null>(null);

  const items = data?.items ?? [];
  useEffect(() => {
    if (selected == null && items.length) setSelected(items[0].id);
  }, [items, selected]);

  const agentName = (id: number) => agents.data?.items.find((a) => a.id === id)?.name ?? `agent ${id}`;
  const current = items.find((c) => c.id === selected) ?? null;

  return (
    <>
      <PageHeader title="Conversations" subtitle="Channel chats (e.g. Telegram) with full persisted history." />

      {isLoading ? (
        <ListSkeleton rows={4} />
      ) : isError ? (
        <ErrorState message="Couldn't load conversations." onRetry={refetch} />
      ) : items.length === 0 ? (
        <EmptyState
          title="No conversations yet"
          hint={
            health.data?.telegram_present
              ? "Telegram is connected. Open your bot in Telegram, send it a message, and the chat appears here with full history."
              : "Set TELEGRAM_BOT_TOKEN (from @BotFather) and restart, then message your bot — the chat appears here with full history."
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-[300px_1fr]">
          {/* list */}
          <Card className="divide-y divide-border overflow-hidden">
            {items.map((c) => (
              <button
                key={c.id}
                onClick={() => setSelected(c.id)}
                className={cn(
                  "flex w-full items-center gap-3 px-3 py-2.5 text-left transition hover:bg-surface",
                  selected === c.id && "bg-surface",
                )}
              >
                <AgentAvatar name={agentName(c.agent_id)} className="h-8 w-8 text-[10px]" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{c.title || `Chat ${c.external_id}`}</div>
                  <div className="flex items-center gap-1.5 text-xs text-muted">
                    <span className="capitalize">{c.channel}</span> · {fmtAgo(c.last_at)}
                  </div>
                </div>
              </button>
            ))}
          </Card>

          {/* transcript */}
          {current ? <Transcript conv={current} agentName={agentName(current.agent_id)} /> : null}
        </div>
      )}
    </>
  );
}

function Transcript({ conv, agentName }: { conv: Conversation; agentName: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["conversation", conv.id, "messages"],
    queryFn: () => Conversations.messages(conv.id),
  });
  const msgs = data?.items ?? [];
  const [view, setView] = useState<"transcript" | "flow">("transcript");
  // a routed chat persists each reply under its specialist (from_agent); show that author so the
  // transcript visibly reflects per-turn routing (fall back to the conv's agent for 1:1 / system).
  const authorOf = (m: Message) =>
    m.from_agent && m.from_agent !== "user" && m.from_agent !== "system" ? m.from_agent : agentName;

  const empty = (
    <div className="flex flex-col items-center gap-2 py-10 text-center text-muted">
      <MessagesSquare className="h-5 w-5" />
      <p className="text-sm">No messages in this conversation yet.</p>
    </div>
  );

  return (
    <Card className="flex max-h-[78vh] flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <AgentAvatar name={agentName} className="h-8 w-8 text-[10px]" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{conv.title || `Chat ${conv.external_id}`}</div>
            <div className="text-xs text-muted">
              {agentName} · <span className="capitalize">{conv.channel}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Transcript | Flow toggle */}
          <div className="flex items-center gap-0.5 rounded-lg border border-border p-0.5">
            <button
              onClick={() => setView("transcript")}
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition",
                view === "transcript" ? "bg-surface text-fg" : "text-muted hover:text-fg",
              )}
            >
              <ListTree className="h-3.5 w-3.5" /> Transcript
            </button>
            <button
              onClick={() => setView("flow")}
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition",
                view === "flow" ? "bg-surface text-fg" : "text-muted hover:text-fg",
              )}
            >
              <Share2 className="h-3.5 w-3.5" /> Flow
            </button>
          </div>
          <Badge tone="default" className="tabular-nums">
            {fmtTokens(conv.total_tokens)} tok
          </Badge>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner className="h-5 w-5" />
        </div>
      ) : msgs.length === 0 ? (
        empty
      ) : view === "flow" ? (
        <Suspense
          fallback={
            <div className="grid h-[58vh] place-items-center">
              <Spinner className="h-5 w-5" />
            </div>
          }
        >
          <ConversationFlow messages={msgs} agentName={agentName} />
        </Suspense>
      ) : (
        <div className="flex-1 space-y-3 overflow-y-auto scroll-thin px-4 py-4">
          {msgs.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex flex-col items-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm text-primary-fg">
                  {m.content}
                </div>
                <span className="mt-0.5 px-1 text-[11px] text-muted">{fmtTime(m.created_at)}</span>
              </div>
            ) : (
              (() => {
                const author = authorOf(m);
                return (
                  <div key={m.id} className="flex gap-2">
                    <AgentAvatar name={author} className="mt-0.5 h-7 w-7 text-[10px]" />
                    <div className="min-w-0 max-w-[80%]">
                      {author !== agentName && (
                        <span className="mb-0.5 block px-1 text-[11px] font-medium text-fg/80">{author}</span>
                      )}
                      <div
                        className="whitespace-pre-wrap rounded-2xl rounded-tl-sm border border-border bg-card px-3.5 py-2 text-sm text-fg/90"
                        style={{ borderLeft: `3px solid hsl(${agentHue(author)} 60% 55%)` }}
                      >
                        {m.content}
                      </div>
                      <span className="mt-0.5 px-1 text-[11px] text-muted">{fmtTime(m.created_at)}</span>
                    </div>
                  </div>
                );
              })()
            ),
          )}
        </div>
      )}
    </Card>
  );
}
