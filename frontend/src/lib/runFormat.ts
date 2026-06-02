import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  CircleDot,
  Coins,
  Flag,
  type LucideIcon,
  PlayCircle,
  Wrench,
} from "lucide-react";

import type { EventEnvelope, Run } from "@/api/types";

export type Tone = "default" | "primary" | "success" | "warning" | "destructive" | "info";

// ── primitives ─────────────────────────────────────────────────────────
const str = (p: Record<string, unknown>, k: string): string | undefined => {
  const v = p[k];
  return typeof v === "string" && v.length ? v : undefined;
};
const num = (p: Record<string, unknown>, k: string): number | undefined => {
  const v = p[k];
  return typeof v === "number" ? v : undefined;
};

export const fmtTokens = (n: number): string => n.toLocaleString("en-US");

export const fmtCost = (n: number): string => {
  if (!n) return "$0";
  return n < 0.01 ? `$${n.toFixed(5)}` : `$${n.toFixed(4)}`;
};

export const fmtDuration = (ms: number): string =>
  ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s` : `${Math.round(ms)}ms`;

/** Parse a backend timestamp. ALL backend times are UTC, but some are serialized without a
 *  timezone suffix (naive) — JS `new Date()` would read those as LOCAL and drift by the offset.
 *  So treat a tz-less string as UTC by appending "Z". */
export const parseTs = (iso: string): Date => {
  const hasTz = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`);
};

export const fmtTime = (iso: string | null): string => {
  if (!iso) return "";
  const d = parseTs(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-US", { hour12: false });
};

export const fmtAgo = (iso: string | null): string => {
  if (!iso) return "";
  const d = parseTs(iso).getTime();
  if (Number.isNaN(d)) return "";
  const s = Math.max(0, Math.round((Date.now() - d) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
};

// ── status (derived from the event stream — the single source while live) ─
const ACTIVE = new Set(["pending", "running"]);

/** Final status if `run_finished` arrived, else "running" once started, else the persisted value. */
export function deriveStatus(events: EventEnvelope[], fallback = "pending"): string {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === "run_finished") return str(events[i].payload, "status") ?? "completed";
  }
  if (events.some((e) => e.type === "run_started")) return "running";
  return fallback;
}

export const isActive = (status: string): boolean => ACTIVE.has(status);

/** Token + cost totals from the event stream (`run_total_tokens`/`run_est_cost` — never client-summed). */
export function deriveTotals(events: EventEnvelope[], run?: Run | null): { tokens: number; cost: number } {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "run_finished") {
      return {
        tokens: num(e.payload, "total_tokens") ?? run?.total_tokens ?? 0,
        cost: num(e.payload, "est_cost") ?? run?.est_cost ?? 0,
      };
    }
    if (e.type === "token_usage") {
      return {
        tokens: num(e.payload, "run_total_tokens") ?? 0,
        cost: num(e.payload, "run_est_cost") ?? 0,
      };
    }
  }
  return { tokens: run?.total_tokens ?? 0, cost: run?.est_cost ?? 0 };
}

/** Cumulative-token series for the sparkline (one point per token_usage event). */
export function tokenSeries(events: EventEnvelope[]): { seq: number; total: number }[] {
  return events
    .filter((e) => e.type === "token_usage")
    .map((e) => ({ seq: e.seq, total: num(e.payload, "run_total_tokens") ?? 0 }));
}

// ── event presentation (one place; reused by the timeline) ───────────────
export interface EventView {
  icon: LucideIcon;
  tone: Tone;
  label: string;
  detail?: string;
  body?: string; // longer preview, shown muted/clamped
  agent?: string;
  ms?: number;
}

