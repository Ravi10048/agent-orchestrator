import {
  Bot,
  Boxes,
  type LucideIcon,
  LayoutDashboard,
  MessagesSquare,
  PlayCircle,
  Plus,
  Search,
  Workflow as WorkflowIcon,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAgents, useConversations, useRuns, useWorkflows } from "@/hooks/queries";
import { cn } from "@/lib/cn";

interface Cmd {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: LucideIcon;
  run: () => void;
}

/** ⌘K / Ctrl+K command palette — jump to any page, action, agent, workflow, run, or conversation. */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  // data (cached by react-query; the palette filters whatever's loaded)
  const agents = useAgents();
  const workflows = useWorkflows();
  const runs = useRuns();
  const conversations = useConversations();

  // global hotkey (⌘K / Ctrl+K) + a custom event so a button can open it too
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("open-command-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("open-command-palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  const all: Cmd[] = useMemo(() => {
    const nav: Cmd[] = [
      { id: "nav-dash", label: "Dashboard", group: "Go to", icon: LayoutDashboard, run: () => go("/") },
      { id: "nav-agents", label: "Agents", group: "Go to", icon: Bot, run: () => go("/agents") },
      { id: "nav-tools", label: "Tools", group: "Go to", icon: Wrench, run: () => go("/tools") },
      { id: "nav-wf", label: "Workflows", group: "Go to", icon: WorkflowIcon, run: () => go("/workflows") },
      { id: "nav-tpl", label: "Templates", group: "Go to", icon: Boxes, run: () => go("/templates") },
      { id: "nav-runs", label: "Runs", group: "Go to", icon: PlayCircle, run: () => go("/runs") },
      { id: "nav-conv", label: "Conversations", group: "Go to", icon: MessagesSquare, run: () => go("/conversations") },
    ];
    const actions: Cmd[] = [
      { id: "act-tpl", label: "Run a template", hint: "browse pre-built workflows", group: "Actions", icon: Plus, run: () => go("/templates") },
      { id: "act-agent", label: "New agent", group: "Actions", icon: Plus, run: () => go("/agents") },
      { id: "act-wf", label: "New workflow", group: "Actions", icon: Plus, run: () => go("/workflows") },
    ];
    const dyn: Cmd[] = [
      ...(agents.data?.items ?? []).map((a) => ({
        id: `agent-${a.id}`, label: a.name, hint: a.role || "agent", group: "Agents", icon: Bot,
        run: () => go("/agents"),
      })),
      ...(workflows.data?.items ?? []).map((w) => ({
        id: `wf-${w.id}`, label: w.name, hint: "open in builder", group: "Workflows", icon: WorkflowIcon,
        run: () => go(`/workflows/${w.id}/build`),
      })),
      ...(runs.data?.items ?? []).slice(0, 30).map((r) => ({
        id: `run-${r.id}`, label: `Run #${r.id}`, hint: r.status, group: "Runs", icon: PlayCircle,
        run: () => go(`/runs?run=${r.id}`),
      })),
      ...(conversations.data?.items ?? []).map((c) => ({
        id: `conv-${c.id}`, label: c.title || `Chat ${c.external_id}`, hint: c.channel, group: "Conversations",
        icon: MessagesSquare, run: () => go("/conversations"),
      })),
    ];
    return [...nav, ...actions, ...dyn];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents.data, workflows.data, runs.data, conversations.data]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? all.filter((c) => c.label.toLowerCase().includes(q) || c.hint?.toLowerCase().includes(q) || c.group.toLowerCase().includes(q))
      : all;
    return list.slice(0, 12);
  }, [all, query]);

  useEffect(() => {
    if (active >= results.length) setActive(0);
  }, [results, active]);

  if (!open) return null;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      results[active]?.run();
    }
  };

  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center p-4 pt-[12vh]">
      <div className="fixed inset-0 bg-black/55 backdrop-blur-sm animate-fade-in" onClick={() => setOpen(false)} />
      <div
        role="dialog"
        aria-modal
        aria-label="Command palette"
        className="relative z-10 w-full max-w-xl overflow-hidden rounded-xl border border-border bg-card shadow-pop animate-fade-in"
      >
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search className="h-4 w-4 shrink-0 text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            placeholder="Search agents, workflows, runs… or jump to a page"
            className="h-12 flex-1 bg-transparent text-sm placeholder:text-muted focus:outline-none"
          />
          <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted">esc</kbd>
        </div>
        <ul className="max-h-[52vh] overflow-y-auto scroll-thin p-1.5">
          {results.length === 0 ? (
            <li className="px-3 py-6 text-center text-sm text-muted">No matches</li>
          ) : (
            results.map((c, i) => {
              const Icon = c.icon;
              return (
                <li key={c.id}>
                  <button
                    onMouseEnter={() => setActive(i)}
                    onClick={() => c.run()}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition",
                      i === active ? "bg-primary/10 text-fg" : "text-muted hover:bg-surface hover:text-fg",
                    )}
                  >
                    <Icon className={cn("h-4 w-4 shrink-0", i === active ? "text-primary" : "text-muted")} />
                    <span className="flex-1 truncate text-fg">{c.label}</span>
                    {c.hint && <span className="truncate text-xs text-muted">{c.hint}</span>}
                    <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted/70">
                      {c.group}
                    </span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
      </div>
    </div>
  );
}
