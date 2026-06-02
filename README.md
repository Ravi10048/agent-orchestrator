# Agent Orchestrator

> An **AI Agent Orchestration Platform** — create agents, configure every dimension
> (personality, tools, memory, guardrails, schedules), wire them into **collaborative
> multi-agent workflows** with conditions and feedback loops, run them on a **real custom
> runtime** that executes real tools, **chat with an agent live over Telegram**, and watch
> everything stream in a **live monitor** (timeline · inter-agent messages · token/cost).
> Runs **fully local with one command**.

Built for the Yuno AI-Engineer challenge. Stack is **all free**: FastAPI + a custom
graph-executor runtime + SQLite + **Groq** (free LLM) + **Telegram** (free channel) +
React 19 / React Flow.

---

## Table of contents
1. [What it does](#1-what-it-does)
2. [Architecture](#2-architecture)
3. [Quickstart (one command)](#3-quickstart-one-command)
4. [Why a custom runtime](#4-why-a-custom-runtime)
5. [Core concepts](#5-core-concepts)
6. [How to extend](#6-how-to-extend)
7. [Testing](#7-testing)
8. [Production next-steps](#8-production-next-steps)

---

## 1. What it does

The **30-second hero demo**: open the app → **Templates** → *Use* **“Support Router”** → type
*any* support question → watch the **Graph** view as a **Supervisor** reads it and **routes** it
to the right specialist — Billing, Tech, or Sales — which then answers (the Supervisor returns the
next agent **and** a short reply; unresolved cases loop back to re-route). Then try **“Research →
Report → Notify”** to see a pipeline with a feedback loop deliver a brief over Telegram, or message
the bot directly to chat 1:1 with the **Supervisor**. (Run `make demo` to pre-populate example runs.)

It's **multi-tenant**: the sidebar **tenant switcher** flips between **Acme Support** (the generic
team above) and **IKEA India** — a real use case where **“Riya”** (a Supervisor on **Telegram**)
re-engages an abandoned cart by routing the customer's barrier to the right specialist — Pricing &
EMI, Delivery, Payments, Product, Retention, Care, and **Notify** (delivers the secure checkout link
to the customer's Telegram) — each backed by HTTP tools (cart, pincode, EMI, payment link…). Open it
in the **live chat playground** (*Workflows → Chat*) to converse with the workflow and watch the graph
route **each turn** in real time. Each tenant is fully isolated; a new one starts with the default tools, and you build your own agents (routing emerges when you connect a router agent to others in a workflow).

| Capability | Where |
|---|---|
| **Agent CRUD + full config** — role, system prompt, model/provider, tool allow-list, channels, memory, guardrails | Agents page + editor |
| **Tool registry** — 3 built-ins + a **no-code HTTP tool builder** (method, URL template, params→JSON-Schema, env-based auth) | Tools page |
| **Visual workflow builder** — React Flow canvas, condition editor, live validation, **conditions + feedback loops** | Workflow Builder |
| **3 pre-built templates** — Support Router (supervisor routing), Collaborative Brief (send_message), Research→Report→Notify | Templates page (seeded) |
| **Multi-tenant SaaS** — each tenant owns its agents/tools/workflows/runs (row-level isolation); a new tenant starts with the default tools (you build the agents) | Sidebar tenant switcher (`X-Tenant-Id`) |
| **External channel** — Telegram (long-poll), ≥1 agent reachable for live human chat | Conversations page |
| **Conversational per-turn routing + chat playground** — chat with a whole *workflow*; each turn routes through the supervisor to the right specialist (sticky `curr_agent`), in a split-screen **cockpit** where the graph lights up live (travelling pulse on the active route · spotlight + camera-follow on the running agent · "now running" badge · activity ticker) | *Workflows → Chat* / *Builder → Chat* |
| **Live monitoring** — real-time event timeline, **inter-agent messages**, **token/cost** | Run Monitor (the `?run=` drawer) |
| **Scheduling** — cron / interval agent runs (APScheduler) | Agent editor |
| **Persisted history** — runs, events, and conversations all stored and visible | Runs / Conversations |

### Impact metrics
The challenge names four impact metrics; here's how the platform delivers each (the Dashboard
surfaces them live in an **Impact** panel):

| Metric | How it's delivered |
|---|---|
| **# configurable dimensions per agent** | **9** — role · system prompt · provider · model · tool allow-list · channels · memory · guardrails · schedule |
| **Time from zero to a working multi-agent workflow** | **~2 clicks** — Templates → *Use* → *Run* (3 templates seed on startup; `make demo` pre-populates example runs, so a fresh DB is demo-ready) |
| **End-to-end task completion rate** | Live: completed ÷ total runs (shown on the Dashboard) |
| **Agent-to-agent message reliability** | **At-least-once** — the in-process bus drains per-agent inboxes; the Telegram channel advances its offset only *after* handling; all messages are persisted and visible |

### Requirements coverage
Every requirement in the challenge brief, mapped to where it lives and its test (✓ = done):

| Challenge requirement | Where it's implemented | Test |
|---|---|---|
| ✓ Agent CRUD (name·role·prompt·model·tools·channels) | `api/routers/agents.py` · Agents page/editor | `test_critical_paths.py` (agent creation) |
| ✓ Agent config (schedules·memory·skills·rules·guardrails) | `models/agent.py` · Agent editor | `test_api.py`, `test_scheduler.py` |
| ✓ Visual workflow builder + **conditions + feedback loops** | `pages/WorkflowBuilder.tsx` · `runtime/executor.py` (`eval_condition`, `max_visits`) | `test_executor.py` |
| ✓ ≥2 pre-built templates (**3 seeded**) | `seed/templates.py` + `seed/graphs.py` | `test_seed.py` |
| ✓ External channel (WhatsApp/Telegram/Slack) — **Telegram** | `channels/telegram.py` · `channels/dispatcher.py` | `test_channels.py` |
| ✓ ≥1 agent reachable for live human chat | the Supervisor / "Riya" (Telegram) | `test_critical_paths.py` (message delivery) |
| ✓ Real runtime executes real tools (not a mockup) | `runtime/executor.py` + `runtime/agent.py` + `runtime/tools/` | `test_executor.py`, `test_tools.py` |
| ✓ Agents communicate **asynchronously** (agent-to-agent) | `runtime/bus/` + `send_message` (Collaborative Brief) | `test_bus.py` |
| ✓ Live monitoring (logs · inter-agent msgs · token/cost) | `runtime/events.py` + `ws/monitor.py` · Run Monitor | `test_api.py` |
| ✓ Message history persisted + visible in the UI | `models/{message,run_event}.py` · Runs/Conversations | `test_critical_paths.py` |
| ✓ Working demo, 2+ agents on a real task | Research→Report→Notify · Support Router · IKEA cart-recovery | `test_critical_paths.py` (workflow execution) |
| ✓ Single setup command, fully local | `./setup.sh` (Docker) · `./start.sh` (native) | — |
| ✓ Tests for the 3 critical paths | agent creation · workflow execution · message delivery | `test_critical_paths.py` |
| ✓ Clean UI / runtime / persistence layer separation | `frontend/` + `api/` · `runtime/` · `models/` + `core/db.py` | (see Architecture) |
| ✓ README (arch diagram · setup · runtime justification · how-to-extend) | this file (§2 · §3 · §4 · §6) | — |
| ➕ **Beyond the brief** — multi-tenant SaaS · per-turn conversational routing · live chat cockpit · OpenAPI tool-import | `models/tenant.py` · `runtime/conversation_router.py` · `pages/WorkflowChat.tsx` · `runtime/tools/openapi_import.py` | `test_tenants.py`, `test_conversation_routing.py`, `test_openapi_import.py` |

---

## 2. Architecture

Three planes, glued by an in-process event bus and a single SQLite database. The **frontend**
talks to a **FastAPI** REST + WebSocket layer; the **custom runtime** executes graphs; **Groq**
serves the LLM and **Telegram** is the human channel.

```mermaid
flowchart TB
  subgraph UI["Frontend — React 19 · Vite · Tailwind · React Flow"]
    BLD["Workflow Builder"]
    MON["Live Monitor (?run=)"]
    CFG["Agents · Tools · Templates · Conversations"]
  end

  subgraph API["API — FastAPI"]
    REST["REST routers<br/>(agents · tools · workflows · runs · conversations · meta)"]
    WS["WebSocket /ws/monitor"]
  end

  subgraph RT["Custom Runtime"]
    RS["RunService<br/>(lifecycle + cancel)"]
    EX["Graph Executor<br/>(sequential cursor walk)"]
    AG["AgentRunner<br/>(turn loop + routing)"]
    GW["LLM Gateway<br/>(provider-agnostic)"]
    TR["Tool Registry<br/>(builtin + HTTP)"]
    BUS(["In-process Bus<br/>(agent-to-agent)"])
    SINK["EventSink<br/>(seq · tokens · fan-out)"]
  end

  CH["Telegram Channel<br/>(long-poll)"]
  SCH["Scheduler<br/>(APScheduler)"]
  DB[("SQLite<br/>(Postgres-ready)")]
  LLMP["Groq / Gemini / Ollama"]
  TG["Telegram Bot API"]

  UI <--> REST
  MON <-. live events .- WS
  REST --> RS --> EX --> AG --> GW --> LLMP
  EX --> TR --> TG
  AG <--> BUS
  AG --> SINK --> WS
  EX --> DB
  CH --> RS
  SCH --> RS
  CFG --> REST

  classDef p fill:#1e1b4b,stroke:#6d5efc,color:#fff;
  class RT,API p;
```

**Three planes**
- **Build** — design an agent / a workflow graph in the UI; validate it; save it.
- **Runtime** — `RunService` creates a `Run`, the **Graph Executor** walks the graph node-by-node,
  each agent node runs an **`AgentRunner`** (prompt → LLM → tool loop → result), routing to the
  next node via the agent’s **`handoff`** tool **or** edge **conditions**. Agents talk to peers via
  the **`send_message`** bus tool. Every step emits an event.
- **Observability** — the **`EventSink`** stamps a per-run `seq`, persists each `RunEvent`,
  aggregates tokens/cost (single source), and fans out to the **WebSocket** so the Live Monitor
  renders in real time (and replays finished runs from the same event log).

**Tech stack** — Python 3.12 · FastAPI + WebSocket · SQLAlchemy 2.0 / SQLite ·
custom graph-executor runtime · Groq (OpenAI-compatible) with Gemini/Ollama behind the same
gateway · Telegram long-poll · APScheduler · React 19 + Vite + TS + Tailwind + React Flow +
@tanstack/react-query + recharts · Docker Compose.

**Default ports** — backend `:8000`, frontend `:5173` (Docker) / `:5174` (Vite dev).

---

## 3. Quickstart (one command)

**Prerequisites:** Docker (for `./setup.sh`) **or** Python 3.12+ & Node 20+ (for the native `./start.sh`). A free **Groq** API key to run agents.

```bash
git clone https://github.com/Ravi10048/agent-orchestrator.git
cd agent-orchestrator
./setup.sh
# first run copies .env.example → .env, then: docker compose up --build
# backend  → http://localhost:8000   (API at /api, health at /api/health)
# frontend → http://localhost:5173
```

To actually **run agents** and **use the channel**, add free keys to `.env` and restart:

```ini
GROQ_API_KEY=...          # free at https://console.groq.com  (required to run agents)
TELEGRAM_BOT_TOKEN=...    # free from @BotFather on Telegram   (optional — enables the channel)
```

The seed — the default **Acme** tenant (3 tools · 9 agents · 3 templates) **plus a sample IKEA
tenant** (cart-recovery tools · a Supervisor + 7 specialists · the *Abandoned-Cart Recovery*
workflow) — runs **idempotently on every startup**, so a fresh DB is demo-ready immediately (and
`make demo` adds example runs). The Dashboard shows a banner if a key is missing.

**Native (no Docker) — one command** (after a one-time install: `cd backend && python -m venv .venv && ./.venv/bin/pip install -r requirements.txt`, and `cd frontend && npm install`):
```bash
./start.sh    # starts backend :8000 + mock API :8001 + the Vite frontend (auto-port); logs → .run/
./stop.sh     # tears it all down — only this stack's ports (leaves other apps, e.g. :5173, running)
```
`start.sh` waits for health and **prints the frontend URL it chose** (Vite uses `:5173`, or the next free
port if `:5173` is busy). Manual fallback (separate shells): `cd backend && ./.venv/bin/uvicorn app.main:app --port 8000`
· `make mock` (the `:8001` mock API the sample tenant's HTTP tools call) · `cd frontend && npm run dev`
· `make seed` (idempotent).

### Demo walkthrough (the recorded demo)
A ~90-second end-to-end run, all visible in the UI:
1. **Run a multi-agent workflow.** *Acme Support* tenant → **Workflows → “Research → Report → Notify” → Run**
   (type a topic) → open the **Run Monitor**: watch *Researcher → Writer → Notifier* execute live with
   inter-agent messages + token/cost; the **Graph** view replays the exact path.
2. **Chat with a workflow (live routing cockpit).** Switch to **IKEA India** → **Workflows → Chat** on
   *Abandoned-Cart Recovery*. As you type, the left graph animates the routing **per turn**:
   *“the sofa is too expensive”* → **Pricing** (No-Cost EMI) · *“will it deliver to 560001?”* → **Delivery**
   · *“this is terrible, I want a refund / a human”* → **Care** (escalates) · *“send the checkout link to my
   telegram”* → **Notify** (delivers via the bot, or truthfully says no Telegram chat is connected).
3. **Talk to it over Telegram.** Message the bot → “Riya” (the Supervisor) routes each message to the right
   specialist; the whole conversation is persisted and visible under **Conversations**.

> **🎥 [Watch the recorded demo (3 min) →](https://drive.google.com/file/d/16WXCRnUVgwVplms2iK_0sF6IvUgeuEYR/view?usp=sharing)** — the full narrated end-to-end walkthrough.

---

## 4. Why a custom runtime

The challenge allows any runtime; I built a **custom graph executor** rather than adopting
LangGraph/AutoGen/CrewAI. Reasoning:

- **Explicit and reviewable.** The orchestration *is* the product here, so the control flow —
  cursor walk, routing precedence (`handoff` → conditions → default edge), cap enforcement on
  every path, event taxonomy — is written plainly in ~one file (`runtime/executor.py`) instead of
  hidden behind a framework. That makes it auditable and easy to reason about in review.
- **Routing rides native tool-calling.** Agents route by *calling a tool* (`handoff`, `send_message`)
  — the same mechanism they use for everything else — instead of a bespoke DSL. Conditions are a
  tiny **safe AST evaluator** (`last.needs_more == true`, `attempts < 2`), not arbitrary `eval`.
- **Correctness-first.** Caps (global `max_run_steps`, per-node `max_visits`, run timeout) are
  enforced on **every** terminal path → a breach **fails** the run (never a silent “completed”).
  Cancel is cooperative between nodes. These were hardened by an adversarial multi-agent review.
- **Honest about the trade-off.** v1 is a **sequential single-cursor walk** — simple and
  predictable. Parallel fan-out / barrier joins are the documented #1 next-step (§8). LangGraph’s
  durable, parallel, checkpointed execution is genuinely strong; for a reviewable prototype where
  the orchestration logic is the thing being evaluated, owning it end-to-end won out.

The **LLM layer is provider-agnostic** (one OpenAI-compatible gateway → Groq default, Gemini and
local Ollama behind the same interface, with timeout/retry/fallback and cost estimation), so the
runtime isn’t coupled to any vendor.

---

## 5. Core concepts

- **Agent** — a configured persona: `role`, `system_prompt`, `provider`/`model`, a **tool
  allow-list** (its “skills”), enabled **channels**, **memory** (short-term window + optional
  rolling summary), and **guardrails** (max steps/tokens/timeout). Reused unchanged for workflow
  nodes *and* 1:1 channel chat.
- **Tool** — `builtin` (Python fn: `web_fetch`, `calculator`, `send_telegram`) or `http` (a no-code
  REST tool defined in the UI: method, URL template with `{placeholders}`, params→JSON-Schema,
  headers, env-var-based auth). The tool executor **never raises** and always times out.
- **Workflow** — a graph of nodes (`start · agent · tool · router · end`) and edges with optional
  **conditions**. Validated in the app layer (one start, reachable end, resolvable refs, a default
  edge on every branch). Supports **feedback loops** (bounded by `max_visits`).
- **Run** — one execution of a workflow. Produces an ordered stream of **`RunEvent`s**
  (`run_started · node_started · node_finished · agent_message · tool_call · token_usage · error ·
  run_finished`) and persists inter-agent **messages**.
- **Channel** — an external messaging seam (Telegram implemented via long-poll). Inbound messages
  resolve to a persisted **Conversation** → a turn → a reply. A plain conversation is **1:1** with one
  agent; a **workflow-bound** conversation routes **each turn** through the workflow's supervisor
  (supervisor-style `{next-agent, reply}`), so the right specialist answers per message, with a sticky
  `curr_agent` for continuity (`runtime/conversation_router.py`).
- **Chat playground** — a full-screen split view (`/workflows/:id/chat`): chat with a workflow on the
  right while the graph animates the routing **live** on the left — a travelling pulse on the active
  edge, a spotlight + camera-follow on the running agent, a "now running" badge, an active-agent
  inspector, and an activity ticker. Reachable from a **Chat** button on the Workflows list *and*
  inside the Builder. Every session is persisted and visible in Conversations.
- **Schedule** — cron/interval triggers (APScheduler) that start an agent or workflow run.
- **Live Monitor** — subscribes to `/ws/monitor`, renders the timeline / inter-agent thread /
  token-cost meters live, and **replays** finished runs from the same event log (gap-filled via
  `GET /api/runs/{id}/events?after_seq=`).

---

## 6. How to extend

**Add a workflow template** — add an entry to `backend/app/seed/templates.py` (`SEED_TEMPLATES`)
with a graph builder in `backend/app/seed/graphs.py` (resolve agent **names → ids**; return
`{nodes, edges}`). It’s **validated at seed time**, so a drift fails loudly at startup. Re-seed
with `make seed` (idempotent). Or just build one visually in the UI and click *Save as template*.

**Add a messaging channel** (e.g. Slack/WhatsApp) — implement the `Channel` ABC in
`backend/app/channels/` (`start` / `stop` / `send` / `handle_update` → normalised
`InboundMessage`), `register_channel(...)` it in the lifespan wiring (`app/main.py`), and add it to
an agent’s `channels`. The **dispatcher is channel-agnostic** — it already resolves agent →
conversation → reply, so no dispatch code changes.

**Add a tool** — *no-code:* build an HTTP tool in the **Tools** page (params become the LLM-facing
JSON-Schema; secrets are referenced by **env-var name only**, never stored). *In code:* add a
function to `backend/app/runtime/tools/builtins/`, register it with `@builtin`, and seed a `Tool`
row in `backend/app/runtime/tools/seed.py`.

**Add a tenant** — the platform is generic; a tenant is just an isolated owner of agents/tools/
workflows. `create_tenant(db, name)` (`backend/app/seed/tenants.py`) bootstraps one with the default
built-in tools; then seed its agents/tools/workflow exactly like the worked example in
`backend/app/seed/sample_tenant.py` (`seed_sample_tenant` — tools → agents → a router workflow; a
self-contained sample, independent of the default Acme tenant). At runtime, scope any request to a
tenant with the **`X-Tenant-Id`** header (the sidebar switcher sets it).

---

## 7. Testing

```bash
make test          # backend pytest (+ frontend vitest if present)
cd backend && pytest -q          # 154 tests
cd backend && ruff check .       # lint
cd frontend && tsc --noEmit && vitest run && vite build   # frontend type-check + tests + build
```

Per-module suites cover each LLD layer (models, LLM gateway, tools, bus, agent, executor,
channels, scheduler, API) plus multi-tenancy and the conversational per-turn routing
(`test_conversation_routing.py`). On top, **`test_seed.py`** (idempotency, all 3 templates pass
`validate_graph`, agent↔tool mappings, the sample tenant) and **`test_critical_paths.py`** exercise the three paths
the rubric names, against the **real** executor/agent/channel code with a **mock LLM** (no API key
or network needed):

1. **Agent creation** — `POST /api/agents` with tools/guardrails/memory → 201; reload is intact.
2. **Workflow execution** — template T1 runs **including one feedback loop** (Writer requests more
   → Researcher runs twice → final brief) → `status=completed`, ≥2 agents, ordered events, tokens > 0.
3. **Message delivery** — an inbound Telegram message → a `Conversation` bound to an agent, inbound
   + outbound `Message` rows persisted, reply delivered to the chat.

---

## 8. Production next-steps

A production-minded **prototype** — genuinely working, clean, and tested, running locally on one
command. What I’d harden next (and the trade-offs I’d discuss):

- **Parallel executor** — fan-out branches + barrier joins (v1 is a sequential single-cursor walk).
- **Durable bus** — swap the in-process asyncio bus for a real broker (Redis/Rabbit/Kafka) + a DLQ
  so agent-to-agent delivery survives restarts and scales across workers.
- **Postgres** — flip one env var (SQLAlchemy is DB-agnostic); add Alembic migrations.
- **Persistent scheduler jobstore** — cross-restart catch-up (current MemoryJobStore reloads from
  the DB but drops runs missed while the process was down).
- **AuthN/Z + multi-tenancy** — users, RBAC, per-tenant isolation; a real secrets manager for tool
  auth (today: env-var references, redacted in all DTOs).
- **More channels** — Slack / WhatsApp / webhooks via the same `Channel` ABC.
- **Observability** — structured logs → an aggregator, traces, and run/cost dashboards beyond the
  built-in live monitor.

---

## Design docs
- [Features & Architecture](docs/features/README.md) · [High-Level Design](docs/HLD.md) ·
  [Low-Level Design 01–11](docs/lld/README.md) · [Build a workflow (hands-on)](docs/BUILD_A_WORKFLOW.md)
