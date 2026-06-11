import { Gauge, Layers, Send, Timer } from "lucide-react";

import { Card } from "@/components/ui/card";
import { computeDashboardStats } from "@/lib/dashboardStats";
import { useRuns } from "@/hooks/queries";

// the configurable dimensions exposed per agent (mirrors the agent editor)
const DIMENSIONS = 9; // role · system prompt · provider · model · tools · channels · memory · guardrails · schedule

/** Surfaces the four "Impact Metrics" — so the platform's value is legible
 *  at a glance. Completion rate is live (from runs, via the shared stats helper so it matches the
 *  Dashboard gauge); the others are platform properties. */
export function ImpactPanel() {
  const runs = useRuns();
  const page = runs.data;
  const stats = computeDashboardStats(page?.items ?? [], page?.total ?? 0, [], 0);
  const finished = stats.completed + stats.failed;
  const rate = stats.completionRate == null ? null : Math.round(stats.completionRate * 100);

  const cards = [
    {
      icon: Layers,
      label: "Config dimensions / agent",
      value: String(DIMENSIONS),
      hint: "role · prompt · model · tools · channels · memory · guardrails · schedule",
    },
    { icon: Timer, label: "Time to first workflow", value: "2 clicks", hint: "Templates → Use → Run" },
    {
      icon: Gauge,
      label: "Task completion rate",
      value: rate == null ? "—" : `${rate}%`,
      hint: finished ? `${stats.completed}/${finished} finished runs` : "no finished runs yet",
    },
    {
      icon: Send,
      label: "Agent-to-agent delivery",
      value: "at-least-once",
      hint: "in-process bus + persisted messages",
    },
  ];

  return (
    <Card className="mt-6 p-5">
      <div className="mb-3 text-sm font-semibold tracking-tight">Impact metrics</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
        {cards.map((c) => {
          const Icon = c.icon;
          return (
            <div key={c.label}>
              <div className="flex items-center gap-1.5 text-xs text-muted">
                <Icon className="h-3.5 w-3.5 text-primary" /> {c.label}
              </div>
              <div className="mt-1.5 text-2xl font-semibold tabular-nums">{c.value}</div>
              <div className="mt-1 text-[11px] leading-snug text-muted">{c.hint}</div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
