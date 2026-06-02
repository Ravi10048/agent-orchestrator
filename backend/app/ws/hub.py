"""MonitorHub (LLD 09) — live fan-out spine for the run monitor. The EventSink (LLD 06)
calls `publish(envelope)` synchronously from the executor task; the hub pushes a copy to
each interested subscriber's queue (non-blocking — a slow consumer drops events, since the
DB-backed backfill + REST events mirror let it catch up). One hub per app (a singleton on
app.state), injected into every run's EventSink."""
import asyncio


class Subscriber:
    def __init__(self, maxsize: int = 2000):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.runs: set[int] = set()  # run_ids this connection subscribed to
        self.all: bool = False  # dashboard: receive every run's events


class MonitorHub:
    def __init__(self):
        self._subs: set[Subscriber] = set()

    def register(self, sub: Subscriber) -> None:
        self._subs.add(sub)

    def unregister(self, sub: Subscriber) -> None:
        self._subs.discard(sub)

    def publish(self, envelope: dict) -> None:
        rid = envelope.get("run_id")
        for sub in list(self._subs):
            if sub.all or rid in sub.runs:
                try:
                    sub.queue.put_nowait(envelope)
                except asyncio.QueueFull:
                    pass  # best-effort live tail; client reconnect/replay closes any gap

    async def close(self) -> None:
        self._subs.clear()
