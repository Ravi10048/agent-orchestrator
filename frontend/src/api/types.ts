// Mirrors the LLD 09 DTOs (the authoritative backend contract).
export type Provider = "groq" | "gemini" | "ollama";

export interface Tenant {
  id: number;
  name: string;
  slug: string;
  is_default: boolean;
  created_at: string;
}

export type EventType =
  | "run_started" | "node_started" | "node_finished" | "agent_message"
  | "tool_call" | "token_usage" | "error" | "run_finished";

export interface Tool {
  id: number;
  name: string;
  description: string;
  type: "builtin" | "http";
  params_schema: Record<string, unknown>;
  builtin_key?: string | null;
  http_method?: string | null;
  endpoint?: string | null;
  headers?: Record<string, string> | null;
  auth?: Record<string, unknown> | null;
  body_template?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface Agent {
  id: number;
  name: string;
  role: string;
  system_prompt: string;
  provider: string;
  model: string;
  channels: string[];
  guardrails: Record<string, number>;
  memory_config: Record<string, unknown>;
  schedule: Record<string, unknown> | null;
  tools: Tool[];
  created_at: string;
  updated_at: string;
}

export interface GraphNode {
  id: string;
  type: "start" | "agent" | "tool" | "router" | "end";
  ref?: number | null;
  config?: Record<string, unknown>;
}
export interface GraphEdge {
  from: string;
  to: string;
  condition?: string | null;
}
export interface GraphJSON {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Workflow {
  id: number;
  name: string;
  description: string;
  graph: GraphJSON;
  is_template: boolean;
  created_at: string;
  updated_at: string;
}

export interface Run {
  id: number;
  workflow_id: number;
  status: "pending" | "running" | "completed" | "failed";
  trigger: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  total_tokens: number;
  est_cost: number;
  error?: string | null;
  started_at: string;
  ended_at?: string | null;
}

export interface Message {
  id: number;
  run_id: number | null;
  conversation_id: string;
  from_agent: string;
  to_agent: string;
  channel: string;
  role: string;
  content: string;
  tool_calls?: unknown[] | null;
  tokens: number;
  created_at: string;
}

export interface Conversation {
  id: number;
  channel: string;
  external_id: string;
  agent_id: number;
  workflow_id?: number | null; // set → routed per-turn through this workflow's router
  curr_agent?: string | null; // the specialist currently holding a routed chat (sticky)
  title: string;
  summary: string;
  total_tokens: number;
  created_at: string;
  last_at: string;
}

export interface EventEnvelope {
  run_id: number;
  seq: number;
  type: EventType | string;
  ts: string | null;
  event_id: number | null;
  payload: Record<string, unknown>;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Health {
  ok: boolean;
  llm_provider: string;
  llm_key_present: boolean;
  telegram_present: boolean;
  db: string;
}
