# LLD 11 — Templates, Packaging, Tests, README

> The glue: seed data, the **one-command** local run, the critical-path tests, and the README (the 10% doc). Consumes all of LLD 01–10.
>
> **📌 What's current:** the *original* sketch below shows **2 templates / 7 agents** with a **Triage → Escalation** support flow. The shipped build has **3 templates** (added *Collaborative Brief*) and **9 agents**, and Template 2 is **"Support Router"** — a single **Supervisor** routing to **Billing / Tech / Sales** that loops **back to itself** when unresolved (the Triage/Escalation pair was superseded; routing emerges from wiring the Supervisor to ≥2 specialists, injected into its prompt with their roles at runtime). The IKEA sample tenant lives in **`seed/sample_tenant.py`**. See [`../features/README.md`](../features/README.md) for the current picture.

## File layout (additions to the repo)
```
agent-orchestrator/
├── setup.sh                  # THE one command
├── Makefile                  # up / dev / seed / test / fmt / clean
├── docker-compose.yml        # backend + frontend + sqlite volume
├── .env.example              # all keys, blank
├── README.md                 # the graded doc
├── backend/
│   ├── Dockerfile            # python:3.12-slim → uvicorn
│   ├── requirements.txt
│   ├── app/seed/{__init__,tools,agents,graphs,templates}.py
│   └── tests/{conftest, test_*(per-module), test_seed, test_critical_paths}.py
└── frontend/
    ├── Dockerfile            # multi-stage: node build → nginx
    ├── nginx.conf            # serve dist; proxy /api + /ws → backend:8000
    └── vite.config.ts        # dev proxy /api,/ws → localhost:8000
```

## Seed (idempotent) — `app/seed/`
`run_seed(db)` runs in `lifespan` (and `python -m app.seed` for `make seed`). **Order: tools → agents → templates.** Upserts by unique key (`Tool.name`, `Agent.name`, `(Workflow.name, is_template)`), so it's safe to re-run.
- **Tools (3 built-ins, LLD 03):** `web_fetch`, `calculator`, `send_telegram`. (Custom HTTP tools are added in the UI — the registry demo.)
- **Agents (7):** for T1 → **Researcher** (`web_fetch`), **Writer**, **Notifier** (`send_telegram`); for T2 → **Triage**, **Billing**, **Tech**, **Escalation**. Each carries all config dimensions (provider/model/guardrails/memory/channels) — see `SEED_AGENTS`.
- **Templates (2):** graphs built by resolving agent **names → ids** at seed time (`graphs.py`), then **`validate_graph` is run at seed time so a drifted template fails loud**.

### Template T1 — "Research → Report → Notify" (linear + feedback loop)
```jsonc
{ "nodes":[
    {"id":"start","type":"start"},
    {"id":"researcher","type":"agent","ref":<Researcher>,"config":{"max_visits":3}},
    {"id":"writer","type":"agent","ref":<Writer>},
    {"id":"notifier","type":"agent","ref":<Notifier>},
    {"id":"end","type":"end"} ],
  "edges":[
    {"from":"start","to":"researcher"},
    {"from":"researcher","to":"writer"},
    {"from":"writer","to":"researcher","condition":"last.needs_more == true"}, // feedback loop (bounded by max_visits)
    {"from":"writer","to":"notifier"},                                         // default edge
    {"from":"notifier","to":"end"} ] }
```
Writer's prompt sets `needs_more=true` when research is thin → loops back (capped); else falls through to Notifier (sends via `send_telegram`). **2+ agents, real task, conditions + feedback.**

### Template T2 — "Support Triage" (LLM handoff + conditions + bounded escalation loop)
```jsonc
{ "nodes":[
    {"id":"start","type":"start"},
    {"id":"triage","type":"agent","ref":<Triage>,"config":{"max_visits":3}},
    {"id":"billing","type":"agent","ref":<Billing>},
    {"id":"tech","type":"agent","ref":<Tech>},
    {"id":"escalation","type":"agent","ref":<Escalation>,"config":{"max_visits":3}},
    {"id":"end","type":"end"} ],
  "edges":[
    {"from":"start","to":"triage"},
    {"from":"triage","to":"billing"},   // ← gives Triage allowed_routes=[Billing,Tech]; it calls handoff(...)
    {"from":"triage","to":"tech"},
    {"from":"billing","to":"escalation","condition":"last.resolved == false"},
    {"from":"billing","to":"end"},      // default
    {"from":"tech","to":"escalation","condition":"last.resolved == false"},
    {"from":"tech","to":"end"},         // default
    {"from":"escalation","to":"triage","condition":"attempts < 2"}, // bounded loop (attempts=escalation visits)
    {"from":"escalation","to":"end"} ] }
```
> **Review fix:** Triage has explicit out-edges to **Billing** and **Tech**, so its `allowed_routes` is populated and the `handoff` tool actually works (the prior draft had no such edges). Demonstrates **handoff routing + edge conditions + a bounded feedback loop** in one graph. Generous `max_visits` keeps demos from hitting the cap.

