# LLD 10 — Frontend (UX-first)

> The web console — the graded **UI/UX & configurability (20%)** surface, and the face of the **40% demo**. Consumes the [LLD 09](09-api.md) contract exactly. Status: **for review** — *hardened by the design + UX adversarial-review pass.*

## Responsibility
A clean, modern, **fast-feeling** SPA to do everything visually: see the system at a glance, **instantiate a template and run a multi-agent workflow in a couple of clicks**, build/edit workflows on a canvas, configure agents across every dimension, manage tools, **watch runs live** (logs · inter-agent messages · token/cost), and chat with an agent. Stack: **React 19 + Vite + TS + Tailwind + shadcn/Radix + @xyflow/react + @tanstack/react-query + recharts**, dev-proxying `/api` + `/ws` → `:8000`.

## Design system (the polish that wins the 20%)
- **Tokens** (CSS vars, shadcn convention): `--primary` indigo-600/500, status `--success` emerald / `--warning` amber / `--destructive` red / `--info` sky; `--radius .75rem` (cards 1rem); fonts **Inter** (sans) + **JetBrains Mono** (code/JSON); `shadow-soft`/`shadow-pop`; an 8-hue **agent-tint** palette for avatars + node accents (an agent has a stable color everywhere).
- **Dark mode default** (`.dark` on `<html>`), light toggle persisted; `prefers-color-scheme` fallback.
- **shadcn/Radix primitives** (`components/ui/*`): button, card, dialog, sheet, input, select, switch, tabs, badge, skeleton, dropdown, tooltip, sonner(toast), command, scroll-area, alert.
- **Shared components**: `PageHeader, EmptyState, ErrorState, ListSkeleton, StatCard, StatusBadge, ProviderPill, ConnectionDot, ConfirmDialog, CopyButton, JsonViewer, TokenCostBadge, AgentAvatar, GuardrailsFields, ScheduleFields, ChannelsField, TagInput`.
- **Motion**: subtle framer-motion (list/card enter, drawer slide, live-event row highlight) — "alive," not flashy.

## Routes (`react-router-dom`) — canonical (resolves the review's route drift)
```
/                        Dashboard (overview + launchpad)
/agents · /agents/new · /agents/:id     AgentsList + AgentEditor (modal-route)
/tools · /tools/new · /tools/:id         ToolsList(registry) + ToolEditor (modal-route)
/workflows                               WorkflowsList
/workflows/:id/build                     WorkflowBuilder  (→ React Flow canvas + inspector)
/templates                               TemplatesGallery
/runs · /runs/:id                        RunsList + RunDetail (post-hoc monitor)
/conversations · /conversations/:id      ConversationsList + transcript
```
**Live monitor = a global `<RunDrawer/>`** overlay keyed by the `?run=:id` search param — so it **survives navigation and is deep-linkable** (watch a run while editing another workflow).

## Data layer — `api/*` + `hooks/*`
- **axios** instance `baseURL:'/api'`; response interceptor → `ApiError{status,code,message,details}` (422 flattened to field errors for forms). Reads the LLD 09 error envelope.
- **react-query**: `staleTime 30s`, `retry 1`, no refetch-on-focus; mutation `onError → toast`. Query-key factory `qk.agents/tools/workflows/templates/runs/runs.events`. Optimistic updates for toggles (agent enable, schedule on/off).
- **`useMonitorSocket(runId)`** → `{status, events, lastEvent}` implementing the **LLD 09 protocol exactly**: connect `/ws/monitor` → send `{action:"subscribe",run_id}` → receive `EventEnvelope`s (backfill then live) → **dedupe + order by `(run_id,seq)`**; auto-reconnect (exp backoff + jitter) and on reconnect refetch `GET /runs/{id}/events?after_seq=<lastSeq>` to close the gap; `ConnectionDot` shows status. **One envelope renderer** for live + replay (RunDetail reuses it).
- **`types.ts`** mirrors LLD 09 DTOs (Agent/Tool/Workflow/Run/Message/Conversation/EventEnvelope, `Provider`, `EventType`).

## Surfaces

### Dashboard `/` — the launchpad (optimizes "time-to-first-workflow")
StatCards (agents · workflows · runs today · tokens/cost today), a **"Run a template" hero** (the 2 seeded templates with one-click *Use*), recent runs (click → RunDrawer), and a **prerequisite banner**: calls `GET /health`; if `llm_key_present=false` shows *"Add GROQ_API_KEY to .env to run agents"* (and `telegram_present=false` → *"Set TELEGRAM_BOT_TOKEN to enable the Telegram channel"*). **(UX fix: the prerequisite is confronted up front, not at the moment of failure.)**

### Templates `/templates` → the hero flow (UX fix: **no surprise auto-run**)
Card per template (name, description, a mini node-graph preview, agent chips). **Use** → `POST /workflows/{id}/instantiate` → navigate to `/workflows/:newId/build` → builder opens with a primed **Run** button that opens a **Run modal prefilled with example input** (editable) → confirm → `POST /runs` → `RunDrawer` live monitor opens. So it's ~2 clicks **with a confirm/edit step** (forgiveness + cost control), and the user *sees* the graph before running.

