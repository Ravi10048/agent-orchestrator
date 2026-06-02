# LLD 01 — Data Model & Persistence

> Module-by-module LLD. Foundation layer — every other module depends on this. Source: [HLD §7 (ER)](../HLD.md). Status: **for review**.

## Responsibility
Define the durable schema (SQLAlchemy 2.0 ORM over SQLite, Postgres-ready), the enums used across the app, and the DB session/engine bootstrap. No business logic here — just persistence.

## Files
```
backend/app/core/
  config.py        # Settings (env) — DATABASE_URL etc. (detailed in LLD 09; referenced here)
  db.py            # engine, SessionLocal, Base, get_db(), init_db()
backend/app/models/
  __init__.py      # import all models so create_all sees them
  enums.py         # str enums
  agent.py         # Agent (+ agent_tools association)
  tool.py          # Tool
  workflow.py      # Workflow
  run.py           # Run
  message.py       # Message
  conversation.py  # Conversation (channel chat session)
  event.py         # RunEvent
```

## DB bootstrap — `core/db.py`
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

class Base(DeclarativeBase):
    pass

# SQLite needs check_same_thread=False for FastAPI's threadpool; Postgres ignores it.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    import app.models  # noqa: F401 — register all models
    Base.metadata.create_all(bind=engine)
```
- **v1 migrations** = `create_all()` on startup (idempotent). **Prod** = Alembic (documented as next-step).
- `DATABASE_URL` default `sqlite:///./data/app.db`; switch to Postgres via env only.

## Enums — `models/enums.py`
```python
import enum
class RunStatus(str, enum.Enum):    PENDING="pending"; RUNNING="running"; COMPLETED="completed"; FAILED="failed"
class TriggerType(str, enum.Enum):  MANUAL="manual"; SCHEDULE="schedule"; CHANNEL="channel"
class ToolType(str, enum.Enum):     BUILTIN="builtin"; HTTP="http"
class ChannelType(str, enum.Enum):  INTERNAL="internal"; TELEGRAM="telegram"
class MessageRole(str, enum.Enum):  SYSTEM="system"; USER="user"; ASSISTANT="assistant"; TOOL="tool"
class EventType(str, enum.Enum):
    RUN_STARTED="run_started"; NODE_STARTED="node_started"; NODE_FINISHED="node_finished"
    AGENT_MESSAGE="agent_message"; TOOL_CALL="tool_call"; TOKEN_USAGE="token_usage"
    ERROR="error"; RUN_FINISHED="run_finished"
```

## Models

### Agent + agent_tools — `models/agent.py`
```python
from sqlalchemy import String, Text, JSON, ForeignKey, Table, Column, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base

agent_tools = Table(  # many-to-many: agent ↔ tool  (mirrors tool-registry tool_mapping)
    "agent_tools", Base.metadata,
    Column("agent_id", ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("tool_id",  ForeignKey("tools.id",  ondelete="CASCADE"), primary_key=True),
)

class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(120), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(40), default="groq")   # groq|gemini|ollama
    model: Mapped[str] = mapped_column(String(80), default="llama-3.3-70b-versatile")
    # config dimensions (JSON) — each is a "configurable dimension per agent"
    channels: Mapped[list]  = mapped_column(JSON, default=list)   # ENABLED channels only, e.g. ["telegram"] — chat_id lives on Conversation
    guardrails: Mapped[dict]= mapped_column(JSON, default=dict)   # {"max_steps":6,"max_tokens":4000,"timeout_s":60}
    memory_config: Mapped[dict] = mapped_column(JSON, default=dict)  # {"type":"short_term","window":12,"summary":false}
    schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"enabled":true,"cron":"*/5 * * * *"}
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    tools: Mapped[list["Tool"]] = relationship(secondary=agent_tools, lazy="selectin")
```
> "skills" (from the PDF) = the agent's mapped `tools`. "interaction rules" = the workflow edges/conditions (LLD 06), not stored on the agent.
> **Memory:** short-term = recent `Message` history fetched by `conversation_id`; optional **summary memory** is persisted on `Conversation.summary` (channel chats).

