"""/ws/monitor endpoint (LLD 09). One protocol: client sends {action:"subscribe",run_id}
→ we register interest (live events start queuing), then backfill the run's past RunEvents
(ordered by seq, ≤ WS_BACKFILL_LIMIT) into the same queue, then a single sender task drains
the queue to the socket. Client dedupes by (run_id, seq), so backfill/live overlap is safe.
All sends go through ONE queue → one writer → no interleave corruption."""
import asyncio
import contextlib
import logging
from datetime import UTC

from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.event import RunEvent
from app.ws.hub import Subscriber

log = logging.getLogger("ws.monitor")


def _ts_utc(dt) -> str | None:
    # RunEvent.ts is a naive UTC value (SQLite func.now()); stamp UTC so the client converts
    # it to local time consistently with the live (already tz-aware) event stream.
    return dt.replace(tzinfo=UTC).isoformat() if dt else None


def _to_envelope(r: RunEvent) -> dict:
    return {
        "run_id": r.run_id, "seq": r.seq, "type": r.type,
        "ts": _ts_utc(r.ts), "event_id": r.id, "payload": r.payload,
    }


def backfill_events(run_id: int, after_seq: int = 0, limit: int = 500) -> list[dict]:
    """Past events for a run as envelopes (seq-ordered). Reused by the REST events mirror."""
    with SessionLocal() as db:
        rows = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
            .order_by(RunEvent.seq.asc())
            .limit(limit)
            .all()
        )
    return [_to_envelope(r) for r in rows]


async def _sender(websocket: WebSocket, sub: Subscriber) -> None:
    try:
        while True:
            await websocket.send_json(await sub.queue.get())
    except asyncio.CancelledError:
        raise
    except Exception:
        # send failed (closed/half-open socket, or an unserialisable payload). Don't die silently
        # and wedge into a no-consumer state — close the socket so the receive loop unblocks + cleans up.
        log.warning("monitor sender stopped; closing socket")
        with contextlib.suppress(Exception):
            await websocket.close()


async def monitor_ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    hub = websocket.app.state.hub
    sub = Subscriber()
    hub.register(sub)
    sender = asyncio.create_task(_sender(websocket, sub))
    try:
        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")
            if action == "subscribe":
                rid = int(msg["run_id"])
                sub.runs.add(rid)  # register interest FIRST so live events buffer
                # offload the blocking backfill query so it doesn't stall the event loop
                for env in await asyncio.to_thread(backfill_events, rid, 0, settings.WS_BACKFILL_LIMIT):
                    try:
                        sub.queue.put_nowait(env)
                    except asyncio.QueueFull:
                        break
            elif action == "subscribe_all":
                sub.all = True
            elif action == "unsubscribe":
                sub.runs.discard(int(msg.get("run_id")))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.unregister(sub)
        sender.cancel()
