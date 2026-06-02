import { describe, expect, it } from "vitest";

import type { EventEnvelope, Message } from "@/api/types";
import { buildTrace } from "@/lib/trace";

const ev = (seq: number, type: string, payload: Record<string, unknown> = {}): EventEnvelope => ({
  run_id: 1,
  seq,
  type,
  ts: null,
  event_id: seq,
  payload,
});

const msg = (id: number, from_agent: string, content: string): Message => ({
  id,
  run_id: 1,
  conversation_id: "1",
  from_agent,
  to_agent: "",
  channel: "internal",
  role: "assistant",
  content,
  tokens: 0,
  created_at: "",
});

describe("buildTrace", () => {
  it("reduces the event stream into per-node trace, the traversed path, and input/output", () => {
    const events: EventEnvelope[] = [
      ev(1, "run_started", { node_count: 3, input_preview: "fix the bug" }),
      ev(2, "node_started", { node_id: "start", node_type: "start" }),
      ev(3, "node_finished", { node_id: "start", node_type: "start", text_preview: "fix the bug" }),
      ev(4, "node_started", { node_id: "eng", node_type: "agent", agent_name: "Engineer" }),
      ev(5, "tool_call", { node_id: "eng", tool: "web_fetch", ok: true }),
      ev(6, "node_finished", {
        node_id: "eng",
        agent_name: "Engineer",
        stopped_reason: "handoff",
        route: "Writer",
        tokens: 50,
        text_preview: "short preview",
      }),
    ];
    const messages: Message[] = [msg(1, "Engineer", "FULL diagnosis text")];

    const t = buildTrace(events, messages, { text: "fix the bug" });

    const eng = t.byNode["eng"];
    expect(eng.agentName).toBe("Engineer");
    expect(eng.status).toBe("handoff"); // routed, not just complete
    expect(eng.route).toBe("Writer");
    expect(eng.tokens).toBe(50);
    expect(eng.tools).toHaveLength(1);
    expect(eng.tools[0].tool).toBe("web_fetch");
    expect(eng.fullText).toBe("FULL diagnosis text"); // matched from persisted messages
    expect(eng.inputText).toBe("fix the bug"); // upstream (start) output = the user request

    expect([...t.traversed]).toContain("start->eng"); // actual path
    expect(t.userInput).toBe("fix the bug");
  });

  it("a routed specialist's input is the request the router forwarded, not the router's reply (r)", () => {
    const events: EventEnvelope[] = [
      ev(1, "run_started", { input_preview: "I was double charged" }),
      ev(2, "node_started", { node_id: "start", node_type: "start" }),
      ev(3, "node_finished", { node_id: "start", node_type: "start", text_preview: "I was double charged" }),
      ev(4, "node_started", { node_id: "sup", node_type: "agent", agent_name: "Supervisor" }),
      ev(5, "node_finished", {
        node_id: "sup",
        agent_name: "Supervisor",
        stopped_reason: "handoff",
        route: "Billing",
        text_preview: "Connecting you to Billing.",
      }),
      ev(6, "node_started", { node_id: "bill", node_type: "agent", agent_name: "Billing" }),
      ev(7, "node_finished", { node_id: "bill", agent_name: "Billing", text_preview: "Refund processed." }),
    ];
    const messages: Message[] = [
      msg(1, "Supervisor", "Connecting you to Billing."),
      msg(2, "Billing", "Refund processed."),
    ];
    const t = buildTrace(events, messages, { text: "I was double charged" });

    expect(t.byNode["sup"].route).toBe("Billing"); // n
    expect(t.byNode["sup"].fullText).toBe("Connecting you to Billing."); // r (the router's reply)
    // the specialist receives the ORIGINAL request the router forwarded — NOT the router's reply
    expect(t.byNode["bill"].inputText).toBe("I was double charged");
  });

  it("marks unreached nodes idle and counts loop visits", () => {
    const events: EventEnvelope[] = [
      ev(1, "node_started", { node_id: "a", agent_name: "A" }),
      ev(2, "node_finished", { node_id: "a", agent_name: "A" }),
      ev(3, "node_started", { node_id: "a", agent_name: "A" }), // second visit (loop)
      ev(4, "node_finished", { node_id: "a", agent_name: "A" }),
    ];
    const t = buildTrace(events, []);
    expect(t.byNode["a"].visits).toBe(2);
    expect(t.byNode["ghost"]).toBeUndefined();
  });
});
