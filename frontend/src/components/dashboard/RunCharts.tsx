import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/ui/card";
import type { DashboardStats, DayPoint, RunPoint } from "@/lib/dashboardStats";
import { fmtCost, fmtTokens } from "@/lib/runFormat";

// ── shared chrome ─────────────────────────────────────────────────────────
const AXIS = { fontSize: 10, fill: "hsl(var(--muted))" } as const;
const GRID = "hsl(var(--border))";

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <div className="mb-3">
        <div className="text-sm font-semibold tracking-tight">{title}</div>
        {subtitle && <div className="mt-0.5 text-[11px] text-muted">{subtitle}</div>}
      </div>
      {children}
    </Card>
  );
}

function RunTip({ active, payload }: { active?: boolean; payload?: Array<{ payload: RunPoint }> }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs shadow-lg">
      <div className="font-medium">Run {d.label}</div>
      <div className="text-muted">
        {fmtTokens(d.tokens)} tok · {fmtCost(d.cost)}
      </div>
      <div className="capitalize text-muted">{d.status}</div>
    </div>
  );
}

function DayTip({ active, payload }: { active?: boolean; payload?: Array<{ payload: DayPoint }> }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs shadow-lg">
      <div className="font-medium">{d.label}</div>
      <div className="text-muted">
        {d.runs} run{d.runs === 1 ? "" : "s"}
      </div>
    </div>
  );
}

// ── the three charts ──────────────────────────────────────────────────────
export function RunCharts({ stats }: { stats: DashboardStats }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard title="Tokens & cost per run" subtitle="most recent runs · hover for cost">
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={stats.perRun} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="dashTok" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis hide domain={[0, "dataMax"]} />
              <Tooltip cursor={{ stroke: "hsl(var(--border-strong))" }} content={<RunTip />} />
              <Area
                type="monotone"
                dataKey="tokens"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                fill="url(#dashTok)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <ChartCard title="Runs over time" subtitle="last 14 days">
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={stats.byDay} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval={3} />
              <YAxis hide allowDecimals={false} domain={[0, "dataMax"]} />
              <Tooltip cursor={{ fill: "hsl(var(--primary) / 0.08)" }} content={<DayTip />} />
              <Bar dataKey="runs" radius={[4, 4, 0, 0]} fill="hsl(var(--primary))" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <ChartCard title="Completion rate" subtitle="completed ÷ finished runs">
        <CompletionGauge stats={stats} />
      </ChartCard>
    </div>
  );
}

function CompletionGauge({ stats }: { stats: DashboardStats }) {
  const pct = stats.completionRate == null ? 0 : Math.round(stats.completionRate * 100);
  const display = stats.completionRate == null ? "—" : `${pct}%`;
  const fill =
    stats.completionRate == null
      ? "hsl(var(--muted))"
      : pct >= 80
        ? "hsl(var(--success))"
        : pct >= 50
          ? "hsl(var(--warning))"
          : "hsl(var(--destructive))";

  return (
    <div>
      <div className="relative h-32">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            data={[{ value: pct }]}
            innerRadius="72%"
            outerRadius="100%"
            startAngle={90}
            endAngle={-270}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar dataKey="value" cornerRadius={10} fill={fill} background={{ fill: "hsl(var(--border))" }} isAnimationActive={false} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <div className="text-center">
            <div className="text-2xl font-semibold tabular-nums">{display}</div>
            <div className="text-[10px] text-muted">{stats.completed + stats.failed} finished</div>
          </div>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-center gap-3 text-[11px] text-muted">
        <Legend color="hsl(var(--success))" label={`${stats.completed} done`} />
        <Legend color="hsl(var(--destructive))" label={`${stats.failed} failed`} />
        <Legend color="hsl(var(--warning))" label={`${stats.active} active`} />
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} /> {label}
    </span>
  );
}
