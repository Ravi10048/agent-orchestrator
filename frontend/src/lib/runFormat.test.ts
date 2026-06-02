import { describe, expect, it } from "vitest";

import type { EventEnvelope } from "@/api/types";
import { deriveStatus, deriveTotals, fmtCost, fmtDuration, fmtTokens, tokenSeries } from "@/lib/runFormat";

const ev = (seq: number, type: string, payload: Record<string, unknown> = {}): EventEnvelope => ({
  run_id: 1,
  seq,
  type,
  ts: null,
  event_id: seq,
  payload,
});

describe("runFormat", () => {
  it("formats tokens, cost, and duration", () => {
    expect(fmtTokens(2513)).toBe("2,513");
    expect(fmtCost(0)).toBe("$0");
    expect(fmtCost(0.0012)).toBe("$0.00120"); // < $0.01 → 5 decimals
    expect(fmtCost(0.5)).toBe("$0.5000"); // ≥ $0.01 → 4 decimals
    expect(fmtDuration(500)).toBe("500ms");
    expect(fmtDuration(2600)).toBe("2.6s");
  });

  it("derives status from the event stream", () => {
    expect(deriveStatus([], "pending")).toBe("pending");
    expect(deriveStatus([ev(1, "run_started")], "pending")).toBe("running");
    expect(
      deriveStatus([ev(1, "run_started"), ev(2, "run_finished", { status: "completed" })], "pending"),
    ).toBe("completed");
  });

  it("derives totals from the single source — NOT a client-side sum", () => {
    const events = [
      ev(1, "token_usage", { total_tokens: 100, run_total_tokens: 100, run_est_cost: 0.001 }),
      ev(2, "token_usage", { total_tokens: 50, run_total_tokens: 150, run_est_cost: 0.0015 }),
    ];
    // the headline reads the LAST run_total (150), not 100+150 summed
    expect(deriveTotals(events).tokens).toBe(150);
    expect(deriveTotals(events).cost).toBeCloseTo(0.0015);
  });

  it("run_finished totals win over token_usage", () => {
    const events = [
      ev(1, "token_usage", { run_total_tokens: 150, run_est_cost: 0.0015 }),
      ev(2, "run_finished", { total_tokens: 160, est_cost: 0.0016, status: "completed" }),
    ];
    expect(deriveTotals(events).tokens).toBe(160);
  });

  it("builds a cumulative token series from token_usage events", () => {
    const events = [
      ev(1, "token_usage", { run_total_tokens: 100 }),
      ev(2, "node_finished"),
      ev(3, "token_usage", { run_total_tokens: 250 }),
    ];
    expect(tokenSeries(events)).toEqual([
      { seq: 1, total: 100 },
      { seq: 3, total: 250 },
    ]);
  });
});
