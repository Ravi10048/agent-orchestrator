import { CornerDownLeft, Loader2, Split, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { ApiError } from "@/api/client";
import { Conversations } from "@/api/resources";
import { Modal } from "@/components/ui/modal";
import { AgentAvatar } from "@/components/ui/status";
import { agentHue, cn } from "@/lib/cn";
import { getLastChatId, saveLastChatId } from "@/lib/prefs";
import { fmtTokens } from "@/lib/runFormat";

interface ToolUse {
  tool: string;
  ok: boolean;
}
interface Turn {
  role: "user" | "assistant";
  content: string;
  meta?: string;
  error?: boolean;
  tools?: ToolUse[];
  author?: string; // assistant turn: who produced it (the routed specialist, or the agent)
  routedFrom?: string | null; // set when this turn re-routed to a different specialist
}

/** Info about one completed assistant turn — emitted to the parent so a workflow chat can drive a
 *  live graph + cockpit (which specialist answered, whether it re-routed, tools, tokens, the message). */
export interface ChatTurnInfo {
  author: string;
  routedFrom?: string | null;
  tools: ToolUse[];
  tokens?: number; // total tokens this turn (router + specialist)
  input?: string; // the user message that drove this turn
  reason?: string; // stopped_reason
}

/** The chat body — multi-turn against an agent (1:1) OR a WORKFLOW (routed per turn). Backed by
 *  POST /conversations/chat, so it REMEMBERS the conversation, persists the transcript (visible in
 *  Conversations), routes each turn through the workflow's supervisor, and can call tools mid-chat.
 *  Reused by the ChatBench modal AND the full-page WorkflowChat playground. */
export function ChatSession({
  agentId,
  workflowId,
  headerName,
  onTurn,
  onBusyChange,
  fill = false,
  showTelegramField = true,
}: {
  agentId?: number;
  workflowId?: number;
  headerName: string;
  onTurn?: (t: ChatTurnInfo) => void;
  onBusyChange?: (busy: boolean) => void;
  fill?: boolean; // true → the message list flex-fills its parent (page); false → fixed height (modal)
  showTelegramField?: boolean;
}) {
  const routed = workflowId != null;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [chatId, setChatId] = useState(() => getLastChatId());
  const [convId, setConvId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [turns, busy]);
  useEffect(() => onBusyChange?.(busy), [busy, onBusyChange]);

  const lastAuthor = [...turns].reverse().find((t) => t.role === "assistant" && !t.error)?.author;

  const send = async () => {
    const message = text.trim();
    if (!message || busy) return;
    if (chatId.trim()) saveLastChatId(chatId);
    setText("");
    setTurns((t) => [...t, { role: "user", content: message }]);
    setBusy(true);
    try {
      const fresh = convId == null;
      const r = await Conversations.chat({
        message,
        // first turn binds the chat: a workflow (routed) OR a single agent (1:1); then continue by id
        agent_id: fresh && !routed ? agentId : undefined,
        workflow_id: fresh && routed ? workflowId : undefined,
        conversation_id: convId ?? undefined,
        chat_id: chatId.trim() || undefined,
      });
      setConvId(r.conversation_id);
      const author = r.active_agent ?? headerName;
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content: r.reply,
          tools: r.tools,
          author,
          routedFrom: r.routed_from,
          meta: `${fmtTokens(r.total_tokens)} tok · ${r.stopped_reason}`,
        },
      ]);
      onTurn?.({ author, routedFrom: r.routed_from, tools: r.tools, tokens: r.total_tokens, input: message, reason: r.stopped_reason });
    } catch (e) {
      setTurns((t) => [
        ...t,
        { role: "assistant", content: (e as ApiError).message ?? "Request failed", error: true },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn("flex flex-col", fill && "min-h-0 flex-1")}>
      {showTelegramField && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-border bg-surface/40 px-3 py-1.5 text-xs">
          <span className="shrink-0 text-muted">Telegram chat id</span>
          <input
            value={chatId}
            onChange={(e) => setChatId(e.target.value)}
            placeholder="optional — lets send_telegram deliver here"
            className="h-7 flex-1 rounded-md border border-border bg-bg px-2 text-xs placeholder:text-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
          />
        </div>
      )}

      <div ref={scroller} className={cn("space-y-3 overflow-y-auto scroll-thin pr-1", fill ? "min-h-0 flex-1" : "h-[42vh]")}>
        {turns.length === 0 && !busy && (
          <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-2 text-center">
            <AgentAvatar name={headerName} className="h-10 w-10 text-sm" />
            <p className="text-sm font-medium">Start a conversation with {headerName}</p>
            <p className="max-w-xs text-xs text-muted">
              {routed
                ? "Each message is routed through the supervisor to the best specialist — watch the graph light up as it routes."
                : "Runs the real agent loop with memory across turns. It can call its tools — set a Telegram chat id above to let it deliver there."}
            </p>
          </div>
        )}
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm text-primary-fg">
                {t.content}
              </div>
            </div>
          ) : (
            <AssistantTurn key={i} turn={t} fallbackName={headerName} />
          ),
        )}
        {busy && (
          <div className="flex items-center gap-2 px-1 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> {routed ? "Routing" : `${lastAuthor ?? headerName} is thinking`}…
          </div>
        )}
      </div>

      <div className="mt-3 flex items-end gap-2 border-t border-border pt-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={1}
          placeholder="Message… (Enter to send, Shift+Enter for newline)"
          className="max-h-32 min-h-[40px] flex-1 resize-none rounded-lg border border-border bg-bg px-3 py-2 text-sm placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
        />
        <button
          onClick={send}
          disabled={busy || !text.trim()}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-primary text-primary-fg shadow-glow transition hover:brightness-110 disabled:opacity-50"
          aria-label="Send"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CornerDownLeft className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}

