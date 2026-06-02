# LLD 08 — Scheduler

> Turns an agent's `schedule` config into recurring runs. Depends on [LLD 01](01-data-model.md) (`Agent.schedule`), [LLD 06](06-executor.md) (`RunService`). Status: **for review** — *hardened by the design + adversarial-review pass.*

## Responsibility
Make **"schedules"** a real, configurable agent dimension: an `AsyncIOScheduler` turns each enabled `Agent.schedule` (cron or interval) into a trigger that starts a **Run** with `trigger=SCHEDULE`. The DB is the **source of truth** — jobs are (re)loaded on startup and upserted/removed on agent CRUD. Everything runs **in-process** on the app's event loop (zero infra).

## Files
```
backend/app/runtime/
  scheduler.py    # SchedulerService, validate_schedule, fire_agent_schedule
  run_service.py  # (LLD 06) gains start_agent_run() — the solo-workflow wrapper
```
Config (LLD 09): `SCHEDULER_TIMEZONE="UTC"`, `SCHEDULER_MISFIRE_GRACE=3600`.

## Schedule config — extends `Agent.schedule` (LLD 01 JSON)
```jsonc
{
  "enabled": true,                 // master on/off (disable without losing config)
  "kind": "cron" | "interval",
  "cron": "*/30 * * * *",          // 5-field cron      (kind == "cron")
  "interval": { "minutes": 30 },   // interval kwargs   (kind == "interval")
  "timezone": "UTC",               // IANA tz; default settings.SCHEDULER_TIMEZONE
  "target": "agent" | "workflow",  // what to run (default "agent")
  "workflow_id": 12,               // required iff target == "workflow"
  "prompt": "Daily standup digest",// the run input text (target == "agent")
  "coalesce": true,                // collapse missed runs → one (default true)
  "max_instances": 1,              // no overlapping runs of the same job (default 1)
  "misfire_grace_time": 3600       // seconds; default settings.SCHEDULER_MISFIRE_GRACE
}
```
> **What a scheduled run executes (review fix — no invented columns):** `RunService` only runs **workflows** (LLD 06). For `target="workflow"` it runs `workflow_id` directly. For `target="agent"` it calls `RunService.start_agent_run(agent_id, …)`, which **ensures a tiny solo workflow exists** (`start → agent → end`, `is_template=False`, system-owned, created once and reused) and runs that. So a "scheduled agent" is well-defined and reuses the exact same executor — no special-casing.

## SchedulerService — `runtime/scheduler.py`
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

JOB_ID = lambda agent_id: f"agent:{agent_id}"      # stable, idempotent id per agent
class ScheduleConfigError(ValueError): ...         # API → 400

class SchedulerService:
    def __init__(self, run_service, session_factory, *, default_tz="UTC", default_grace=3600):
        self.run_service = run_service; self.session_factory = session_factory
        self.default_tz = default_tz; self.default_grace = default_grace
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},     # DB is source of truth; reloaded on startup
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": default_grace},
            timezone=default_tz)

    def start(self):  self.scheduler.start()             # on the running loop (FastAPI lifespan)
    async def shutdown(self):  self.scheduler.shutdown(wait=False)

    def load_all_schedules(self) -> int:                 # startup: rebuild jobs from Agent rows
        n = 0
        with self.session_factory() as db:
            for a in db.query(Agent).filter(Agent.schedule.isnot(None)).all():
                try:
                    if self.upsert_agent_schedule(a): n += 1
                except ScheduleConfigError as e:
                    log.warning("skip bad schedule agent=%s: %s", a.id, e)   # never crash startup
        return n

    def upsert_agent_schedule(self, agent) -> bool:      # called by the agents router on create/update
        jid = JOB_ID(agent.id); cfg = agent.schedule or {}
        if not cfg.get("enabled"):                       # disabled / none → ensure removed (idempotent)
            self._safe_remove(jid); return False
        cfg = self.validate_schedule(cfg)                # raises ScheduleConfigError → router 400 BEFORE saving
        self.scheduler.add_job(
            func=fire_agent_schedule, trigger=self._build_trigger(cfg), id=jid,
            name=f"{agent.name} schedule",
            args=[self.run_service, self.session_factory, agent.id],
            coalesce=cfg["coalesce"], max_instances=cfg["max_instances"],
            misfire_grace_time=cfg["misfire_grace_time"],
            replace_existing=True)                       # same id REPLACES atomically (no TOCTOU)
        return True

    def remove_agent_schedule(self, agent_id):  self._safe_remove(JOB_ID(agent_id))
    def _safe_remove(self, jid):
        try: self.scheduler.remove_job(jid)
        except JobLookupError: pass                      # idempotent; no get-then-remove race

    @staticmethod
    def validate_schedule(cfg) -> dict: ...              # see below (raises → 400)
    def _build_trigger(self, cfg):
        if cfg["kind"] == "cron":     return CronTrigger.from_crontab(cfg["cron"], timezone=cfg["timezone"])
        return IntervalTrigger(**cfg["interval"], timezone=cfg["timezone"])
