# LLD 09 — Backend API & WebSocket

> The application seam the frontend + grader hit. Fronts the whole runtime (LLD 01–08). Status: **for review** — *hardened by the design + adversarial-review pass; this doc is the **authoritative contract** (the cross-doc drift the review caught — WS protocol, instantiate endpoint, `trigger` enum, `agent_message` fields, GraphValidationError attr — is resolved here and referenced by LLD 10/11).*

## Responsibility
One FastAPI app whose `lifespan` wires everything (DB, seed, channels, scheduler, the monitor hub), **six REST routers** returning Pydantic v2 DTOs, and **one `/ws/monitor` WebSocket** carrying a strict `EventEnvelope` (backfill-then-live). A **thin orchestration layer**: routers validate + persist + delegate to `RunService`/`SchedulerService`/the Channel registry — it never runs LLMs or graphs itself.

## File layout
```
backend/app/
  main.py            # create_app(), lifespan, exception handlers, CORS, /ws/monitor
  core/config.py     # Settings (pydantic-settings) — every env key LLD 01-08 referenced
  core/errors.py     # AppError hierarchy + ErrorEnvelope + install_exception_handlers
  core/deps.py       # get_db, get_run_service, get_scheduler, get_hub, get_settings
  api/__init__.py    # api_router (prefix="/api") includes all sub-routers
  api/schemas/       # DTOs: common, agent, tool, workflow, run, conversation, event
  api/routers/       # agents, tools, workflows, runs, conversations, meta
  ws/hub.py          # MonitorHub (singleton), Subscriber, EventEnvelope
  ws/monitor.py      # /ws/monitor endpoint (subscribe protocol + backfill)
```

## App wiring — `main.py`
```python
@asynccontextmanager
async def lifespan(app):
    init_db()                                              # LLD 01
    with SessionLocal() as db: run_seed(db)                # LLD 11: tools → agents → 2 templates (idempotent)
    hub = MonitorHub(); app.state.hub = hub                # singleton → injected into EventSink (LLD 06)
    rs  = RunService(SessionLocal, hub=hub, max_run_steps=settings.MAX_RUN_STEPS,
                     run_timeout_s=settings.RUN_TIMEOUT_S); app.state.run_service = rs
    sched = SchedulerService(rs, SessionLocal, default_tz=settings.SCHEDULER_TIMEZONE,
                             default_grace=settings.SCHEDULER_MISFIRE_GRACE); app.state.scheduler = sched
    if settings.TELEGRAM_BOT_TOKEN:                        # channel registered only if configured
        ch = TelegramChannel(settings.TELEGRAM_BOT_TOKEN, dispatcher=make_dispatcher(SessionLocal, hub),
                             poll_timeout=settings.TELEGRAM_POLL_TIMEOUT); register_channel(ch); await ch.start()
    sched.start(); sched.load_all_schedules()              # rebuild jobs from DB (LLD 08)
    try: yield
    finally:
        for ch in list_channels(): await ch.stop()
        await sched.shutdown(); await rs.shutdown(); await hub.close()

def create_app():
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan, default_response_class=ORJSONResponse)
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    install_exception_handlers(app); app.include_router(api_router)
    app.add_api_websocket_route("/ws/monitor", monitor_ws_endpoint); return app
```

## Config — `core/config.py`
`Settings(BaseSettings, env_file=".env")` with: `APP_NAME, ENV, DEBUG, HOST, PORT=8000, CORS_ORIGINS=[localhost:5173]`; `DATABASE_URL=sqlite:///./data/app.db`; `DEFAULT_LLM_PROVIDER=groq, GROQ_API_KEY, GEMINI_API_KEY, OLLAMA_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES, LLM_FALLBACK_PROVIDER`; `TELEGRAM_BOT_TOKEN, TELEGRAM_POLL_TIMEOUT=30`; `SCHEDULER_TIMEZONE=UTC, SCHEDULER_MISFIRE_GRACE=3600`; `MAX_RUN_STEPS=50, DEFAULT_MAX_VISITS=8, RUN_TIMEOUT_S=300`; `WS_BACKFILL_LIMIT=500`. (Single place for all LLD 01–08 env keys.)

