import { Coins, DollarSign } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";

import type { EventEnvelope, Run } from "@/api/types";
import { AgentAvatar } from "@/components/ui/status";
import { deriveTotals, fmtCost, fmtTokens, tokenSeries } from "@/lib/runFormat";

const num = (p: Record<string, unknown>, k: string): number => (typeof p[k] === "number" ? (p[k] as number) : 0);
const str = (p: Record<string, unknown>, k: string): string => (typeof p[k] === "string" ? (p[k] as string) : "");

interface Row {
  agent: string;
  tokens: number;
  cost: number;
  model: string;
}

/** Token + cost meters. Headline reads run_total_tokens/run_est_cost (single source); the
 *  per-agent table is event-level detail; the sparkline tracks cumulative growth. */
export function TokenMeter({ events, run }: { events: EventEnvelope[]; run?: Run | null }) {
  const { tokens, cost } = deriveTotals(events, run);
  const series = tokenSeries(events);

  // per-agent breakdown (sums individual token_usage events — detail, not the headline source)
  const byAgent = new Map<string, Row>();
  for (const e of events) {
    if (e.type !== "token_usage") continue;
    const agent = str(e.payload, "agent_name") || "node";
    const row = byAgent.get(agent) ?? { agent, tokens: 0, cost: 0, model: str(e.payload, "model") };
    row.tokens += num(e.payload, "total_tokens");
    row.cost += num(e.payload, "est_cost_usd");
    row.model = str(e.payload, "model") || row.model;
    byAgent.set(agent, row);
  }
  const rows = [...byAgent.values()].sort((a, b) => b.tokens - a.tokens);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Meter icon={Coins} label="Total tokens" value={fmtTokens(tokens)} accent="text-primary" />
        <Meter icon={DollarSign} label="Est. cost" value={fmtCost(cost)} accent="text-success" />
      </div>

      {series.length > 1 && (
        <div className="rounded-lg border border-border bg-card p-3">
          <div className="mb-1 text-xs text-muted">Cumulative tokens</div>
          <div className="h-24">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series} margin={{ top: 4, right: 2, bottom: 0, left: 2 }}>
                <defs>
                  <linearGradient id="tokGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <YAxis hide domain={[0, "dataMax"]} />
                <Tooltip
                  cursor={{ stroke: "hsl(var(--border-strong))" }}
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelFormatter={(s) => `seq ${s}`}
                  formatter={(v) => [fmtTokens(Number(v)), "tokens"]}
                />
                <Area
                  type="monotone"
                  dataKey="total"
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  fill="url(#tokGrad)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {rows.length > 0 && (
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-3 py-2 text-xs font-medium text-muted">By agent</div>
          <ul className="divide-y divide-border">
            {rows.map((r) => (
              <li key={r.agent} className="flex items-center gap-3 px-3 py-2">
                <AgentAvatar name={r.agent} className="h-6 w-6 text-[10px]" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{r.agent}</div>
                  {r.model && <div className="truncate font-mono text-[11px] text-muted">{r.model}</div>}
                </div>
                <div className="text-right text-xs tabular-nums">
                  <div className="font-medium">{fmtTokens(r.tokens)} tok</div>
                  <div className="text-muted">{fmtCost(r.cost)}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Meter({
  icon: Icon,
  label,
  value,
  accent,
}: {
  icon: typeof Coins;
  label: string;
  value: string;
  accent: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-1.5 text-xs text-muted">
        <Icon className={`h-3.5 w-3.5 ${accent}`} /> {label}
      </div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
