import { MessagesSquare } from "lucide-react";

import type { EventEnvelope } from "@/api/types";
import { AgentAvatar } from "@/components/ui/status";
import { agentHue } from "@/lib/cn";
import { fmtTime } from "@/lib/runFormat";

const text = (p: Record<string, unknown>, k: string): string => (typeof p[k] === "string" ? (p[k] as string) : "");

/** Inter-agent message thread — `agent_message` events (peer send_message), tinted per sender. */
export function AgentThread({ events }: { events: EventEnvelope[] }) {
  const msgs = events.filter((e) => e.type === "agent_message");

  if (msgs.length === 0)
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
        <MessagesSquare className="h-6 w-6 text-muted" />
        <p className="text-sm text-muted">No inter-agent messages yet.</p>
        <p className="max-w-xs text-xs text-muted/80">
          These appear when an agent uses <code className="font-mono">send_message</code> to talk to a peer. Handoffs
          show on the Timeline.
        </p>
      </div>
    );

  return (
    <div className="space-y-3">
      {msgs.map((e, i) => {
        const from = text(e.payload, "from_agent") || "?";
        const to = text(e.payload, "to_agent");
        const hue = agentHue(from);
        return (
          <div
            key={`${e.seq}-${i}`}
            className="rounded-lg border border-border bg-card p-3"
            style={{ borderLeft: `3px solid hsl(${hue} 60% 55%)` }}
          >
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="flex items-center gap-1.5 font-medium">
                <AgentAvatar name={from} className="h-5 w-5 text-[9px]" />
                {from}
                <span className="text-muted">→</span>
                {to === "*" ? <span className="text-muted">all agents</span> : <span>{to || "?"}</span>}
                {to === "*" && (
                  <span className="rounded bg-info/10 px-1.5 py-0.5 text-[10px] font-medium text-info">broadcast</span>
                )}
              </span>
              <span className="font-mono text-[11px] text-muted">{fmtTime(e.ts)}</span>
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-fg/90">{text(e.payload, "content_preview")}</p>
          </div>
        );
      })}
    </div>
  );
}
