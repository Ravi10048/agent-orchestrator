import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Agents, Conversations, Meta, Runs, Tenants, Tools, Workflows } from "@/api/resources";

export const qk = {
  health: ["health"] as const,
  tenants: ["tenants"] as const,
  agents: ["agents"] as const,
  agent: (id: number) => ["agents", id] as const,
  tools: ["tools"] as const,
  tool: (id: number) => ["tools", id] as const,
  workflows: (t?: boolean) => ["workflows", t ?? "all"] as const,
  templates: ["templates"] as const,
  workflow: (id: number) => ["workflow", id] as const,
  runs: (wf?: number) => ["runs", wf ?? "all"] as const,
  run: (id: number) => ["run", id] as const,
  conversations: ["conversations"] as const,
  conversation: (id: number) => ["conversation", id] as const,
  models: (p?: string) => ["models", p ?? "default"] as const,
};

// ── queries ───────────────────────────────────────────────────────────
export const useHealth = () => useQuery({ queryKey: qk.health, queryFn: Meta.health });
export const useTenants = () => useQuery({ queryKey: qk.tenants, queryFn: Tenants.list });
export const useAgents = () => useQuery({ queryKey: qk.agents, queryFn: Agents.list });
export const useAgent = (id: number) =>
  useQuery({ queryKey: qk.agent(id), queryFn: () => Agents.get(id), enabled: Number.isFinite(id) && id > 0 });
export const useTools = () => useQuery({ queryKey: qk.tools, queryFn: Tools.list });
export const useTool = (id: number) =>
  useQuery({ queryKey: qk.tool(id), queryFn: () => Tools.get(id), enabled: id > 0 });
export const useWorkflows = (t?: boolean) => useQuery({ queryKey: qk.workflows(t), queryFn: () => Workflows.list(t) });
export const useTemplates = () => useQuery({ queryKey: qk.templates, queryFn: Workflows.templates });
export const useWorkflow = (id: number) =>
  useQuery({ queryKey: qk.workflow(id), queryFn: () => Workflows.get(id), enabled: id > 0 });
export const useRuns = (wf?: number) => useQuery({ queryKey: qk.runs(wf), queryFn: () => Runs.list(wf) });
export const useRun = (id: number) =>
  useQuery({ queryKey: qk.run(id), queryFn: () => Runs.get(id), enabled: id > 0 });
export const useConversations = () => useQuery({ queryKey: qk.conversations, queryFn: Conversations.list });
export const useModels = (provider?: string) =>
  useQuery({ queryKey: qk.models(provider), queryFn: () => Meta.models(provider), enabled: !!provider });

// ── mutations ─────────────────────────────────────────────────────────
export function useAgentMutations() {
  const qc = useQueryClient();
  const inv = () => qc.invalidateQueries({ queryKey: qk.agents });
  return {
    create: useMutation({ mutationFn: (b: Record<string, unknown>) => Agents.create(b), onSuccess: inv }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => Agents.update(id, body),
      onSuccess: inv,
    }),
    remove: useMutation({ mutationFn: (id: number) => Agents.remove(id), onSuccess: inv }),
    setTools: useMutation({
      mutationFn: ({ id, tool_ids }: { id: number; tool_ids: number[] }) => Agents.setTools(id, tool_ids),
      onSuccess: inv,
    }),
  };
}

export function useToolMutations() {
  const qc = useQueryClient();
  const inv = () => qc.invalidateQueries({ queryKey: qk.tools });
  return {
    create: useMutation({ mutationFn: (b: Record<string, unknown>) => Tools.create(b), onSuccess: inv }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => Tools.update(id, body),
      onSuccess: inv,
    }),
    remove: useMutation({
      mutationFn: ({ id, force }: { id: number; force?: boolean }) => Tools.remove(id, force),
      onSuccess: inv,
    }),
  };
}

export function useWorkflowMutations() {
  const qc = useQueryClient();
  // refresh BOTH lists: a workflow can become a template (and vice-versa via instantiate)
  const inv = () => {
    qc.invalidateQueries({ queryKey: ["workflows"] });
    qc.invalidateQueries({ queryKey: qk.templates });
  };
  return {
    create: useMutation({ mutationFn: Workflows.create, onSuccess: inv }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => Workflows.update(id, body),
      onSuccess: inv,
    }),
    instantiate: useMutation({
      mutationFn: ({ id, name }: { id: number; name?: string }) => Workflows.instantiate(id, name),
      onSuccess: inv,
    }),
    saveAsTemplate: useMutation({ mutationFn: (id: number) => Workflows.saveAsTemplate(id), onSuccess: inv }),
    remove: useMutation({ mutationFn: (id: number) => Workflows.remove(id), onSuccess: inv }),
  };
}

export function useRunMutations() {
  const qc = useQueryClient();
  return {
    create: useMutation({
      mutationFn: ({ workflowId, input }: { workflowId: number; input: Record<string, unknown> }) =>
        Runs.create(workflowId, input),
      onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
    }),
    cancel: useMutation({
      mutationFn: (id: number) => Runs.cancel(id),
      onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
    }),
  };
}
