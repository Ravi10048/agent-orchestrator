"""Channel abstraction + registry (LLD 07). One seam shared by the poll loop, the
`send_telegram` tool, and outbound replies. Adding a channel = subclass + register."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ChannelNotConfigured(Exception):
    def __init__(self, name: str):
        super().__init__(f"channel '{name}' not configured")


@dataclass
class InboundMessage:
    """Normalised, channel-agnostic inbound → the dispatcher is reusable across channels."""
    channel: str
    chat_id: str
    text: str
    user_display: str = ""
    raw: dict = field(default_factory=dict)


class Channel(ABC):
    name: str  # registry key, e.g. "telegram"

    @abstractmethod
    async def start(self) -> None: ...  # spawn the long-poll task (idempotent, non-blocking)

    @abstractmethod
    async def stop(self) -> None: ...  # cancel loop, close client (idempotent)

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> dict: ...  # used by dispatcher AND send_telegram

    @abstractmethod
    async def handle_update(self, update: dict) -> "InboundMessage | None": ...  # pure parse; None = skip


_REGISTRY: dict[str, Channel] = {}


def register_channel(ch: Channel) -> None:
    _REGISTRY[ch.name] = ch


def get_channel(name: str) -> Channel:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ChannelNotConfigured(name) from None


def list_channels() -> list[Channel]:
    return list(_REGISTRY.values())


def clear_channels() -> None:
    _REGISTRY.clear()
