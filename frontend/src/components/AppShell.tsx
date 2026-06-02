import {
  Bot,
  Boxes,
  LayoutDashboard,
  MessagesSquare,
  PlayCircle,
  Search,
  Workflow as WorkflowIcon,
  Wrench,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { TenantSwitcher } from "@/components/TenantSwitcher";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { cn } from "@/lib/cn";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/workflows", label: "Workflows", icon: WorkflowIcon },
  { to: "/templates", label: "Templates", icon: Boxes },
  { to: "/runs", label: "Runs", icon: PlayCircle },
  { to: "/conversations", label: "Conversations", icon: MessagesSquare },
];

export function AppShell() {
  return (
    <div className="flex h-full">
      <aside className="flex w-[244px] shrink-0 flex-col border-r border-border bg-surface/60">
        <div className="flex items-center gap-3 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-primary to-[hsl(280_85%_62%)] shadow-glow">
            <WorkflowIcon className="h-[18px] w-[18px] text-white" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">Agent Orchestrator</div>
            <div className="text-[11px] text-muted">orchestration platform</div>
          </div>
        </div>

        <TenantSwitcher />

        <div className="px-3 pb-1">
          <button
            onClick={() => window.dispatchEvent(new Event("open-command-palette"))}
            className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-muted transition hover:border-border-strong hover:text-fg"
          >
            <Search className="h-4 w-4" />
            <span className="flex-1 text-left">Search…</span>
            <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px]">⌘K</kbd>
          </button>
        </div>

        <div className="px-5 pb-2 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
          Platform
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}>
              {({ isActive }) => (
                <span
                  className={cn(
                    "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                    isActive ? "bg-primary/10 text-fg" : "text-muted hover:bg-card hover:text-fg",
                  )}
                >
                  {isActive && (
                    <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-primary" aria-hidden />
                  )}
                  <Icon className={cn("h-4 w-4", isActive ? "text-primary" : "text-muted group-hover:text-fg")} />
                  {label}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center justify-between px-5 py-4">
          <span className="flex items-center gap-2 text-[11px] text-muted">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            v0.1 · runs locally
          </span>
          <ThemeToggle />
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto scroll-thin">
        <div className="mx-auto max-w-6xl px-8 py-8 animate-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
