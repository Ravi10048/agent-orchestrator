import { describe, expect, it } from "vitest";

import type { Conversation, Run } from "@/api/types";
import { computeDashboardStats } from "@/lib/dashboardStats";

// local noon so day-bucketing can't drift across midnight on the test machine's timezone
const NOW = new Date(2026, 5, 2, 12, 0, 0).getTime();
const iso = (ms: number) => new Date(ms).toISOString();

const run = (p: Partial<Run> & Pick<Run, "id" | "status">): Run => ({
  workflow_id: 1,
  trigger: "manual",
  input: {},
  output: null,
  total_tokens: 0,
  est_cost: 0,
  started_at: iso(NOW),
  ended_at: null,
  ...p,
});

const conv = (p: Partial<Conversation> & Pick<Conversation, "id">): Conversation => ({
  channel: "web",
  external_id: "x",
  agent_id: 1,
  title: "t",
  summary: "",
  total_tokens: 0,
  created_at: iso(NOW),
  last_at: iso(NOW),
  ...p,
});

describe("computeDashboardStats", () => {
  // the API returns runs newest-first (id desc)
  const runs: Run[] = [
    run({ id: 3, status: "running", total_tokens: 10, est_cost: 0, started_at: iso(NOW), ended_at: null }),
    run({ id: 2, status: "failed", total_tokens: 50, est_cost: 0.0005, started_at: iso(NOW - 4000), ended_at: iso(NOW - 3000) }),
    run({ id: 1, status: "completed", total_tokens: 100, est_cost: 0.001, started_at: iso(NOW - 5000), ended_at: iso(NOW - 3000) }),
  ];

  it("sums tokens/cost and counts statuses", () => {
    const s = computeDashboardStats(runs, 3, [], 0, { now: NOW });
    expect(s.totalTokens).toBe(160);
    expect(s.totalCost).toBeCloseTo(0.0015);
    expect(s.completed).toBe(1);
    expect(s.failed).toBe(1);
    expect(s.active).toBe(1);
    expect(s.sampledRuns).toBe(3);
    expect(s.totalRuns).toBe(3);
  });

  it("completion rate is completed / finished (excludes still-running)", () => {
    const s = computeDashboardStats(runs, 3, [], 0, { now: NOW });
    expect(s.completionRate).toBe(0.5); // 1 completed / (1 completed + 1 failed)
  });

  it("avg duration is the mean wall-clock over runs that ended", () => {
    const s = computeDashboardStats(runs, 3, [], 0, { now: NOW });
    expect(s.avgDurationMs).toBe(1500); // (2000ms + 1000ms) / 2; the running one has no end → excluded
  });

  it("perRun is chronological ascending and carries status", () => {
    const s = computeDashboardStats(runs, 3, [], 0, { now: NOW });
    expect(s.perRun.map((p) => p.label)).toEqual(["#1", "#2", "#3"]);
    expect(s.perRun[0]).toMatchObject({ id: 1, tokens: 100, status: "completed" });
  });

  it("perRun keeps only the most recent maxPerRun", () => {
    const many: Run[] = [5, 4, 3, 2, 1].map((id) => run({ id, status: "completed" }));
    const s = computeDashboardStats(many, 5, [], 0, { now: NOW, maxPerRun: 3 });
    expect(s.perRun.map((p) => p.label)).toEqual(["#3", "#4", "#5"]);
  });

  it("byDay is zero-filled to `days` with today holding the runs started now", () => {
    const s = computeDashboardStats(runs, 3, [], 0, { now: NOW, days: 14 });
    expect(s.byDay).toHaveLength(14);
    expect(s.byDay[s.byDay.length - 1].runs).toBe(3); // all three started "today"
    expect(s.byDay.reduce((a, d) => a + d.runs, 0)).toBe(3);
  });

  it("aggregates conversation tokens and surfaces the true total count", () => {
    const s = computeDashboardStats(
      runs,
      3,
      [conv({ id: 1, total_tokens: 20 }), conv({ id: 2, total_tokens: 30 })],
      7,
      { now: NOW },
    );
    expect(s.conversations).toBe(7); // the true page total, not just the sampled records
    expect(s.conversationTokens).toBe(50);
  });

  it("handles the empty case without NaN", () => {
    const s = computeDashboardStats([], 0, [], 0, { now: NOW });
    expect(s.totalTokens).toBe(0);
    expect(s.completionRate).toBeNull();
    expect(s.avgDurationMs).toBeNull();
    expect(s.perRun).toEqual([]);
    expect(s.byDay).toHaveLength(14);
  });
});
