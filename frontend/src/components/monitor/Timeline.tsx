import type { EventEnvelope } from "@/api/types";
import { agentHue, cn } from "@/lib/cn";
import { type Tone, describeEvent, fmtDuration, fmtTime } from "@/lib/runFormat";

const DOT: Record<Tone, string> = {
  default: "bg-surface text-muted ring-border",
  primary: "bg-primary/15 text-primary ring-primary/30",
  success: "bg-success/15 text-success ring-success/30",
  warning: "bg-warning/15 text-warning ring-warning/30",
  destructive: "bg-destructive/15 text-destructive ring-destructive/30",
  info: "bg-info/15 text-info ring-info/30",
};

/** Vertical event timeline — one row per RunEvent, ordered by seq, color-coded by type. */
export function Timeline({ events }: { events: EventEnvelope[] }) {
  if (events.length === 0)
    return <p className="px-1 py-8 text-center text-sm text-muted">Waiting for the first event…</p>;

  return (
    <ol className="relative space-y-1 pl-1">
      {events.map((e, i) => {
        const v = describeEvent(e);
        const Icon = v.icon;
        const last = i === events.length - 1;
        return (
          <li key={`${e.seq}-${e.event_id ?? i}`} className="relative flex gap-3">
            {/* rail */}
            <div className="flex flex-col items-center">
              <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-full ring-1", DOT[v.tone])}>
                <Icon className="h-3.5 w-3.5" />
              </span>
              {!last && <span className="w-px flex-1 bg-border" />}
            </div>
            {/* body */}
            <div className="min-w-0 flex-1 pb-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5 text-sm font-medium">
                  {v.agent && (
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: `hsl(${agentHue(v.agent)} 60% 55%)` }}
                    />
                  )}
                  <span className="truncate">{v.label}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2 font-mono text-[11px] text-muted">
                  {v.ms != null && (
                    <span className="rounded bg-surface px-1.5 py-0.5 text-fg/80">{fmtDuration(v.ms)}</span>
                  )}
                  {fmtTime(e.ts)}
                </span>
              </div>
              {v.detail && <p className="mt-0.5 text-xs text-muted">{v.detail}</p>}
              {v.body && (
                <p className="mt-1 line-clamp-3 rounded-md border border-border bg-bg/50 px-2.5 py-1.5 text-xs text-fg/80">
                  {v.body}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
