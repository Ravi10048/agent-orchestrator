# LLD 04 — Message Bus

> The async agent-to-agent transport. Standalone (no DB deps). Used by the Graph Executor ([LLD 06](06-executor.md)) and Agents ([LLD 05](05-agent.md)). Status: **for review**.

## Responsibility
Carry **messages between agents asynchronously** during a workflow run. Each agent has an **inbox**; an agent (or the executor) **publishes** a message addressed to a peer; the bus **delivers** it to that peer's inbox. This is the concrete mechanism behind two explicit requirements — *"Agents must communicate asynchronously"* and the *"agent-to-agent message reliability"* impact metric. Implementation is **in-process asyncio** behind a `MessageBus` interface, so Redis/Kafka is a drop-in for production.

> Scope: the bus is for **inter-agent** traffic *inside a run*. Human↔agent channel traffic (Telegram) goes through the Channel layer (LLD 07), not here.

## Files
```
backend/app/runtime/bus/
  __init__.py      # BusMessage, MessageBus, new_bus()
  base.py          # MessageBus (ABC) + BusMessage
  in_process.py    # InProcessBus (asyncio.Queue per agent)
```

## Interface — `bus/base.py`
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class BusMessage:
    id: str
    from_agent: str
    to_agent: str                 # peer agent name, or "*" = broadcast to all other agents
    content: str
    run_id: int | None = None
    meta: dict = field(default_factory=dict)
    ts: float = 0.0

class MessageBus(ABC):
    @abstractmethod
    async def publish(self, msg: BusMessage) -> None: ...
    @abstractmethod
    async def receive(self, agent: str, timeout: float | None = None) -> BusMessage | None: ...
    @abstractmethod
    def drain(self, agent: str) -> list[BusMessage]: ...    # non-blocking: all pending right now
    @abstractmethod
    def has_pending(self, agent: str) -> bool: ...
```

## In-process implementation — `bus/in_process.py`
```python
import asyncio
from app.runtime.bus.base import MessageBus, BusMessage

class InProcessBus(MessageBus):
    """One asyncio.Queue per agent. One instance per run (created by the executor)."""
    def __init__(self):
        self._inboxes: dict[str, asyncio.Queue[BusMessage]] = {}

    def _q(self, agent: str) -> asyncio.Queue:
        return self._inboxes.setdefault(agent, asyncio.Queue())

    async def publish(self, msg: BusMessage) -> None:
        targets = ([a for a in self._inboxes if a != msg.from_agent]
                   if msg.to_agent == "*" else [msg.to_agent])
        for a in targets:
            await self._q(a).put(msg)

    async def receive(self, agent: str, timeout: float | None = None) -> BusMessage | None:
        q = self._q(agent)
        try:
            return await (asyncio.wait_for(q.get(), timeout) if timeout else q.get())
        except asyncio.TimeoutError:
            return None

    def drain(self, agent: str) -> list[BusMessage]:
        q, out = self._q(agent), []
        while not q.empty():
            try: out.append(q.get_nowait())
            except asyncio.QueueEmpty: break
        return out

    def has_pending(self, agent: str) -> bool:
        return not self._q(agent).empty()

def new_bus() -> MessageBus:        # factory → swap impl via config later
    return InProcessBus()
```

## How it's used (with the Executor, LLD 06)
The executor creates **one bus per run** and is the place that ties bus delivery to persistence + monitoring:
```python
# when agent A's output should reach peer B (per a graph edge, or A explicitly addresses B):
msg = BusMessage(id=uuid(), from_agent="A", to_agent="B", content=output, run_id=run.id)
await bus.publish(msg)                       # async delivery to B's inbox
persist_message(run.id, from_agent="A", to_agent="B", channel="internal", content=output)  # audit (LLD 01)
emit(EventType.AGENT_MESSAGE, {...})         # → live monitor "inter-agent messages" (LLD 06)

# when B's node runs, it folds any waiting peer messages into its prompt:
incoming = bus.drain("B")                     # all messages addressed to B
```
- **Independent branches run concurrently** (each agent node is an asyncio task); a node can `await bus.receive("B", timeout)` to wait for a peer, or `drain` what's already there.
- Topology comes from the **graph edges**; the bus is the **transport** that makes the hops asynchronous + observable.

## Reliability (the impact metric)
Every published message is (a) queued for in-order delivery, (b) **persisted** as a `Message` row, and (c) **emitted** as an `AGENT_MESSAGE` event to the monitor — so delivery is auditable and visible live. In-process queues are reliable within the process; the documented prod swap (Redis/Kafka behind the same `MessageBus` ABC) adds cross-process + crash durability + DLQ.

## Tests (`backend/tests/test_bus.py`)
- `publish` → `receive` round-trip (direct address).
- broadcast (`to_agent="*"`) reaches all *other* agents, not the sender.
- `drain` returns all pending and leaves the queue empty; `has_pending` accuracy.
- `receive(timeout=...)` returns `None` when no message arrives.
- ordering: messages delivered FIFO per inbox.

## Decisions / tradeoffs
- **In-process asyncio queues** — zero deps, real async, perfect for a single-command local prototype; the `MessageBus` ABC + `new_bus()` factory make Redis/Kafka a drop-in for prod (the "what I'd change for scale" answer).
- **One bus per run** — isolates runs cleanly (no cross-run leakage), inboxes keyed by agent name within the run.
- **Bus = transport, graph = topology** — keeps "who talks to whom" declarative (editable in the UI) while the bus stays a dumb, reliable pipe.
- **Persistence + events live in the executor, not the bus** — the bus stays a pure, unit-testable primitive; observability/audit is layered on where the run context exists.
- **Broadcast supported** (`"*"`) for fan-out patterns, but the templates use direct addressing for clarity.

---
*Next: [LLD 05 — Agent](05-agent.md). Reply "go" to continue, or flag changes.*
