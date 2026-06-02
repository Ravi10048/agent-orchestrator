import { Play, Plus, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import type { ApiError } from "@/api/client";
import { Tools } from "@/api/resources";
import type { Tool } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { useToolMutations } from "@/hooks/queries";
import { toast } from "@/lib/toast";

interface ParamRow { name: string; type: string; required: boolean }
interface KV { key: string; value: string }

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

function schemaToRows(schema: Record<string, unknown> | undefined): ParamRow[] {
  const props = (schema?.properties as Record<string, { type?: string }>) ?? {};
  const required = (schema?.required as string[]) ?? [];
  return Object.entries(props).map(([name, def]) => ({
    name,
    type: def.type ?? "string",
    required: required.includes(name),
  }));
}
function rowsToSchema(rows: ParamRow[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  for (const r of rows) if (r.name.trim()) properties[r.name.trim()] = { type: r.type };
  return { type: "object", properties, required: rows.filter((r) => r.required && r.name.trim()).map((r) => r.name.trim()) };
}

export function ToolEditor({ open, onClose, tool }: { open: boolean; onClose: () => void; tool: Tool | null }) {
  const editing = !!tool;
  const builtin = tool?.type === "builtin";
  const { create, update } = useToolMutations();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [method, setMethod] = useState("GET");
  const [endpoint, setEndpoint] = useState("");
  const [params, setParams] = useState<ParamRow[]>([]);
  const [headers, setHeaders] = useState<KV[]>([]);
  const [authType, setAuthType] = useState("none");
  const [authName, setAuthName] = useState("");
  const [authEnv, setAuthEnv] = useState("");
  const [tryArgs, setTryArgs] = useState("{}");
  const [tryOut, setTryOut] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTryOut(null);
    setTryArgs("{}");
    if (tool) {
      setName(tool.name);
      setDescription(tool.description);
      setMethod(tool.http_method ?? "GET");
      setEndpoint(tool.endpoint ?? "");
      setParams(schemaToRows(tool.params_schema));
      setHeaders(Object.entries(tool.headers ?? {}).map(([key, value]) => ({ key, value: String(value) })));
      const a = (tool.auth ?? {}) as Record<string, string>;
      setAuthType(a.type ?? "none");
      setAuthName(a.name ?? "");
      setAuthEnv(a.token_env ?? a.value_env ?? "");
    } else {
      setName("");
      setDescription("");
      setMethod("GET");
      setEndpoint("");
      setParams([{ name: "", type: "string", required: true }]);
      setHeaders([]);
      setAuthType("none");
      setAuthName("");
      setAuthEnv("");
    }
  }, [open, tool]);

  const buildAuth = (): Record<string, string> | null => {
    if (authType === "bearer") return { type: "bearer", token_env: authEnv };
    if (authType === "header") return { type: "header", name: authName, value_env: authEnv };
    return null;
  };

  const save = async () => {
    if (!builtin && !name.trim()) {
      toast.error("Name is required");
      return;
    }
    const body: Record<string, unknown> = {
      description,
      params_schema: rowsToSchema(params),
      http_method: method,
      endpoint,
      headers: headers.length ? Object.fromEntries(headers.filter((h) => h.key).map((h) => [h.key, h.value])) : null,
      auth: buildAuth(),
    };
    try {
      if (editing && tool) {
        await update.mutateAsync({ id: tool.id, body });
      } else {
        await create.mutateAsync({ ...body, name, type: "http" });
      }
      toast.success(editing ? "Tool updated" : "Tool created");
      onClose();
    } catch (e) {
      toast.error((e as ApiError).message ?? "Save failed");
    }
  };

  const tryIt = async () => {
    if (!tool) return;
    try {
      const args = JSON.parse(tryArgs || "{}");
      const r = await Tools.test(tool.id, args);
      setTryOut(JSON.stringify(r, null, 2));
    } catch (e) {
      const msg = e instanceof SyntaxError ? "Args must be valid JSON" : (e as ApiError).message;
      toast.error(msg ?? "Test failed");
    }
  };

  // ── built-in: read-only view ──────────────────────────────────────
  if (builtin && tool) {
    return (
      <Modal open={open} onClose={onClose} title={tool.name} description="Built-in tool (read-only).">
        <p className="mb-3 text-sm text-muted">{tool.description}</p>
        <Label>Parameters</Label>
        <pre className="mt-1.5 max-h-72 overflow-auto scroll-thin rounded-lg border border-border bg-bg p-3 font-mono text-xs">
          {JSON.stringify(tool.params_schema, null, 2)}
        </pre>
      </Modal>
    );
  }

  // ── http: no-code builder ─────────────────────────────────────────
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={editing ? "Edit HTTP tool" : "New HTTP tool"}
      description="Define a REST call with no code — map it to an agent and the runtime executes it."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} disabled={create.isPending || update.isPending}>
            {editing ? "Save" : "Create tool"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} disabled={editing} placeholder="get_weather" />
          </Field>
          <Field label="Description" hint="shown to the LLM">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Get current weather" />
          </Field>
        </div>

        <div className="grid grid-cols-[120px_1fr] gap-3">
          <Field label="Method">
            <Select value={method} onChange={(e) => setMethod(e.target.value)}>
              {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </Select>
          </Field>
          <Field label="URL" hint="use {placeholders} from params">
            <Input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="https://api.example.com/weather/{city}" className="font-mono" />
          </Field>
        </div>

        <RowEditor<ParamRow>
          label="Parameters"
          cols="grid-cols-[1fr_8rem_4rem_auto]"
          rows={params}
          onAdd={() => setParams((r) => [...r, { name: "", type: "string", required: false }])}
          onRemove={(i) => setParams((r) => r.filter((_, x) => x !== i))}
          render={(row, i) => (
            <>
              <Input
                value={row.name}
                placeholder="param"
                onChange={(e) => setParams((r) => r.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
              />
              <Select
                value={row.type}
                onChange={(e) => setParams((r) => r.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}
              >
                {["string", "number", "integer", "boolean"].map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </Select>
              <label className="flex items-center gap-1.5 px-1 text-xs text-muted">
                <input
                  type="checkbox"
                  className="accent-[hsl(var(--primary))]"
                  checked={row.required}
                  onChange={(e) => setParams((r) => r.map((x, j) => (j === i ? { ...x, required: e.target.checked } : x)))}
                />
                req
              </label>
            </>
          )}
        />

        <RowEditor<KV>
          label="Headers"
          cols="grid-cols-[1fr_1.6fr_auto]"
          rows={headers}
          onAdd={() => setHeaders((r) => [...r, { key: "", value: "" }])}
          onRemove={(i) => setHeaders((r) => r.filter((_, x) => x !== i))}
          render={(row, i) => (
            <>
              <Input
                value={row.key}
                placeholder="Header"
                onChange={(e) => setHeaders((r) => r.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))}
              />
              <Input
                value={row.value}
                placeholder="value"
                onChange={(e) => setHeaders((r) => r.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
              />
            </>
          )}
        />

        <div className="space-y-1.5">
          <Label>
            Auth <span className="font-normal text-muted">— secrets are read from env-var names, never stored</span>
          </Label>
          <div className="grid grid-cols-3 gap-2">
            <Select value={authType} onChange={(e) => setAuthType(e.target.value)}>
              <option value="none">No auth</option>
              <option value="bearer">Bearer</option>
              <option value="header">Header</option>
            </Select>
            {authType === "header" && (
              <Input value={authName} onChange={(e) => setAuthName(e.target.value)} placeholder="X-Api-Key" />
            )}
            {authType !== "none" && (
              <Input
                value={authEnv}
                onChange={(e) => setAuthEnv(e.target.value)}
                placeholder="ENV_VAR_NAME"
                className="font-mono"
              />
            )}
          </div>
        </div>

        {editing && (
          <div className="space-y-1.5 rounded-lg border border-border p-3">
            <Label>Try it</Label>
            <Textarea rows={2} value={tryArgs} onChange={(e) => setTryArgs(e.target.value)} className="font-mono text-xs" />
            <Button variant="secondary" size="sm" onClick={tryIt}>
              <Play className="h-3.5 w-3.5" /> Run
            </Button>
            {tryOut && (
              <pre className="max-h-48 overflow-auto scroll-thin rounded-lg border border-border bg-bg p-3 font-mono text-xs">
                {tryOut}
              </pre>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}

function RowEditor<T>({
  label,
  cols,
  rows,
  onAdd,
  onRemove,
  render,
}: {
  label: string;
  cols: string;
  rows: T[];
  onAdd: () => void;
  onRemove: (i: number) => void;
  render: (row: T, i: number) => ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        <Button variant="ghost" size="sm" onClick={onAdd}>
          <Plus className="h-3.5 w-3.5" /> Add
        </Button>
      </div>
      {rows.length === 0 && <p className="text-xs text-muted">None.</p>}
      {rows.map((row, i) => (
        <div key={i} className={`grid items-center gap-2 ${cols}`}>
          {render(row, i)}
          <button onClick={() => onRemove(i)} className="text-muted transition hover:text-destructive" aria-label="Remove">
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