```

## validate_schedule (fail fast → API 400)
```python
def validate_schedule(cfg):
    if not cfg or not cfg.get("enabled"): return cfg or {}          # disabled is valid
    kind = cfg.get("kind") or ("cron" if "cron" in cfg else "interval")
    if kind == "cron":
        if not cfg.get("cron"): raise ScheduleConfigError("cron expression required")
        try: CronTrigger.from_crontab(cfg["cron"])                  # APScheduler validates fields
        except Exception as e: raise ScheduleConfigError(f"bad cron: {e}")
    elif kind == "interval":
        iv = cfg.get("interval") or {}
        total = iv.get("seconds",0)+60*iv.get("minutes",0)+3600*iv.get("hours",0)+86400*iv.get("days",0)
        if total < 10: raise ScheduleConfigError("interval must be >= 10s (runaway guard)")
    else: raise ScheduleConfigError(f"unknown kind '{kind}'")
    try: ZoneInfo(cfg.get("timezone") or settings.SCHEDULER_TIMEZONE)
    except Exception: raise ScheduleConfigError("bad timezone")
    if cfg.get("target","agent") == "workflow" and not cfg.get("workflow_id"):
        raise ScheduleConfigError("target=workflow requires workflow_id")
    return {**cfg, "kind": kind, "timezone": cfg.get("timezone") or settings.SCHEDULER_TIMEZONE,
            "target": cfg.get("target","agent"), "coalesce": cfg.get("coalesce", True),
            "max_instances": cfg.get("max_instances", 1),
            "misfire_grace_time": cfg.get("misfire_grace_time", settings.SCHEDULER_MISFIRE_GRACE)}
```

## The fire body (module-level → no closure state)
```python
async def fire_agent_schedule(run_service, session_factory, agent_id) -> int | None:
    """Resolve the agent's schedule target and start a Run (trigger=SCHEDULE). Returns run_id or None."""
    with session_factory() as db:
        a = db.get(Agent, agent_id)
        if not a or not (a.schedule or {}).get("enabled"): return None     # deleted/disabled since load → skip
        cfg = a.schedule
    if cfg.get("target") == "workflow":
        return await run_service.start_run(cfg["workflow_id"],
                   run_input={"text": cfg.get("prompt","(scheduled)")}, trigger=TriggerType.SCHEDULE)
    return await run_service.start_agent_run(agent_id,
               run_input={"text": cfg.get("prompt","(scheduled run)")}, trigger=TriggerType.SCHEDULE)
```
`start_run`/`start_agent_run` validate (fast) then spawn the actual run as a **background asyncio.Task** (LLD 06) — so the job callback returns quickly and never blocks the scheduler loop.

## RunService addition (LLD 06) — solo-workflow wrapper
```python
async def start_agent_run(self, agent_id, run_input, trigger=TriggerType.MANUAL) -> int:
    wf_id = self._ensure_solo_workflow(agent_id)     # create-once: graph start→agent(ref=agent_id)→end
    return await self.start_run(wf_id, run_input, trigger)
```

## Edge cases & semantics (review-hardened)
| Concern | Handling |
|---|---|
| **In-process misfires** (blocked loop / overrun job) | `coalesce=True` + `misfire_grace_time` → at most **one** catch-up run within grace, else skip (no thundering herd). |
| **Runs missed while the *process* was down** | **NOT replayed on restart** — `MemoryJobStore` is non-persistent, so on reload each job just schedules its next *future* fire (degraded-safe: skipped, never duplicated). Cross-restart catch-up = a persistent jobstore (`SQLAlchemyJobStore`), a documented **production next-step**. *(Corrected after the LLD08 review — the earlier "one catch-up after downtime" claim was inaccurate for MemoryJobStore.)* |
| **Overlapping runs** | `max_instances=1` → a new fire is skipped if the previous run's *trigger* is still in `fire_agent_schedule` (the run itself is a detached Task, so this just guards the trigger). |
| **Restart persistence** | `MemoryJobStore` + **`load_all_schedules()` on startup** (DB = source of truth). Simpler & more consistent than APScheduler's `SQLAlchemyJobStore` (which would double-store config). |
| **Timezone** | per-schedule IANA `timezone` (validated), default `settings.SCHEDULER_TIMEZONE`. |
| **CRUD safety** | commit the Agent row, **then** `upsert_agent_schedule` (validate raises → 400 before save in the router). `add_job(replace_existing=True)` is atomic; `_safe_remove` swallows `JobLookupError` (no TOCTOU). |
| **Runaway interval** | `validate_schedule` rejects intervals `< 10s`. |
| **Agent deleted/disabled after load** | `fire_agent_schedule` re-reads the agent and **skips** if gone/disabled. |
| **Don't block the loop** | the fire callback only validates + spawns; the run executes as a background Task. |

## Tests (`backend/tests/test_scheduler.py`)
- `validate_schedule`: valid cron/interval pass; bad cron, sub-10s interval, missing `workflow_id`, bad tz → `ScheduleConfigError`.
- `upsert_agent_schedule`: enabled → job added with `JOB_ID`; disabled → removed; re-upsert replaces (count stays 1).
- `_safe_remove` on missing job → no error.
- `fire_agent_schedule` (mock RunService): `target=agent` → `start_agent_run`; `target=workflow` → `start_run(workflow_id)`; disabled/deleted agent → returns `None`, no run.
- `load_all_schedules` skips invalid configs without crashing.

## Decisions / tradeoffs
- **APScheduler `AsyncIOScheduler` in-process** — zero infra, runs on the app loop; a distributed scheduler (Celery-beat/Temporal) is the documented prod next-step.
- **DB is the source of truth + MemoryJobStore + reload-on-startup** — one place to edit schedules (the agent), no job/config drift; survives restarts via reload.
- **Solo-workflow wrapper for scheduled agents** — keeps `RunService` workflow-only (no invented agent-run path); a scheduled agent is just a 1-node workflow → same executor, events, persistence.
- **`coalesce + misfire_grace + max_instances=1`** — sane recovery from downtime and no overlap, the two classic scheduler footguns.
- **Validate → 400 before persisting the job** — a bad schedule never gets scheduled.

---
*Next: [LLD 09 — Backend API & WebSocket](09-api.md). Reply "go" to continue, or flag changes.*