### Workflow Builder `/workflows/:id/build` (React Flow)
Layout: **Toolbar** (name, save-state, validation badge, auto-layout, undo/redo, **Run**) | **Palette** (drag start/agent/tool/router/end) + **Canvas** | **Inspector** (right).
- **Custom nodes** (`BaseNode` chrome: type icon, title, handles, selected ring, **error dot**): AgentNode shows agent avatar+name+model; RouterNode shows branch count; Start/End distinct.
- **ConditionEdge**: bezier with a **condition pill**; default (`else`) edges dashed; delete-on-hover.
- **Inspector** switches by selection: AgentInspector (pick agent, `max_visits`), ToolInspector, RouterInspector, **EdgeInspector → `ConditionEditor`** — a small editor for the LLD 06 mini-language (`last.intent == "billing"`, `attempts < 3`) with **token chips + autocomplete + a live "test against last output" check** (calls a tiny client mirror; the server `/workflows/validate` is the authority).
- **Live validation**: debounced `POST /workflows/validate` on edits → `ValidationPanel` lists errors (one start, reachable end, **branching node needs a default edge** — mirrors LLD 06); clicking an error selects+centers the node. **Save** disabled while invalid (or saves draft with a clear warning).
- **Run from builder**: the Run modal (above) → `RunDrawer`; **`LiveNodeBadges`** overlay nodes with running/done/failed from the WS stream — you watch the graph light up.
- State: a small **Zustand** store (nodes/edges/selection/dirty/undo-redo); `graphCodec` ↔ GraphJSON; `autolayout` (dagre).

### Live Monitor — `<RunDrawer/>` (must *feel* live; the 40% demo centerpiece)
Three panes, fed by `useMonitorSocket`:
1. **Timeline** — ordered event rows (`node_started/finished`, `tool_call`, `error`), color-coded by `EventType`, newest highlighted (motion); node-finished rows show `duration_ms` + `stopped_reason`.
2. **Inter-agent messages** — a chat-style thread of `agent_message` events (`from_agent → to_agent`, `content_preview`), each tinted by the agent's color — *visibly* demonstrating agent-to-agent comms (a graded metric). **(UX/contract fix: reads `from_agent/to_agent/content_preview` exactly.)**
3. **Tokens & cost** — `TokenCostBadge` + a recharts sparkline; displays `run_total_tokens` / `run_est_cost` from the **latest `token_usage` event** and the final from `run_finished` — **single source, no client summation** (UX fix: no double count). Status pill + **Cancel** (→ `POST /runs/{id}/cancel`).
RunDetail `/runs/:id` reuses the same panes for finished runs (replay via the events REST mirror).

### Agents `/agents` + AgentEditor (maximizes "configurable dimensions per agent")
List with avatar/provider/model/schedule badges. Editor (tabbed sheet) sections — **every dimension is a first-class control**: **Identity** (name, role), **Brain** (system_prompt editor, provider select → dependent `GET /models` model select), **Tools** (multiselect from the registry = "skills"), **Channels** (toggle telegram), **Schedule** (`ScheduleFields`: cron/interval builder with a **live "next fires" preview** via `/agents/{id}/schedule` or a validate call), **Memory** (window slider + summary switch), **Guardrails** (`GuardrailsFields`: max_steps/max_tokens/timeout). A **Test** box (`POST /agents/{id}/test`) for an instant 1:1 reply. Forms: react-hook-form + zod, 422 → inline field errors, optimistic save + toast.

### Tools `/tools` (registry + no-code HTTP builder)
List (builtin vs http badge, `agent_count`). ToolEditor: built-ins read-only (show params); **HTTP tool builder** — name, description, **method + URL template** (with `{placeholder}` chips), a **params-schema builder** (rows → JSON-Schema), headers, **auth** (type + env-var *name*), and **"Try it"** (`POST /tools/{id}/test {args}`) showing rendered URL + status (secrets redacted). This is the "add a custom tool, no code" story.

### Chat test-bench + Conversations
`/agents/{id}` has a **Chat** tab (`POST /agents/{id}/test` or `/chat`) to converse 1:1 in-app (mirrors the Telegram experience for the demo). `/conversations` lists channel chats (Telegram) with transcripts (persisted history, visible in UI — a requirement).

## Cross-cutting UX (the review's polish bar)
- **Every list has Empty / Loading(skeleton) / Error states** with a clear primary action (e.g. "Create your first agent", "Use a template").
- **Command palette** (`⌘K`) — jump to any agent/workflow/run, "New agent", "Run template".
- **Responsive** (sidebar collapses; canvas + drawers adapt); **a11y** (Radix = focus management + keyboard + ARIA; visible focus rings; color-contrast-checked tokens).
- **Optimistic + toasts** everywhere; destructive actions via `ConfirmDialog`.
- **"Feels live"**: WS-driven highlights, `ConnectionDot`, sub-second Groq responses.

## Tests (`frontend/src/__tests__/*`, vitest)
- `apiClient` error-envelope parsing (422 → field errors).
- `useMonitorSocket` reducer: dedupe + order by `(run_id,seq)`; reconnect backfill merge.
- `graphCodec` round-trip; client `validateGraph` mirrors the LLD 06 rules.
- (E2E is out of scope; backend critical-path tests live in LLD 11.)

## Decisions / tradeoffs
- **Templates + launchpad + prerequisite banner** directly serve the "time-to-first-workflow" metric and the demo — and the banner makes the LLM-key prerequisite honest (the review's #1 UX gap).
- **No surprise auto-run** — instantiate → builder → confirm Run modal (forgiveness + cost control), and the user sees the graph first.
- **One WS protocol + one envelope renderer** (per LLD 09) for live and replay — no drift, less code.
- **Single token/cost source** (`run_total_tokens`/`run_est_cost`) — accurate, matches the graded metric.
- **RunDrawer keyed by `?run=`** — deep-linkable, survives navigation, great for the live demo.
- **shadcn/Radix + tokens + dark-default** — modern, accessible, consistent polish for the 20% with minimal custom CSS.
- **Zustand only inside the builder** (local, high-churn canvas state); react-query owns all server state — clean separation.

---
*Next: [LLD 11 — Templates, packaging, tests, README](11-glue.md).*
