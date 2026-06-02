# Low-Level Design (LLD) — index

Detailed, build-ready design for the Agent Orchestration Platform, **one module at a time**. Each module is reviewed before the next. Source of truth for *what* we build: [`../HLD.md`](../HLD.md).

> **📌 What's current** — these LLDs are the *original* build-ready design; the platform is now **fully built** (154 tests) and evolved on top of them. For the current functionality + architecture see [`../features/README.md`](../features/README.md) and [`../HLD.md`](../HLD.md). Key deltas since these docs: **multi-tenant SaaS** · **per-turn conversational routing** + a **chat cockpit** · **OpenAPI tool-import** · **Dashboard analytics** · a full **template lifecycle** (Save-as-template / delete) · a **draft agent-tester** · **3** seed templates (not 2) and **9** seed agents · the support template is **"Support Router"** (a single **Supervisor** → Billing/Tech/Sales, looping back to itself) — the old **Triage/Escalation** pair was superseded · the sample-tenant seed is **`seed/sample_tenant.py`**.

## Module order (dependency-first)

| # | Module | Depends on | File |
|---|---|---|---|
| 01 | **Data model & persistence** — ORM, enums, DB setup | — | `01-data-model.md` |
| 02 | **LLM Gateway** — provider abstraction (Groq/Gemini/Ollama) + token meter | 01 | `02-llm-gateway.md` |
| 03 | **Tool system** — `Tool` interface, builtin + http executor, registry | 01, 02 | `03-tools.md` |
| 04 | **Message Bus** — async interface + in-process impl | — | `04-message-bus.md` |
| 05 | **Agent** — turn logic, memory, guardrails, output parsing | 02, 03, 04 | `05-agent.md` |
| 06 | **Graph Executor** — run lifecycle, nodes/edges/conditions/loops, events | 01, 04, 05 | `06-executor.md` |
| 07 | **Channels** — `Channel` interface + Telegram adapter | 01, 05 | `07-channels.md` |
| 08 | **Scheduler** — APScheduler triggers | 06 | `08-scheduler.md` |
| 09 | **Backend API & WebSocket** — routers, DTOs, contracts | all above | `09-api.md` |
| 10 | **Frontend** — pages, React Flow builder, monitor, API/WS client | 09 | `10-frontend.md` |
| 11 | **Templates, packaging, tests, README** | all | `11-glue.md` |

## Per-module LLD format
**Responsibility → Files → Interfaces/contracts (signatures & types) → Schema/logic → Dependencies & how it's used → Tests → Decisions/tradeoffs.**

> After all modules are signed off, we move to implementation (build), still module-by-module in the same order.