### Tool — `models/tool.py`
```python
class Tool(Base):
    __tablename__ = "tools"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(20), default="builtin")     # ToolType
    params_schema: Mapped[dict] = mapped_column(JSON, default=dict)      # JSON-Schema of args (advertised to LLM)
    # builtin:
    builtin_key: Mapped[str | None] = mapped_column(String(80), nullable=True)  # registry key → python fn
    # http (user-defined REST tool):
    http_method: Mapped[str | None] = mapped_column(String(10), nullable=True)  # GET/POST/...
    endpoint: Mapped[str | None]    = mapped_column(Text, nullable=True)        # URL template w/ {placeholders}
    headers: Mapped[dict | None]    = mapped_column(JSON, nullable=True)
    auth: Mapped[dict | None]       = mapped_column(JSON, nullable=True)        # {"type":"bearer","token_env":"X"}
    body_template: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

### Workflow — `models/workflow.py`
```python
class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # graph = {"nodes":[{"id","type","ref","config"}], "edges":[{"from","to","condition"}]}
    #   node.type ∈ start|agent|tool|router|end ; node.ref = agent_id/tool_id ; edge.condition = expr|null
    graph: Mapped[dict] = mapped_column(JSON, default=dict)
    is_template: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```
> **Graph validation (app-layer, no schema):** on save, check that every node `ref` resolves to an existing Agent/Tool id, there is exactly one `start`, an `end` is reachable, and there are no orphan nodes — reject invalid graphs with HTTP 400. At runtime the executor fails the run gracefully (emits an `error` event) if a `ref` went missing (e.g. an agent was deleted). This is the referential integrity a JSON column can't enforce.

### Run — `models/run.py`
```python
class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # RunStatus
    trigger: Mapped[str] = mapped_column(String(20), default="manual")              # TriggerType
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_tokens: Mapped[int] = mapped_column(default=0)
    est_cost: Mapped[float] = mapped_column(default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    messages: Mapped[list["Message"]]  = relationship(cascade="all, delete-orphan", lazy="selectin")
    events:   Mapped[list["RunEvent"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
```

### Message — `models/message.py`  (covers inter-agent + channel + history)
```python
class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String(120), index=True)  # run id or telegram chat id
    from_agent: Mapped[str] = mapped_column(String(120), default="")   # agent name | "user" | "system"
    to_agent: Mapped[str] = mapped_column(String(120), default="")     # agent name | "user"
    channel: Mapped[str] = mapped_column(String(20), default="internal")  # ChannelType
    role: Mapped[str] = mapped_column(String(20), default="assistant")    # MessageRole
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), index=True)
```
> `conversation_id` is the universal grouping key: channel messages use `str(conversation.id)`, workflow messages use `str(run.id)`.

### Conversation — `models/conversation.py`  (channel chat session: routing + summary memory)
```python
from sqlalchemy import UniqueConstraint
class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), default="telegram")    # ChannelType
    external_id: Mapped[str] = mapped_column(String(120), index=True)       # e.g. Telegram chat_id (learned at runtime)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)  # which agent answers this chat
    title: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")                  # rolling summary memory (when enabled)
    total_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    last_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_conv_channel_external"),)
```
> A `Conversation` is the **channel chat session** — created when a new `chat_id` first messages the bot. It routes that chat to `agent_id` and holds the per-chat `summary`. Workflow runs do **not** need a Conversation (they use `Run`).

### RunEvent — `models/event.py`  (live monitoring + persisted logs)
```python
class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))   # EventType
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), index=True)
```

## Relationships & indexes (summary)
- `Workflow 1—* Run`, `Run 1—* Message`, `Run 1—* RunEvent`, `Agent *—* Tool` (via `agent_tools`), `Agent 1—* Conversation`; a `Conversation` groups its channel `Message`s by `conversation_id = str(conversation.id)`.
- Indexes: `agents.name`, `tools.name`(unique), `workflows.name`, `workflows.is_template`, `runs.workflow_id`, `runs.status`, `messages.conversation_id`, `messages.run_id`, `messages.created_at`, `run_events.run_id`, `run_events.ts`, `conversations.external_id`, `conversations.agent_id`, unique(`conversations.channel`, `external_id`).
- JSON columns work natively on SQLite (text) and Postgres (jsonb) — no code change to swap.

## How other modules use this
- **API (09)** CRUDs Agent/Tool/Workflow, lists Run/Message/RunEvent.
- **Executor (06)** creates a Run, writes Message + RunEvent rows, updates Run status/tokens/cost/output.
- **Agent (05)** reads memory from Message history (by `conversation_id`).
- **Channels (07)** create/look up a `Conversation` per `chat_id` (routes chat→agent, holds summary), and persist inbound/outbound `Message` rows keyed by `conversation_id = str(conversation.id)`.

## Tests (`backend/tests/test_models.py`)
- create Agent with mapped Tools → reload → assoc intact.
- create Workflow(is_template=True) → query templates.
- create Run → add Messages + RunEvents → cascade delete on Run delete.
- create Conversation(channel, external_id) twice → unique constraint blocks the duplicate.
- (Critical-path "agent creation" test partly lives here; full CRUD test in LLD 09.)

## Decisions / tradeoffs
- **Workflow graph as a single JSON column** (not normalized node/edge tables): the graph is always read/written whole and is authored by React Flow as one document — JSON keeps it simple and matches the editor. Tradeoff: can't query individual nodes in SQL (we don't need to).
- **`agent_tools` association table** (not a JSON list on Agent): proper many-to-many, matches the ER and the tool-registry mapping pattern, lets us query "which agents use tool X" (useful for the monitor/registry).
- **One `Message` table for all message kinds** via `channel`/`from`/`to` — avoids 3 near-identical tables; `conversation_id` groups both runs and channel chats.
- **`RunEvent` separate from `Message`**: events are append-only telemetry (node/tool/token), messages are conversational content. Keeping them apart keeps the history view clean and the monitor stream cheap.
- **SQLite + JSON, Postgres-ready**: zero-infra single-command now; one env var to graduate.
- **`Conversation` as a thin channel-session overlay** (not a universal parent of all messages): it gives channel chats an identity (routes chat→agent), a home for summary memory, and per-chat token totals — without over-normalizing workflow messages, which stay under `Run`. Messages remain grouped by the string `conversation_id`.
- **`Agent.channels` = enablement, not chat ids**: a Telegram `chat_id` is dynamic (learned from inbound updates), so it belongs on `Conversation`, not on the agent config.
- **Graph referential integrity lives in the app layer** (validate-on-save + graceful runtime), since a JSON graph can't hold foreign keys.

---
*Next: [LLD 02 — LLM Gateway](02-llm-gateway.md). Reply "go" to continue, or flag changes to the schema first.*
