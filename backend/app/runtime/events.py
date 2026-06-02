"""EventSink — the observability spine (LLD 06). One per run. `emit(type, payload)` is
synchronous: stamp a per-run monotonic `seq` → persist a RunEvent (best-effort, never
breaks the run) → aggregate token/cost (from TOKEN_USAGE) → fan-out a copy to the
WebSocket MonitorHub (non-blocking). The hub is duck-typed (`publish(envelope: dict)`)
and optional — None in tests / when no monitor is attached (it's wired in LLD 09)."""
import logging
from datetime import UTC, datetime

from app.models.enums import EventType
from app.models.event import RunEvent

log = logging.getLogger("runtime.events")


class EventSink:
    def __init__(self, run_id: int, session_factory, hub=None):
        self.run_id = run_id
        self.session_factory = session_factory
        self.hub = hub
        self.seq = 0
        self.total_tokens = 0
        self.est_cost = 0.0

    def emit(self, etype, payload: dict | None = None, *, node_id: str | None = None) -> dict:
        self.seq += 1
        etype = str(etype)
        payload = dict(payload or {})
        if node_id and "node_id" not in payload:
            payload["node_id"] = node_id

        if etype == EventType.TOKEN_USAGE:  # the single source for run totals
            self.total_tokens += payload.get("total_tokens", 0) or 0
            self.est_cost += payload.get("est_cost_usd", 0.0) or 0.0
            payload["run_total_tokens"] = self.total_tokens
            payload["run_est_cost"] = round(self.est_cost, 6)

        event_id = self._persist(etype, payload)
        envelope = {
            "run_id": self.run_id, "seq": self.seq, "type": etype,
            "ts": datetime.now(UTC).isoformat(), "event_id": event_id, "payload": payload,
        }
        self._fanout(envelope)
        return envelope

    def _persist(self, etype: str, payload: dict) -> int | None:
        try:
            with self.session_factory() as db:
                ev = RunEvent(run_id=self.run_id, seq=self.seq, type=etype, payload=payload)
                db.add(ev)
                db.commit()
                db.refresh(ev)
                return ev.id
        except Exception:
            log.warning("event persist failed (run=%s type=%s) — swallowed", self.run_id, etype)
            return None  # monitoring must never break a run

    def _fanout(self, envelope: dict) -> None:
        if not self.hub:
            return
        try:
            self.hub.publish(envelope)  # non-blocking (LLD 09 MonitorHub)
        except Exception:
            log.debug("event fan-out failed (run=%s) — swallowed", self.run_id)
