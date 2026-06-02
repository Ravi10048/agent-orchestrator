import { Badge } from "@/components/ui/badge";
import { agentHue, cn } from "@/lib/cn";

const RUN_TONE: Record<string, "default" | "primary" | "success" | "warning" | "destructive" | "info"> = {
  pending: "default",
  running: "info",
  completed: "success",
  failed: "destructive",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={RUN_TONE[status] ?? "default"}>{status}</Badge>;
}

export function ProviderPill({ provider }: { provider: string }) {
  return <Badge tone="primary" className="font-mono">{provider}</Badge>;
}

export function ConnectionDot({ status }: { status: "connecting" | "open" | "closed" }) {
  const color = status === "open" ? "bg-success" : status === "connecting" ? "bg-warning" : "bg-destructive";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <span className={cn("h-2 w-2 rounded-full", color, status === "connecting" && "animate-pulse")} />
      {status}
    </span>
  );
}

/** Colored avatar/dot for an agent — stable color per name. */
export function AgentAvatar({ name, className }: { name: string; className?: string }) {
  const hue = agentHue(name);
  return (
    <span
      className={cn("inline-flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold text-white", className)}
      style={{ backgroundColor: `hsl(${hue} 60% 45%)` }}
      title={name}
    >
      {name.slice(0, 2).toUpperCase()}
    </span>
  );
}
