// Pure analytics for the Dashboard — derived entirely from the tenant-scoped runs/conversations
// the API already returns (every request carries X-Tenant-Id, so these numbers are per-org).
// Kept side-effect-free + `now` injectable so it can be unit-tested deterministically.
import type { Conversation, Run } from "@/api/types";

import { parseTs } from "./runFormat";

export interface RunPoint {
  id: number;
  label: string; // "#42"
  tokens: number;
  cost: number;
  status: Run["status"];
}

export interface DayPoint {
  key: string; // "2026-06-02"
  label: string; // "Jun 2"
  runs: number;
}

export interface DashboardStats {
  totalRuns: number; // true count from the API page (may exceed the sampled records)
  sampledRuns: number; // how many run records we actually summed (the page's items)
  totalTokens: number;
  totalCost: number;
  avgDurationMs: number | null; // wall-clock mean over runs that have ended
  completed: number;
  failed: number;
  active: number; // running + pending
  completionRate: number | null; // completed / finished(=completed+failed) — 0..1, null if none finished
  perRun: RunPoint[]; // chronological asc, capped to the most recent `maxPerRun`
  byDay: DayPoint[]; // last `days` calendar days, zero-filled, chronological
  conversations: number;
  conversationTokens: number;
}

const dayKey = (d: Date): string => {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
};

/** Last `days` calendar days (local), zero-filled, with each day's run count. */
function buildDayBuckets(runs: Run[], days: number, now: number): DayPoint[] {
  const counts = new Map<string, number>();
  for (const r of runs) {
    if (!r.started_at) continue;
    const d = parseTs(r.started_at);
    if (Number.isNaN(d.getTime())) continue;
    const k = dayKey(d);
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const base = new Date(now);
  base.setHours(0, 0, 0, 0);
  const out: DayPoint[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(base);
    d.setDate(base.getDate() - i);
    out.push({
      key: dayKey(d),
      label: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      runs: counts.get(dayKey(d)) ?? 0,
    });
  }
  return out;
}

/** Reduce the (tenant-scoped) runs + conversations into the dashboard's headline + chart series. */
export function computeDashboardStats(
  runs: Run[],
  totalRuns: number,
  conversations: Conversation[],
  totalConversations: number,
  opts: { days?: number; maxPerRun?: number; now?: number } = {},
): DashboardStats {
  const days = opts.days ?? 14;
  const maxPerRun = opts.maxPerRun ?? 24;
  const now = opts.now ?? Date.now();

  let totalTokens = 0;
  let totalCost = 0;
  let completed = 0;
  let failed = 0;
  let active = 0;
  let durSum = 0;
  let durN = 0;

  for (const r of runs) {
    totalTokens += r.total_tokens ?? 0;
    totalCost += r.est_cost ?? 0;
    if (r.status === "completed") completed += 1;
    else if (r.status === "failed") failed += 1;
    else active += 1;
    if (r.started_at && r.ended_at) {
      const ms = parseTs(r.ended_at).getTime() - parseTs(r.started_at).getTime();
      if (Number.isFinite(ms) && ms >= 0) {
        durSum += ms;
        durN += 1;
      }
    }
  }

  // the API returns runs newest-first → reverse to chronological, then keep the most recent N
  const chrono = [...runs].reverse();
  const perRun: RunPoint[] = chrono.slice(Math.max(0, chrono.length - maxPerRun)).map((r) => ({
    id: r.id,
    label: `#${r.id}`,
    tokens: r.total_tokens ?? 0,
    cost: r.est_cost ?? 0,
    status: r.status,
  }));

  let conversationTokens = 0;
  for (const c of conversations) conversationTokens += c.total_tokens ?? 0;

  const finished = completed + failed;
  return {
    totalRuns,
    sampledRuns: runs.length,
    totalTokens,
    totalCost,
    avgDurationMs: durN ? durSum / durN : null,
    completed,
    failed,
    active,
    completionRate: finished ? completed / finished : null,
    perRun,
    byDay: buildDayBuckets(runs, days, now),
    conversations: totalConversations,
    conversationTokens,
  };
}
