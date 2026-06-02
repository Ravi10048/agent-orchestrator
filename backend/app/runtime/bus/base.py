"""Async agent-to-agent transport interface (LLD 04). In-process impl in in_process.py;
Redis/Kafka would be a drop-in behind this same ABC for production."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BusMessage:
    id: str
    from_agent: str
    to_agent: str  # peer agent name, or "*" = broadcast to all other agents
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
    def drain(self, agent: str) -> list[BusMessage]:  # non-blocking: all pending right now
        ...

    @abstractmethod
    def has_pending(self, agent: str) -> bool: ...