export function describeEvent(e: EventEnvelope): EventView {
  const p = e.payload;
  switch (e.type) {
    case "run_started":
      return {
        icon: PlayCircle,
        tone: "info",
        label: "Run started",
        detail: [num(p, "node_count") && `${num(p, "node_count")} nodes`, str(p, "trigger") && `via ${str(p, "trigger")}`]
          .filter(Boolean)
          .join(" · "),
        body: str(p, "input_preview"),
      };
    case "node_started": {
      const agent = str(p, "agent_name");
      const type = str(p, "node_type") ?? "node";
      return {
        icon: CircleDot,
        tone: "default",
        label: agent ? `${agent} started` : `${type} "${str(p, "node_id") ?? ""}" started`,
        detail: [num(p, "step") && `step ${num(p, "step")}`, (num(p, "visit") ?? 0) > 1 && `visit ${num(p, "visit")}`]
          .filter(Boolean)
          .join(" · "),
        agent,
      };
    }
    case "node_finished": {
      if (str(p, "note") === "dead_end_terminal")
        return { icon: Flag, tone: "warning", label: "Dead end — graceful stop", detail: str(p, "node_id") };
      const agent = str(p, "agent_name");
      const type = str(p, "node_type") ?? "node";
      const route = str(p, "route");
      return {
        icon: CheckCircle2,
        tone: "success",
        label: agent ? `${agent} finished` : `${type} "${str(p, "node_id") ?? ""}" finished`,
        detail: [
          str(p, "stopped_reason") && `stop: ${str(p, "stopped_reason")}`,
          route && `→ ${route}`,
          num(p, "tokens") != null && `${fmtTokens(num(p, "tokens")!)} tok`,
        ]
          .filter(Boolean)
          .join(" · "),
        body: str(p, "text_preview"),
        agent,
        ms: num(p, "duration_ms"),
      };
    }
    case "agent_message": {
      const from = str(p, "from_agent") ?? "?";
      const to = str(p, "to_agent");
      return {
        icon: ArrowRightLeft,
        tone: "primary",
        label: `${from} → ${to === "*" ? "all agents" : (to ?? "?")}`,
        body: str(p, "content_preview"),
        agent: from,
      };
    }
    case "tool_call": {
      const ok = p.ok !== false;
      return {
        icon: Wrench,
        tone: ok ? "info" : "destructive",
        label: `${str(p, "tool") ?? "tool"} ${ok ? "called" : "failed"}`,
        detail: [
          str(p, "agent_name"),
          num(p, "latency_ms") != null && `${fmtDuration(num(p, "latency_ms")!)}`,
        ]
          .filter(Boolean)
          .join(" · "),
        body: ok ? undefined : str(p, "error"),
        agent: str(p, "agent_name"),
      };
    }
    case "token_usage": {
      const agent = str(p, "agent_name");
      return {
        icon: Coins,
        tone: "default",
        label: `${agent ?? "node"} · ${fmtTokens(num(p, "total_tokens") ?? 0)} tok`,
        detail: [str(p, "model"), num(p, "run_total_tokens") != null && `run total ${fmtTokens(num(p, "run_total_tokens")!)}`]
          .filter(Boolean)
          .join(" · "),
        agent,
      };
    }
    case "error":
      return {
        icon: AlertTriangle,
        tone: "destructive",
        label: `Error · ${str(p, "scope") ?? "run"}`,
        detail: str(p, "node_id") ?? str(p, "agent_name"),
        body: str(p, "error"),
        agent: str(p, "agent_name"),
      };
    case "run_finished": {
      const status = str(p, "status") ?? "completed";
      const ok = status === "completed";
      return {
        icon: Flag,
        tone: ok ? "success" : "destructive",
        label: `Run ${status}`,
        detail: [
          num(p, "total_tokens") != null && `${fmtTokens(num(p, "total_tokens")!)} tok`,
          num(p, "duration_ms") != null && fmtDuration(num(p, "duration_ms")!),
        ]
          .filter(Boolean)
          .join(" · "),
        body: str(p, "error") ?? str(p, "output_preview"),
        ms: num(p, "duration_ms"),
      };
    }
    default:
      return { icon: CircleDot, tone: "default", label: e.type };
  }
}
