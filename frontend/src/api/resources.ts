import { api } from "./client";
import type {
  Agent,
  Conversation,
  EventEnvelope,
  GraphJSON,
  Health,
  Message,
  Page,
  Run,
  Tenant,
  Tool,
  Workflow,
} from "./types";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

export const Tenants = {
  list: () => data<Tenant[]>(api.get("/tenants")),
  create: (name: string) => data<Tenant>(api.post("/tenants", { name })),
};

export const Agents = {
  list: () => data<Page<Agent>>(api.get("/agents")),
  get: (id: number) => data<Agent>(api.get(`/agents/${id}`)),
  create: (body: Record<string, unknown>) => data<Agent>(api.post("/agents", body)),
  update: (id: number, body: Record<string, unknown>) => data<Agent>(api.patch(`/agents/${id}`, body)),
  remove: (id: number) => data<void>(api.delete(`/agents/${id}`)),
  setTools: (id: number, tool_ids: number[]) => data<Agent>(api.put(`/agents/${id}/tools`, { tool_ids })),
  setSchedule: (id: number, schedule: Record<string, unknown>) =>
    data<Agent>(api.put(`/agents/${id}/schedule`, schedule)),
  test: (id: number, message: string) =>
    data<{ reply: string; stopped_reason: string; total_tokens: number; est_cost_usd: number }>(
      api.post(`/agents/${id}/test`, { message }),
    ),
  // test the UNSAVED form config (no persist) — so the editor's Test box reflects live edits
  testDraft: (body: {
    message: string;
    name?: string;
    role?: string;
    system_prompt?: string;
    provider?: string;
    model?: string;
    tool_ids?: number[];
    guardrails?: Record<string, number>;
    memory_config?: Record<string, unknown>;
  }) =>
    data<{ reply: string; stopped_reason: string; total_tokens: number; est_cost_usd: number }>(
      api.post(`/agents/test`, body),
    ),
};

export const Tools = {
  list: () => data<Page<Tool>>(api.get("/tools")),
  get: (id: number) => data<Tool>(api.get(`/tools/${id}`)),
  create: (body: Record<string, unknown>) => data<Tool>(api.post("/tools", body)),
  update: (id: number, body: Record<string, unknown>) => data<Tool>(api.patch(`/tools/${id}`, body)),
  remove: (id: number, force = false) => data<void>(api.delete(`/tools/${id}`, { params: { force } })),
  test: (id: number, args: Record<string, unknown>) =>
    data<{ ok: boolean; output: unknown; error: string | null; latency_ms: number }>(
      api.post(`/tools/${id}/test`, { args }),
    ),
  // import HTTP tools from an OpenAPI/Swagger spec (paste a spec OR give a URL)
  importSpec: (body: { url?: string; spec?: Record<string, unknown>; base_url?: string }) =>
    data<Tool[]>(api.post("/tools/import", body)),
};

export const Workflows = {
  list: (isTemplate?: boolean) =>
    data<Page<Workflow>>(api.get("/workflows", { params: { is_template: isTemplate } })),
  templates: () => data<Workflow[]>(api.get("/templates")),
  get: (id: number) => data<Workflow>(api.get(`/workflows/${id}`)),
  create: (body: { name: string; description?: string; graph: GraphJSON; is_template?: boolean }) =>
    data<Workflow>(api.post("/workflows", body)),
  update: (id: number, body: Record<string, unknown>) => data<Workflow>(api.put(`/workflows/${id}`, body)),
  validate: (graph: GraphJSON) =>
    data<{ valid: boolean; errors: string[] }>(api.post("/workflows/validate", { graph })),
  instantiate: (id: number, name?: string) =>
    data<Workflow>(api.post(`/workflows/${id}/instantiate`, { name })),
  // publish a workflow as a reusable template — idempotent per (tenant, name): re-publishing
  // updates the existing template instead of creating a duplicate
  saveAsTemplate: (id: number) => data<Workflow>(api.post(`/workflows/${id}/save-as-template`)),
  remove: (id: number) => data<void>(api.delete(`/workflows/${id}`)),
};

export const Runs = {
  list: (workflowId?: number) => data<Page<Run>>(api.get("/runs", { params: { workflow_id: workflowId } })),
  get: (id: number) => data<Run>(api.get(`/runs/${id}`)),
  create: (workflow_id: number, input: Record<string, unknown>, trigger = "manual") =>
    data<Run>(api.post("/runs", { workflow_id, input, trigger })),
  cancel: (id: number) => data<{ ok: boolean }>(api.post(`/runs/${id}/cancel`)),
  events: (id: number, afterSeq = 0) =>
    data<EventEnvelope[]>(api.get(`/runs/${id}/events`, { params: { after_seq: afterSeq } })),
  messages: (id: number) => data<Page<Message>>(api.get(`/runs/${id}/messages`)),
};

export const Conversations = {
  list: () => data<Page<Conversation>>(api.get("/conversations")),
  get: (id: number) => data<Conversation>(api.get(`/conversations/${id}`)),
  messages: (id: number) => data<Page<Message>>(api.get(`/conversations/${id}/messages`)),
  // one multi-turn chat turn — to START pass agent_id (1:1) OR workflow_id (routed per-turn through
  // the workflow's router); to CONTINUE pass conversation_id (binding is fixed at creation)
  chat: (body: {
    message: string;
    agent_id?: number;
    workflow_id?: number;
    conversation_id?: number;
    chat_id?: string;
  }) =>
    data<{
      conversation_id: number;
      reply: string;
      tools: { tool: string; ok: boolean }[];
      total_tokens: number;
      stopped_reason: string;
      active_agent?: string | null; // who produced this reply (the routed specialist)
      routed_from?: string | null; // prior handler when routing changed this turn (UI chip)
    }>(api.post("/conversations/chat", body)),
};

export const Meta = {
  health: () => data<Health>(api.get("/health")),
  models: (provider?: string) => data<{ provider: string; models: string[] }>(api.get("/models", { params: { provider } })),
};
