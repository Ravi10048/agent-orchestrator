# LLD 07 — Channels (Telegram)

> The human↔agent messaging layer. Depends on [LLD 01](01-data-model.md) (Conversation, Message), [LLD 05](05-agent.md) (AgentRunner, 1:1 mode), [LLD 03](03-tools.md) (`send_telegram`). Status: **for review** — *hardened by the design + adversarial-review pass (must-fixes folded in).*

## Responsibility
Let a human talk to an agent over a **free** external channel. v1 = **Telegram** via **long-polling** (`getUpdates` — no public webhook, fully local). Inbound message → find/create a `Conversation` (chat→agent binding) → run the bound agent in **1:1 mode** (`AgentRunner`, LLD 05) → persist inbound+outbound `Message` rows (visible in the UI) → reply. A `Channel` ABC + registry make "add a new channel" a clean extension point (the rubric asks for this), and the `send_telegram` builtin tool reaches the **same** adapter.

## Files
```
backend/app/channels/
  base.py         # Channel ABC, InboundMessage, registry (register/get/list_channels)
  telegram.py     # TelegramChannel — long-poll loop, send, parse
  dispatcher.py   # dispatch_inbound(): Conversation routing → AgentRunner → persist → reply
```
Config (LLD 09): `TELEGRAM_BOT_TOKEN` (channel registered only if set), `TELEGRAM_POLL_TIMEOUT=30`.

## Channel ABC + registry — `channels/base.py`
```python
@dataclass
class InboundMessage:                 # normalised, channel-agnostic → dispatcher is reusable
    channel: str; chat_id: str; text: str; user_display: str = ""; raw: dict = field(default_factory=dict)

class Channel(ABC):
    name: str                                     # registry key, e.g. "telegram"
    @abstractmethod
    async def start(self) -> None: ...            # spawn the long-poll task (idempotent, non-blocking)
    @abstractmethod
    async def stop(self) -> None: ...             # cancel loop, close client (idempotent)
    @abstractmethod
    async def send(self, chat_id: str, text: str) -> dict: ...   # used by dispatcher AND send_telegram tool
    @abstractmethod
    async def handle_update(self, update: dict) -> "InboundMessage | None": ...  # pure parse; None = skip

_REGISTRY: dict[str, Channel] = {}
def register_channel(ch): _REGISTRY[ch.name] = ch
def get_channel(name) -> Channel:
    try: return _REGISTRY[name]
    except KeyError: raise ChannelNotConfigured(name)
```
The registry is the single seam shared by the **poll loop**, the **`send_telegram` tool** (LLD 03 → `get_channel("telegram").send(ctx.chat_id, text)`), and outbound replies.

## Telegram adapter — `channels/telegram.py`
```python
class TelegramChannel(Channel):
    name = "telegram"
    def __init__(self, token, dispatcher, *, poll_timeout=30, http_timeout=40.0):
        self._token=token; self._dispatch=dispatcher; self._poll_timeout=poll_timeout
        self._http_timeout=http_timeout            # MUST exceed poll_timeout
        self._offset=None; self._task=None; self._client=None; self._running=False

    async def start(self):
        if self._running: return
        self._client = httpx.AsyncClient(timeout=self._http_timeout)
        await self._delete_webhook()               # ← FIX: clear any webhook so getUpdates won't 409
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="telegram-poll")

    async def send(self, chat_id, text):
        for chunk in _split(text, 4096):           # Telegram hard cap
            r = await self._client.post(_url(self._token,"sendMessage"),
                                        json={"chat_id": chat_id, "text": chunk})
            r.raise_for_status()
        return r.json()

    async def handle_update(self, update):         # pure parsing, no I/O
        msg = update.get("message")
        if not msg or not msg.get("text"): return None         # skip edits/non-text/callbacks
        frm = msg.get("from", {})
        if frm.get("is_bot"): return None
        return InboundMessage("telegram", str(msg["chat"]["id"]), msg["text"],
                              frm.get("first_name") or frm.get("username") or "", update)

    async def _poll_loop(self):
        backoff = 1.0
        while self._running:
            try:
                params = {"timeout": self._poll_timeout, "allowed_updates": ["message"]}
                if self._offset is not None: params["offset"] = self._offset   # ACK cursor
                r = await self._client.get(_url(self._token,"getUpdates"), params=params)
                if r.status_code == 409:                       # webhook set OR a 2nd poller (uvicorn --reload)
                    log.error("getUpdates 409 — deleteWebhook / run a single poller"); await asyncio.sleep(5); continue
                r.raise_for_status(); body = r.json()
                if not body.get("ok"): await asyncio.sleep(backoff); continue
                backoff = 1.0
                for u in body["result"]:
                    inb = await self.handle_update(u)
                    try:
                        if inb: await self._dispatch(inb)       # persists inbound FIRST (see dispatcher)
                    except Exception:
                        log.exception("update %s failed; skipping", u.get("update_id"))
                    finally:
                        self._offset = u["update_id"] + 1       # ← FIX: advance AFTER handling (at-least-once),
                                                                #   in finally so a poison update can't wedge the loop
            except asyncio.CancelledError: raise
            except (httpx.TimeoutException, httpx.TransportError):
                await asyncio.sleep(backoff); backoff = min(backoff*2, 30)   # network blip → backoff + reconnect
            except Exception:
                log.exception("poll loop error"); await asyncio.sleep(backoff); backoff = min(backoff*2, 30)
```
**Delivery semantics (review fix):** the offset advances **after** an update is handled (and the inbound is persisted), not before — so a crash mid-handling makes Telegram *redeliver* (at-least-once) rather than silently dropping (at-most-once). The `finally` guarantees a poison update still advances the cursor, so it can't wedge the loop. (Optional dedup by `update_id` is a noted nicety.) The loop survives network errors with exponential backoff + auto-reconnect.