### `SEED_AGENTS` shape (excerpt)
```python
SEED_AGENTS = [
  dict(name="Researcher", role="Web researcher", tools=["web_fetch"], provider="groq",
       model="llama-3.3-70b-versatile", system_prompt="Research the topic with web_fetch; be concise, cite URLs.",
       guardrails={"max_steps":5,"max_tokens":1024,"max_tokens_total":8000,"timeout_s":60},
       memory_config={"type":"short_term","window":12,"summary":False}, channels=[]),
  dict(name="Triage", role="Support triage", tools=[], provider="groq", model="llama-3.3-70b-versatile",
       system_prompt="Classify the issue. Hand off to Billing or Tech via the handoff tool.", ...),
  # ... Writer, Notifier, Billing, Tech, Escalation
]
```
Billing/Tech prompts set `resolved=true|false`; Notifier uses `send_telegram`.

## Packaging — the ONE command
**`setup.sh`:**
```bash
#!/usr/bin/env bash
set -euo pipefail
[ -f .env ] || { cp .env.example .env; echo "→ created .env — add GROQ_API_KEY (and TELEGRAM_BOT_TOKEN for the channel)"; }
docker compose up --build      # backend :8000, frontend :5173 (nginx), seed runs on startup
```
**`docker-compose.yml`:** `backend` (build ./backend, env_file .env, volume `./data:/app/data` for SQLite, `:8000`) + `frontend` (build ./frontend, nginx serving the Vite build, proxy `/api`+`/ws`→backend, `:5173`). No external infra (Groq/Telegram are cloud SaaS; Ollama optional).
**`Makefile`:** `make up` (compose), `make dev` (native: backend `uvicorn app.main:app --reload`, frontend `npm run dev`), `make seed`, `make test` (pytest + vitest), `make fmt`, `make clean`.
**`.env.example`:** `DEFAULT_LLM_PROVIDER=groq`, `GROQ_API_KEY=`, `GEMINI_API_KEY=`, `OLLAMA_BASE_URL=http://localhost:11434`, `TELEGRAM_BOT_TOKEN=`, `DATABASE_URL=sqlite:///./data/app.db`, plus the executor/scheduler tunables.
> Single command, fully local, free. (Native `make dev` is the no-Docker fallback.)

## Tests
**`conftest.py`:** in-memory SQLite engine + `Base.metadata.create_all`, `TestClient(app)`, a **mock-LLM fixture** (`monkeypatch app.llm.complete` with scripted `LLMResult`s — deterministic, no network/keys), and a `seeded_db` fixture.
**Per-module** suites are owned by their LLDs (`test_models … test_scheduler … test_api`).
**`test_seed.py`:** `run_seed` is idempotent (re-run → stable counts); **both templates pass `validate_graph`**; agent↔tool mappings resolve.
**`test_critical_paths.py`** — the three the rubric names:
1. **Agent creation:** `POST /api/agents` (with tools/guardrails/memory) → 201; reload → tool mapping intact.
2. **Workflow execution:** scripted mock-LLM drives **T1** including **one feedback loop** (Writer `needs_more=true` → Researcher visit 2 → final report); assert `Run.status=completed`, ≥2 agents ran, token totals > 0, ordered events emitted, output captured.
3. **Message delivery:** an inbound Telegram update → `dispatch_inbound` (mock `getUpdates`/`send`) → `Conversation` created with `agent_id`, inbound+outbound `Message` rows persisted, reply sent.

## README.md (the 10% — outline)
1. **What it is** + a 30-sec GIF (the hero: template → run → live monitor → Telegram chat).
2. **Architecture diagram** (the HLD system diagram) + the 3-plane/4-layer overview.
3. **Quickstart** — the one command + the GROQ/Telegram key steps (how to get them, free).
4. **Runtime choice — why a custom runtime** (the LLD 05/06 justification + the "why not LangGraph" talking points; how routing rides native tool-calling).
5. **Concepts** — agents, tools (custom HTTP), workflows (graph: conditions + loops), runs, channels, schedules, the live monitor.
6. **How to extend** — add a workflow template · add a messaging channel (the `Channel` ABC) · add a tool (HTTP in the UI / built-in in code). *(Rubric explicitly asks for this.)*
7. **Testing** — `make test` + the 3 critical paths.
8. **Production next-steps** (the tradeoffs to discuss live) — parallel executor + barrier joins, real broker bus (Kafka/Rabbit) + DLQ, Postgres, auth/RBAC/multi-tenancy, webhooks + WhatsApp/Slack, distributed scheduler, secrets manager, observability stack.

## Decisions / tradeoffs
- **Templates seeded with their agents + `validate_graph` at seed time** — the "2-click" demo works on a fresh DB, and a drifted template fails loud at startup, not mid-demo.
- **T2 gives Triage real out-edges** so `handoff` works; both templates together cover handoff + conditions + feedback loops (the requirement), with generous `max_visits` so demos don't trip the cap.
- **`docker compose up` as the one command** (native `make dev` fallback) — portable + truly local; no paid infra.
- **Mock-LLM critical-path tests** — deterministic, run with **no API key/network** in CI, yet exercise the real executor/agent/channel code.
- **README leads with the demo + the runtime-choice justification** — the two things graded highest (40% demo, 30% architecture) and the live-session talking points.

---
## ✅ LLD complete
All 11 modules are designed and cross-checked. Build order = LLD order (01→11): data → LLM → tools → bus → agent → executor → channels → scheduler → API → frontend → seed/packaging/tests/README. See the [LLD index](README.md), the [HLD](../HLD.md), and the [evaluation-coverage matrix](../HLD.md#11-evaluation-coverage--every-criterion-in-the-pdf).
