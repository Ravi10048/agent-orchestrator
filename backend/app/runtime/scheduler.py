"""Scheduler (LLD 08) — turns each enabled Agent.schedule (cron/interval) into recurring
runs via APScheduler. The DB is the source of truth: jobs are reloaded on startup and
upserted/removed on agent CRUD. Everything runs in-process on the app's event loop.

Downtime semantics: coalesce + misfire_grace_time collapse IN-PROCESS misfires (a blocked
loop or an overrun job) into a single catch-up. Runs missed while the PROCESS was down are
NOT replayed on restart — MemoryJobStore is non-persistent, so each job simply reschedules
its next future fire (degraded-safe: skipped, never duplicated). Cross-restart catch-up =
a persistent jobstore (APScheduler SQLAlchemyJobStore) — a documented production next-step.
"""
import logging
from zoneinfo import ZoneInfo

from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.models import Agent
from app.models.enums import TriggerType

log = logging.getLogger("scheduler")


def JOB_ID(agent_id: int) -> str:  # stable, idempotent id per agent
    return f"agent:{agent_id}"


class ScheduleConfigError(ValueError):
    """Invalid schedule config → API maps to 400."""


_INTERVAL_KEYS = {"weeks": 604800, "days": 86400, "hours": 3600, "minutes": 60, "seconds": 1}


def _validate_cron(cfg: dict) -> None:
    if not cfg.get("cron"):
        raise ScheduleConfigError("cron expression required")
    try:
        CronTrigger.from_crontab(cfg["cron"])  # APScheduler validates the fields
    except Exception as e:
        raise ScheduleConfigError(f"bad cron: {e}") from e


def _validate_interval(iv: dict) -> None:
    bad = set(iv) - set(_INTERVAL_KEYS)  # reject typo/unknown keys so _build_trigger can't TypeError later
    if bad:
        raise ScheduleConfigError(f"unknown interval keys {sorted(bad)} (allowed: {sorted(_INTERVAL_KEYS)})")
    for k, v in iv.items():  # values must be numbers (free-form JSON could send strings)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ScheduleConfigError(f"interval.{k} must be a number")
    total = sum(_INTERVAL_KEYS[k] * iv.get(k, 0) for k in _INTERVAL_KEYS)
    if total < 10:
        raise ScheduleConfigError("interval must be >= 10s (runaway guard)")


def validate_schedule(cfg: dict) -> dict:
    """Validate + normalise a schedule config. Raises ScheduleConfigError (→400) on bad
    input. A disabled/empty config is valid (returned as-is)."""
    if not cfg or not cfg.get("enabled"):
        return cfg or {}
    kind = cfg.get("kind") or ("cron" if "cron" in cfg else "interval")
    if kind == "cron":
        _validate_cron(cfg)
    elif kind == "interval":
        _validate_interval(cfg.get("interval") or {})
    else:
        raise ScheduleConfigError(f"unknown kind '{kind}'")
    tz = cfg.get("timezone") or settings.SCHEDULER_TIMEZONE
    try:
        ZoneInfo(tz)
    except Exception as e:
        raise ScheduleConfigError("bad timezone") from e
    if cfg.get("target", "agent") == "workflow" and not cfg.get("workflow_id"):
        raise ScheduleConfigError("target=workflow requires workflow_id")
    return {
        **cfg, "kind": kind, "timezone": tz, "target": cfg.get("target", "agent"),
        "coalesce": cfg.get("coalesce", True), "max_instances": cfg.get("max_instances", 1),
        "misfire_grace_time": cfg.get("misfire_grace_time", settings.SCHEDULER_MISFIRE_GRACE),
    }


async def fire_agent_schedule(run_service, session_factory, agent_id) -> int | None:
    """Resolve the agent's schedule target and start a Run (trigger=SCHEDULE). Module-level
    (no closure state). Returns run_id or None. Re-reads the agent so a since-deleted/disabled
    agent is skipped. start_run/start_agent_run spawn the run as a background task, so this
    callback returns quickly and never blocks the scheduler loop."""
    with session_factory() as db:
        a = db.get(Agent, agent_id)
        if not a or not (a.schedule or {}).get("enabled"):
            return None  # deleted/disabled since the job was loaded → skip
        cfg = a.schedule
    if cfg.get("target") == "workflow":
        return await run_service.start_run(
            cfg["workflow_id"], run_input={"text": cfg.get("prompt", "(scheduled)")},
            trigger=TriggerType.SCHEDULE)
    return await run_service.start_agent_run(
        agent_id, run_input={"text": cfg.get("prompt", "(scheduled run)")},
        trigger=TriggerType.SCHEDULE)


class SchedulerService:
    def __init__(self, run_service, session_factory, *, default_tz="UTC", default_grace=3600):
        self.run_service = run_service
        self.session_factory = session_factory
        self.default_tz = default_tz
        self.default_grace = default_grace
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},  # DB is source of truth; reloaded on startup
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": default_grace},
            timezone=default_tz,
        )

    def start(self) -> None:
        self.scheduler.start()  # on the running loop (FastAPI lifespan)

    async def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    def load_all_schedules(self) -> int:
        """Startup: rebuild jobs from Agent rows. Never crashes on a bad config."""
        with self.session_factory() as db:
            agents = db.query(Agent).filter(Agent.schedule.isnot(None)).all()
        n = 0
        for a in agents:
            try:
                if self.upsert_agent_schedule(a):
                    n += 1
            except ScheduleConfigError as e:
                log.warning("skip bad schedule agent=%s: %s", a.id, e)
            except Exception:  # never let one malformed row crash startup
                log.exception("skip schedule agent=%s (unexpected build error)", a.id)
        return n

    def upsert_agent_schedule(self, agent) -> bool:
        """Called by the agents router on create/update. validate raises (→400) BEFORE
        the job is added; disabled/none ensures the job is removed (idempotent)."""
        jid = JOB_ID(agent.id)
        cfg = agent.schedule or {}
        if not cfg.get("enabled"):
            self._safe_remove(jid)
            return False
        cfg = validate_schedule(cfg)
        self.scheduler.add_job(
            func=fire_agent_schedule, trigger=self._build_trigger(cfg), id=jid,
            name=f"{agent.name} schedule",
            args=[self.run_service, self.session_factory, agent.id],
            coalesce=cfg["coalesce"], max_instances=cfg["max_instances"],
            misfire_grace_time=cfg["misfire_grace_time"],
            replace_existing=True,  # same id REPLACES atomically (no TOCTOU)
        )
        return True

    def remove_agent_schedule(self, agent_id) -> None:
        self._safe_remove(JOB_ID(agent_id))

    def _safe_remove(self, jid: str) -> None:
        try:
            self.scheduler.remove_job(jid)
        except JobLookupError:
            pass  # idempotent; no get-then-remove race

    @staticmethod
    def validate_schedule(cfg: dict) -> dict:
        return validate_schedule(cfg)

    def _build_trigger(self, cfg: dict):
        if cfg["kind"] == "cron":
            return CronTrigger.from_crontab(cfg["cron"], timezone=cfg["timezone"])
        return IntervalTrigger(**cfg["interval"], timezone=cfg["timezone"])