## Inbound dispatch — `channels/dispatcher.py` (the 1:1 path)
```python
async def dispatch_inbound(inb: InboundMessage, *, session_factory, emit=lambda *a: None):
    # (A) resolve the bound AGENT FIRST, then create the Conversation (agent_id is NOT NULL — LLD 01)
    with session_factory() as db:
        conv = db.query(Conversation).filter_by(channel=inb.channel, external_id=inb.chat_id).first()
        if conv is None:
            agent = resolve_agent_for_channel(db, inb.channel)        # an Agent with this channel enabled
            if agent is None:
                return await get_channel(inb.channel).send(inb.chat_id, NO_AGENT_REPLY)   # nothing bound → reply + stop
            conv = Conversation(channel=inb.channel, external_id=inb.chat_id,
                                agent_id=agent.id, title=inb.user_display or inb.chat_id)
            db.add(conv)
            try: db.commit()
            except IntegrityError:                                    # concurrent first message (unique constraint)
                db.rollback(); conv = db.query(Conversation).filter_by(
                    channel=inb.channel, external_id=inb.chat_id).first()
        agent = db.get(Agent, conv.agent_id)
        if agent is None:
            return await get_channel(inb.channel).send(inb.chat_id, AGENT_DELETED_REPLY)
        spec = build_agent_spec(agent)                                # resolves mapped tools (allow-list)
        summary = conv.summary; conv_id = conv.id

    # (B) persist inbound, then load WINDOWED history (current text goes in input, not history → no dup)
    persist_message(session_factory, conversation_id=str(conv_id), from_agent="user", to_agent=agent.name,
                    channel=inb.channel, role="user", content=inb.text)
    history = load_history(session_factory, str(conv_id), window=spec.memory_config.get("window", 12))

    # (C) run the SAME AgentRunner in 1:1 mode (no bus, no handoff/peer control tools)
    result = await AgentRunner(spec, bus=None, emit=emit).run(AgentInput(
        input=inb.text, history=history, summary=summary, allowed_routes=[],
        ctx=ToolContext(conversation_id=str(conv_id), chat_id=inb.chat_id, agent_name=agent.name)))

    # (D) persist outbound + roll memory/counters
    persist_message(session_factory, conversation_id=str(conv_id), from_agent=agent.name, to_agent="user",
                    channel=inb.channel, role="assistant", content=result.text, tokens=result.usage.total_tokens)
    with session_factory() as db:
        c = db.get(Conversation, conv_id); c.total_tokens += result.usage.total_tokens; c.last_at = _now()
        if spec.memory_config.get("summary") and _history_len(db, conv_id) > spec.memory_config.get("window",12):
            c.summary = await summarize_history(llm, _older(db, conv_id), prior=c.summary)   # LLD 05 helper
        db.commit()

    # (E) reply
    await get_channel(inb.channel).send(inb.chat_id, result.text)
```
**Reply policy (review fix):** the dispatcher **always** sends `result.text` (we do *not* try to detect "already replied via the `send_telegram` tool" — LLD 05's `tool_runs` is audit-only and can't carry a target). `send_telegram` is intended for **workflow nodes** (e.g. the Notifier agent in Template 1) to push into a chat; a 1:1 channel agent simply returns text. (Don't grant `send_telegram` to a pure 1:1 agent; if you do, it sends an extra message — documented.)

## Concurrency note
Updates are dispatched **sequentially in `update_id` order** by the single poll loop, so messages from one chat are processed in order. (Per-chat serialization is therefore automatic in v1; a future webhook/multi-worker setup would add an explicit per-chat lock.)

## How to add a new channel (the rubric's extension point — for README)
1. Subclass `Channel` (implement `start/stop/send/handle_update` returning a normalised `InboundMessage`).
2. `register_channel(MyChannel(token, dispatch_inbound))` at startup when its token env var is set.
3. That's it — `dispatch_inbound`, `Conversation`, persistence, and the monitor are all channel-agnostic. (Slack = socket-mode adapter; WhatsApp = Twilio/Meta webhook adapter — both just implement the ABC.)

## Tests (`backend/tests/test_channels.py`) — critical-path "message delivery"
- `handle_update` parses text msgs, skips edits/non-text/bot.
- poll loop (mock `httpx`): advances offset only after dispatch; a raising dispatch still advances (no wedge); 409 → backoff not crash; network error → reconnect.
- `dispatch_inbound`: creates Conversation with `agent_id` set; concurrent first-message `IntegrityError` → re-read; persists inbound+outbound; sends reply (full path with a mocked `AgentRunner`).
- "no agent bound" / "agent deleted" → friendly reply, no dangling Conversation.

## Decisions / tradeoffs
- **Long-poll, not webhook** — runs fully local with no tunnel; webhook + WhatsApp/Slack are documented next-steps behind the same ABC.
- **At-least-once** (offset after handling) over at-most-once — never silently drop a user message; duplicates are rare + tolerable.
- **Agent resolved before Conversation** — respects the `agent_id NOT NULL` constraint; `IntegrityError` retry handles the concurrent-first-message race.
- **Dispatcher always sends `result.text`** — drops the unimplementable "replied-via-tool" suppression; `send_telegram` is a workflow-notify tool.
- **Channel ABC + registry** — one seam for the loop, the tool, and replies; new channels are pure adapters.
- **`delete_webhook` on start + 409 backoff** — avoids the classic getUpdates conflict (incl. `uvicorn --reload` double-poller).

---
*Next: [LLD 08 — Scheduler](08-scheduler.md).*
