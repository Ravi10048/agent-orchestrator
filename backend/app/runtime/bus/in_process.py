"""In-process asyncio implementation — one Queue per agent, one bus per run (created
by the executor). Zero deps, real async; reliable within the process (LLD 04)."""
import asyncio

from app.runtime.bus.base import BusMessage, MessageBus


class InProcessBus(MessageBus):
    """One asyncio.Queue per agent. One instance per run (created by the executor)."""

    def __init__(self):
        self._inboxes: dict[str, asyncio.Queue[BusMessage]] = {}

    def _q(self, agent: str) -> asyncio.Queue:
        return self._inboxes.setdefault(agent, asyncio.Queue())

    async def publish(self, msg: BusMessage) -> None:
        targets = (
            [a for a in self._inboxes if a != msg.from_agent]
            if msg.to_agent == "*"
            else [msg.to_agent]
        )
        for a in targets:
            await self._q(a).put(msg)

    async def receive(self, agent: str, timeout: float | None = None) -> BusMessage | None:
        q = self._q(agent)
        try:
            return await (asyncio.wait_for(q.get(), timeout) if timeout else q.get())
        except TimeoutError:
            return None

    def drain(self, agent: str) -> list[BusMessage]:
        q, out = self._q(agent), []
        while not q.empty():
            try:
                out.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out

    def has_pending(self, agent: str) -> bool:
        return not self._q(agent).empty()


def new_bus() -> MessageBus:  # factory → swap impl via config later
    return InProcessBus()