## Error envelope — `core/errors.py` (every error has this exact shape)
```python
class ErrorEnvelope(BaseModel): error: ErrorBody
class ErrorBody(BaseModel): code: str; message: str; details: Any | None = None
# AppError → (status, code):
#  ResourceNotFound→404 not_found · GraphValidationError→400 graph_invalid (details=e.errors:list[str], LLD 06)
#  ScheduleConfigError→400 schedule_invalid · ChannelNotConfigured→409 channel_unconfigured · ConflictError→409 conflict
#  RequestValidationError→422 validation_error (details=exc.errors()) · Exception→500 internal (message hidden unless DEBUG)
```
> **Consistency fix:** `GraphValidationError` exposes `.errors: list[str]` (LLD 06 standard); the handler puts it in `details`. `POST /api/workflows/validate` returns **200** `{valid, errors}` (it's a check, not a failure).

## REST API (all under `/api`; DTOs are `Create`/`Update`/`Out`; `Page[T]={items,total,limit,offset}`)
**Agents** — `GET /agents` · `POST /agents` · `GET/PATCH/DELETE /agents/{id}` · `PUT /agents/{id}/tools {tool_ids:[int]}` · `PUT /agents/{id}/schedule ScheduleDTO` (validate→400 then upsert job) · `POST /agents/{id}/test {message}` → 1:1 reply (no persist).
`AgentCreate{name*, role, system_prompt, provider="groq", model, tool_ids:[int], channels:[str], guardrails:{max_steps=6,max_tokens=1024,max_tokens_total=8000,timeout_s=60}, memory_config:{type="short_term",window=12,summary=false}, schedule:ScheduleDTO|None}` → `AgentOut{…, tools:[ToolOut], created_at, updated_at}`.

**Tools** — `GET /tools` · `POST /tools` · `GET/PATCH/DELETE /tools/{id}` (409 if mapped & not `?force`) · `POST /tools/{id}/test {args}` → executes via `execute_tool_call` (secrets redacted, returns rendered_url/status).
`ToolCreate{name*, description, type:"builtin"|"http", params_schema:{}, builtin_key?, http_method?, endpoint?, headers?, auth?:AuthDTO, body_template?}`. **`AuthDTO` carries env-var *names* only — never secret values** (also redacted in `ToolOut`).

**Workflows** — `GET /workflows?is_template=` · `GET /templates` (sugar) · `POST /workflows` (validate_graph→400) · `GET /workflows/{id}` · `PUT /workflows/{id}` · `POST /workflows/validate {graph}` → 200 `{valid,errors}` · **`POST /workflows/{id}/instantiate {name?}` → 201 editable copy** (is_template=false; graph deep-copied; agent refs reused — the **single** "Use template" endpoint) · `DELETE /workflows/{id}`.
`GraphDTO{nodes:[{id,type,ref?,config?}], edges:[{from,to,condition?}]}`.

**Runs** — `POST /runs {workflow_id*, input={}, trigger}` → 201 `RunOut` (starts via `RunService.start_run`, returns `run_id` immediately) · `GET /runs` · `GET /runs/{id}` → `RunDetailOut` · `POST /runs/{id}/cancel` (409 if finished) · **`GET /runs/{id}/events?after_seq=&limit=` → `[EventEnvelope]`** (REST mirror of the WS stream — reconnect/replay source) · `GET /runs/{id}/messages` → `Page[MessageOut]`.
> **Consistency fix:** `RunCreate.trigger: Literal["manual","schedule","channel"]="manual"` (constrained → no 422); API does `TriggerType(body.trigger)`.

**Conversations** (channel history) — `GET /conversations?agent_id=&channel=` · `GET /conversations/{id}` · `GET /conversations/{id}/messages` (by `conversation_id=str(id)`, ordered).
**Meta** — `GET /health` → `{ok, llm_provider, llm_key_present:bool, telegram_present:bool, db:"ok"}` (drives the frontend onboarding/status banner) · `GET /models?provider=` → selectable models.

## WebSocket — `/ws/monitor` (THE one protocol)
**Handshake:** client connects, then sends `{"action":"subscribe","run_id":N}` (or `{"action":"subscribe_all"}` for the dashboard; `{"action":"unsubscribe","run_id":N}`). Server flow per subscribe (zero-gap):
1. **register** the `Subscriber` on the `MonitorHub` (live events for that run now buffer), 2. **backfill** past `RunEvent`s for the run (ordered by `seq`, ≤ `WS_BACKFILL_LIMIT`) as normal envelopes, 3. **flush** buffered live events. The client **dedupes by `(run_id, seq)`**, so backfill/live overlap is harmless.
**Reconnect:** client refetches `GET /runs/{id}/events?after_seq=<lastSeq>` then re-subscribes — same dedup. (WS = live tail + initial backfill; the REST events endpoint = reconnect catch-up. One renderer for both.)

**`EventEnvelope`** (identical for WS + REST replay):
```jsonc
{ "run_id": 12, "seq": 7, "type": "node_finished", "ts": "2026-…Z", "event_id": 41,
  "payload": { /* exact LLD 06 taxonomy per type */ } }
```
Payloads follow the LLD 06 table verbatim. **Consistency fix (graded metric):** `agent_message.payload = {msg_id, from_agent, to_agent, content_preview, broadcast}` (the frontend reads these exact names — prevents a blank inter-agent feed). `token_usage.payload` includes `run_total_tokens` + `run_est_cost` (**single source** — the frontend displays these, never client-sums per-event → no double count).

## Request flows (the load-bearing handlers)
- **Agent CRUD ↔ scheduler (no drift):** `validate_schedule` (→400) **before** commit; `upsert_agent_schedule` **after** commit; DELETE does `remove_agent_schedule` then delete (cascade-unmaps tools). Tool mapping `PUT` replaces the association atomically.
- **Workflow save** reuses `RunService.executor.validate_graph` (the single source of truth, LLD 06) → 400 `graph_invalid{details:[...]}`; templates are seeded/trusted (skip).
- **Run start** returns `run_id` synchronously; the executor runs as a background task (LLD 06); the client immediately opens the WS → backfill replays the few already-emitted events (no visible gap).

## Tests (`backend/tests/test_api.py`) — critical-path "agent creation"
- agents CRUD + tool-mapping `PUT` (mapping intact on reload); bad `schedule` → 400 before persist.
- workflow `POST` with an invalid graph → 400 `graph_invalid` (details listing node errors); `/validate` → 200 `{valid:false,errors}`.
- `POST /workflows/{id}/instantiate` → editable copy (is_template=false), refs reused.
- `POST /runs` → 201 + `run_id`; `/runs/{id}/events?after_seq=` returns ordered envelopes; `/cancel` on a finished run → 409.
- WS: subscribe → backfill (seq-ordered) then live; dedupe holds.
- error envelope shape for 404/400/409/422.

## Decisions / tradeoffs
- **This doc is the single contract** — LLD 10 (frontend) and LLD 11 (seed/tests) consume these exact shapes; the review's cross-doc drift is resolved here.
- **Thin routers, delegate to services** — keeps the API testable and the runtime reusable (CLI/scheduler/channel all reuse `RunService`).
- **One `MonitorHub` singleton in `lifespan`**, injected into `EventSink` — live fan-out + DB-backed backfill = zero-gap, replayable streams.
- **WS subscribe-message protocol + seq-dedupe + REST events mirror** — one robust handshake, trivial reconnect, one renderer for live & history.
- **Secrets are env-var *names*** in tool DTOs (never values) — safe to display/store.

---
*Next: [LLD 10 — Frontend](10-frontend.md).*