/** Modal wrapper around ChatSession — used for an AGENT 1:1 chat (Agents page) and as a quick
 *  workflow chat. The full split-screen experience lives in the WorkflowChat page. */
export function ChatBench({
  open,
  onClose,
  agentId,
  agentName,
  workflowId,
  workflowName,
}: {
  open: boolean;
  onClose: () => void;
  agentId?: number;
  agentName?: string;
  workflowId?: number;
  workflowName?: string;
}) {
  const routed = workflowId != null;
  const headerName = (routed ? workflowName : agentName) ?? "Assistant";
  const [active, setActive] = useState<string | undefined>();

  useEffect(() => {
    if (open) setActive(undefined);
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          {`Chat · ${headerName}`}
          {routed && active && (
            <span className="inline-flex items-center gap-1 rounded-full bg-info/10 px-2 py-0.5 text-[11px] font-medium text-info">
              <Split className="h-3 w-3" /> now with {active}
            </span>
          )}
        </span>
      }
      description={
        routed
          ? "Routed per turn — the supervisor reads each message and picks the right specialist to answer."
          : "Multi-turn — the agent remembers this conversation and can use its tools."
      }
      size="lg"
    >
      {open && (
        <ChatSession
          key={`${agentId ?? "a"}-${workflowId ?? "w"}`}
          agentId={agentId}
          workflowId={workflowId}
          headerName={headerName}
          onTurn={(t) => setActive(t.author)}
        />
      )}
    </Modal>
  );
}

/** One assistant bubble, rendered by its ACTUAL author (the routed specialist) so a workflow chat
 *  visibly shows who answered; a "routed from X" chip marks a hand-off to a different specialist. */
function AssistantTurn({ turn, fallbackName }: { turn: Turn; fallbackName: string }) {
  const author = turn.author ?? fallbackName;
  const hue = agentHue(author);
  const rerouted = !turn.error && turn.routedFrom != null && turn.routedFrom !== author;
  return (
    <div className="flex gap-2">
      <AgentAvatar name={turn.error ? fallbackName : author} className="mt-0.5 h-7 w-7 text-[10px]" />
      <div className="min-w-0 max-w-[85%]">
        {!turn.error && (
          <div className="mb-0.5 flex items-center gap-1.5 px-1">
            <span className="text-[11px] font-medium text-fg/80">{author}</span>
            {rerouted && (
              <span className="inline-flex items-center gap-1 rounded bg-info/10 px-1.5 py-0.5 text-[10px] font-medium text-info">
                <Split className="h-2.5 w-2.5" /> routed from {turn.routedFrom}
              </span>
            )}
          </div>
        )}
        <div
          className={cn(
            "whitespace-pre-wrap rounded-2xl rounded-tl-sm border px-3.5 py-2 text-sm",
            turn.error
              ? "border-destructive/30 bg-destructive/5 text-destructive"
              : "border-border bg-card text-fg/90",
          )}
          style={turn.error ? undefined : { borderLeft: `3px solid hsl(${hue} 60% 55%)` }}
        >
          {turn.content}
        </div>
        {turn.tools && turn.tools.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1 px-1">
            {turn.tools.map((tl, j) => (
              <span
                key={j}
                className={cn(
                  "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium",
                  tl.ok ? "bg-info/10 text-info" : "bg-destructive/10 text-destructive",
                )}
              >
                <Wrench className="h-2.5 w-2.5" />
                {tl.tool}
                {!tl.ok && " ✕"}
              </span>
            ))}
          </div>
        )}
        {turn.meta && <div className="mt-1 px-1 font-mono text-[11px] text-muted">{turn.meta}</div>}
      </div>
    </div>
  );
}
