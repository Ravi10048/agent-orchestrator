import { Coins, DollarSign, MessagesSquare, Timer } from "lucide-react";

import { Card } from "@/components/ui/card";
import type { DashboardStats } from "@/lib/dashboardStats";
import { fmtCost, fmtDuration, fmtTokens } from "@/lib/runFormat";

/** Live operational metrics for the active tenant — total LLM spend, throughput, latency, chat
 *  volume. All derived from the tenant-scoped runs/conversations (no fabricated numbers). */
export function MetricStrip({ stats }: { stats: DashboardStats }) {
  // be honest if the runs page is truncated (default API limit is 50): the sums cover the sample
  const sampleHint =
    stats.totalRuns > stats.sampledRuns
      ? `last ${stats.sampledRuns} of ${stats.totalRuns} runs`
      : `${stats.sampledRuns} run${stats.sampledRuns === 1 ? "" : "s"}`;

  const cards = [
    { icon: Coins, label: "Total tokens", value: fmtTokens(stats.totalTokens), hint: `across ${sampleHint}`, accent: "text-primary" },
    { icon: DollarSign, label: "Est. cost", value: fmtCost(stats.totalCost), hint: "LLM spend (estimated)", accent: "text-success" },
    {
      icon: Timer,
      label: "Avg run duration",
      value: stats.avgDurationMs == null ? "—" : fmtDuration(stats.avgDurationMs),
      hint: "wall-clock, finished runs",
      accent: "text-info",
    },
    {
      icon: MessagesSquare,
      label: "Conversations",
      value: String(stats.conversations),
      hint: stats.conversationTokens ? `${fmtTokens(stats.conversationTokens)} tok` : "chat + channels",
      accent: "text-warning",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {cards.map((c) => {
        const Icon = c.icon;
        return (
          <Card key={c.label} className="p-4">
            <div className="flex items-center gap-1.5 text-xs text-muted">
              <Icon className={`h-3.5 w-3.5 ${c.accent}`} /> {c.label}
            </div>
            <div className="mt-2 text-2xl font-semibold tabular-nums">{c.value}</div>
            <div className="mt-1 text-[11px] leading-snug text-muted">{c.hint}</div>
          </Card>
        );
      })}
    </div>
  );
}
