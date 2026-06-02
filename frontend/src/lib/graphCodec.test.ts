import { describe, expect, it } from "vitest";

import type { GraphJSON } from "@/api/types";
import { toFlow, toGraph } from "@/lib/graphCodec";

const graph: GraphJSON = {
  nodes: [
    { id: "start", type: "start" },
    { id: "a", type: "agent", ref: 5, config: { max_visits: 3 } },
    { id: "end", type: "end" },
  ],
  edges: [
    { from: "start", to: "a", condition: null },
    { from: "a", to: "end", condition: "last.done == true" },
  ],
};

describe("graphCodec", () => {
  it("round-trips graph → flow → graph (ids, type, ref, max_visits, condition preserved)", () => {
    const resolve = (ref: number | null | undefined) => (ref === 5 ? { name: "Agent5", model: "m" } : {});
    const { nodes, edges } = toFlow(graph, resolve);
    expect(nodes).toHaveLength(3);
    expect(edges).toHaveLength(2);

    const back = toGraph(nodes, edges);
    expect(back.nodes.map((n) => n.id).sort()).toEqual(["a", "end", "start"]);

    const a = back.nodes.find((n) => n.id === "a")!;
    expect(a.type).toBe("agent");
    expect(a.ref).toBe(5);
    expect(a.config?.max_visits).toBe(3);

    const conditional = back.edges.find((e) => e.from === "a" && e.to === "end")!;
    expect(conditional.condition).toBe("last.done == true");
    const plain = back.edges.find((e) => e.from === "start" && e.to === "a")!;
    expect(plain.condition).toBeNull();
  });
});
