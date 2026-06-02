import { Send } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import type { ApiError } from "@/api/client";
import { Agents } from "@/api/resources";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAgent, useAgentMutations, useModels, useTools } from "@/hooks/queries";
import { toast } from "@/lib/toast";

interface Form {
  name: string;
  role: string;
  system_prompt: string;
  provider: string;
  model: string;
  channels: string[];
  guardrails: { max_steps: number; max_tokens: number; max_tokens_total: number; timeout_s: number };
  memory_config: { type: string; window: number; summary: boolean };
}

const BLANK: Form = {
  name: "",
  role: "",
  system_prompt: "",
  provider: "groq",
  model: "llama-3.3-70b-versatile",
  channels: [],
  guardrails: { max_steps: 6, max_tokens: 1024, max_tokens_total: 8000, timeout_s: 60 },
  memory_config: { type: "short_term", window: 12, summary: false },
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</div>
      {children}
    </div>
  );
}
function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>
        {label}
        {hint && <span className="ml-1 font-normal text-muted">{hint}</span>}
      </Label>
      {children}
    </div>
  );
}

export function AgentEditor({
  open,
  onClose,
  agentId,
}: {
  open: boolean;
  onClose: () => void;
  agentId: number | null;
}) {
  const editing = !!agentId;
  const existing = useAgent(agentId ?? 0);
  const tools = useTools();
  const { create, update, setTools } = useAgentMutations();
  const [form, setForm] = useState<Form>(BLANK);
  const [toolIds, setToolIds] = useState<number[]>([]);
  const models = useModels(form.provider);

  // testing (edit-only)
  const [testMsg, setTestMsg] = useState("");
  const [testReply, setTestReply] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (editing && existing.data) {
      const a = existing.data;
      setForm({
        name: a.name,
        role: a.role,
        system_prompt: a.system_prompt,
        provider: a.provider,
        model: a.model,
        channels: a.channels ?? [],
        guardrails: { ...BLANK.guardrails, ...(a.guardrails as Form["guardrails"]) },
        memory_config: { ...BLANK.memory_config, ...(a.memory_config as Form["memory_config"]) },
      });
      setToolIds(a.tools.map((t) => t.id));
    } else if (!editing) {
      setForm(BLANK);
      setToolIds([]);
    }
    setTestReply(null);
    setTestMsg("");
  }, [open, editing, existing.data]);

  const patch = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));
  const modelOptions = [...new Set([form.model, ...(models.data?.models ?? [])])].filter(Boolean);

  const save = async () => {
    if (!form.name.trim()) {
      toast.error("Name is required");
      return;
    }
    try {
      if (editing && agentId) {
        await update.mutateAsync({ id: agentId, body: { ...form } });
        await setTools.mutateAsync({ id: agentId, tool_ids: toolIds });
      } else {
        await create.mutateAsync({ ...form, tool_ids: toolIds });
      }
      toast.success(editing ? "Agent updated" : "Agent created");
      onClose();
    } catch (e) {
      toast.error((e as ApiError).message ?? "Save failed");
    }
  };

  // test the CURRENT (unsaved) form — so the reply reflects exactly what's typed, no save needed
  const runTest = async () => {
    if (!testMsg.trim()) return;
    setTesting(true);
    setTestReply(null);
    try {
      const r = await Agents.testDraft({
        message: testMsg,
        name: form.name || "Draft agent",
        role: form.role,
        system_prompt: form.system_prompt,
        provider: form.provider,
        model: form.model,
        tool_ids: toolIds,
        guardrails: form.guardrails,
        memory_config: form.memory_config,
      });
      setTestReply(r.reply);
    } catch (e) {
      toast.error((e as ApiError).message ?? "Test failed");
    } finally {
      setTesting(false);
    }
  };

  const toggleTool = (id: number) =>
    setToolIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  const telegramOn = form.channels.includes("telegram");

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={editing ? "Edit agent" : "New agent"}
      description="Configure every dimension: brain, skills (tools), channels, memory, and guardrails."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} disabled={create.isPending || update.isPending}>
            {editing ? "Save changes" : "Create agent"}
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        <Section title="Identity">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">
              <Input value={form.name} onChange={(e) => patch({ name: e.target.value })} placeholder="Researcher" />
            </Field>
            <Field label="Role">
              <Input value={form.role} onChange={(e) => patch({ role: e.target.value })} placeholder="Web researcher" />
            </Field>
          </div>
        </Section>

        <Section title="Brain">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Provider">
              <Select value={form.provider} onChange={(e) => patch({ provider: e.target.value })}>
                <option value="groq">Groq</option>
                <option value="gemini">Gemini</option>
                <option value="ollama">Ollama (local)</option>
              </Select>
            </Field>
            <Field label="Model">
              <Select value={form.model} onChange={(e) => patch({ model: e.target.value })}>
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="System prompt">
            <Textarea
              rows={4}
              value={form.system_prompt}
              onChange={(e) => patch({ system_prompt: e.target.value })}
              placeholder="You are a concise web researcher. Cite URLs."
            />
          </Field>
        </Section>

        <Section title="Skills (tools)">
          {tools.data && tools.data.items.length > 0 ? (
            <div className="grid grid-cols-2 gap-2">
              {tools.data.items.map((t) => (
                <label
                  key={t.id}
                  className="flex cursor-pointer items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:border-border-strong"
                >
                  <input
                    type="checkbox"
                    className="accent-[hsl(var(--primary))]"
                    checked={toolIds.includes(t.id)}
                    onChange={() => toggleTool(t.id)}
                  />
                  <span className="truncate">{t.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted">No tools yet — create one in the Tools tab.</p>
          )}
        </Section>

        <div className="grid grid-cols-2 gap-6">
          <Section title="Channels">
            <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2">
              <span className="text-sm">Telegram</span>
              <Switch
                checked={telegramOn}
                onCheckedChange={(v) => patch({ channels: v ? ["telegram"] : [] })}
              />
            </div>
          </Section>
          <Section title="Memory">
            <Field label="Window" hint="recent messages">
              <Input
                type="number"
                value={form.memory_config.window}
                onChange={(e) => patch({ memory_config: { ...form.memory_config, window: Number(e.target.value) } })}
              />
            </Field>
            <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2">
              <span className="text-sm">Summary memory</span>
              <Switch
                checked={form.memory_config.summary}
                onCheckedChange={(v) => patch({ memory_config: { ...form.memory_config, summary: v } })}
              />
            </div>
          </Section>
        </div>

        <Section title="Guardrails">
          <div className="grid grid-cols-4 gap-3">
            {(["max_steps", "max_tokens", "max_tokens_total", "timeout_s"] as const).map((k) => (
              <Field key={k} label={k.replace(/_/g, " ")}>
                <Input
                  type="number"
                  value={form.guardrails[k]}
                  onChange={(e) => patch({ guardrails: { ...form.guardrails, [k]: Number(e.target.value) } })}
                />
              </Field>
            ))}
          </div>
        </Section>

        <Section title="Test">
          <p className="-mt-1 text-xs text-muted">
            Runs the config above as-is — no need to save first. Nothing is persisted.
          </p>
          <div className="flex gap-2">
            <Input
              value={testMsg}
              onChange={(e) => setTestMsg(e.target.value)}
              placeholder="Say hi to the agent…"
              onKeyDown={(e) => e.key === "Enter" && runTest()}
            />
            <Button variant="secondary" onClick={runTest} disabled={testing}>
              <Send className="h-4 w-4" /> {testing ? "…" : "Test"}
            </Button>
          </div>
          {testReply !== null && (
            <div className="rounded-lg border border-border bg-surface p-3 text-sm">{testReply}</div>
          )}
        </Section>
      </div>
    </Modal>
  );
}
