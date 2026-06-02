"""LLD 08 — Scheduler tests (validation, upsert/remove idempotency, fire routing)."""
import pytest

from app.models import Agent, Workflow
from app.models.enums import TriggerType
from app.runtime.scheduler import (
    JOB_ID,
    ScheduleConfigError,
    SchedulerService,
    fire_agent_schedule,
    validate_schedule,
)


class _MockRunService:
    def __init__(self):
        self.calls = []

    async def start_run(self, workflow_id, run_input=None, trigger=None):
        self.calls.append(("workflow", workflow_id, trigger))
        return 101

    async def start_agent_run(self, agent_id, run_input=None, trigger=None):
        self.calls.append(("agent", agent_id, trigger))
        return 202


@pytest.fixture
async def sched(session_factory):
    # Started so add_job/remove_job hit the jobstore (replace_existing dedup is applied there).
    svc = SchedulerService(_MockRunService(), session_factory)
    svc.start()
    try:
        yield svc
    finally:
        svc.scheduler.shutdown(wait=False)


# ── validate_schedule ─────────────────────────────────────────────────
def test_validate_cron_ok():
    cfg = validate_schedule({"enabled": True, "kind": "cron", "cron": "*/30 * * * *"})
    assert cfg["kind"] == "cron" and cfg["coalesce"] is True and cfg["max_instances"] == 1


def test_validate_interval_ok():
    cfg = validate_schedule({"enabled": True, "kind": "interval", "interval": {"minutes": 5}})
    assert cfg["kind"] == "interval" and cfg["target"] == "agent"


def test_validate_disabled_passthrough():
    assert validate_schedule({"enabled": False}) == {"enabled": False}
    assert validate_schedule({}) == {}


def test_validate_bad_cron():
    with pytest.raises(ScheduleConfigError):
        validate_schedule({"enabled": True, "kind": "cron", "cron": "not a cron"})


def test_validate_missing_cron():
    with pytest.raises(ScheduleConfigError):
        validate_schedule({"enabled": True, "kind": "cron"})


def test_validate_sub_10s_interval():
    with pytest.raises(ScheduleConfigError):
        validate_schedule({"enabled": True, "kind": "interval", "interval": {"seconds": 5}})


def test_validate_workflow_requires_id():
    with pytest.raises(ScheduleConfigError):
        validate_schedule({"enabled": True, "kind": "interval", "interval": {"minutes": 5},
                           "target": "workflow"})


def test_validate_bad_timezone():
    with pytest.raises(ScheduleConfigError):
        validate_schedule({"enabled": True, "kind": "interval", "interval": {"minutes": 5},
                           "timezone": "Mars/Phobos"})


# review regressions: interval shape must funnel through ScheduleConfigError (→400), never TypeError
def test_validate_interval_unknown_key_rejected():
    with pytest.raises(ScheduleConfigError):
        validate_schedule({"enabled": True, "kind": "interval", "interval": {"minutes": 30, "foo": 1}})


def test_validate_interval_non_numeric_rejected():
    with pytest.raises(ScheduleConfigError):
        validate_schedule({"enabled": True, "kind": "interval", "interval": {"seconds": "30"}})


def test_validate_interval_weeks_ok():
    cfg = validate_schedule({"enabled": True, "kind": "interval", "interval": {"weeks": 1}})
    assert cfg["kind"] == "interval"  # weeks counts toward the runaway total → not wrongly rejected


# ── upsert / remove (idempotent) ──────────────────────────────────────
async def test_upsert_adds_and_replaces(sched, session_factory):
    with session_factory() as db:
        a = Agent(name="Sched", schedule={"enabled": True, "kind": "interval", "interval": {"minutes": 5}})
        db.add(a)
        db.commit()
        aid = a.id
    with session_factory() as db:
        assert sched.upsert_agent_schedule(db.get(Agent, aid)) is True
    assert sched.scheduler.get_job(JOB_ID(aid)) is not None
    with session_factory() as db:  # re-upsert replaces atomically → still exactly one job
        sched.upsert_agent_schedule(db.get(Agent, aid))
    assert len([j for j in sched.scheduler.get_jobs() if j.id == JOB_ID(aid)]) == 1


async def test_upsert_disabled_removes(sched, session_factory):
    with session_factory() as db:
        a = Agent(name="S", schedule={"enabled": True, "kind": "interval", "interval": {"minutes": 5}})
        db.add(a)
        db.commit()
        aid = a.id
    with session_factory() as db:
        sched.upsert_agent_schedule(db.get(Agent, aid))
    assert sched.scheduler.get_job(JOB_ID(aid)) is not None
    with session_factory() as db:
        a = db.get(Agent, aid)
        a.schedule = {"enabled": False}
        db.commit()
    with session_factory() as db:
        assert sched.upsert_agent_schedule(db.get(Agent, aid)) is False
    assert sched.scheduler.get_job(JOB_ID(aid)) is None


async def test_safe_remove_missing_no_error(sched):
    sched.remove_agent_schedule(99999)  # no JobLookupError surfaces


async def test_load_all_skips_invalid(sched, session_factory):
    with session_factory() as db:
        db.add_all([
            Agent(name="good", schedule={"enabled": True, "kind": "interval", "interval": {"minutes": 5}}),
            Agent(name="bad", schedule={"enabled": True, "kind": "cron", "cron": "garbage"}),
            Agent(name="off", schedule={"enabled": False}),
            Agent(name="none", schedule=None),
        ])
        db.commit()
    assert sched.load_all_schedules() == 1  # only 'good' scheduled; 'bad' skipped without crashing


# ── fire_agent_schedule (routing) ─────────────────────────────────────
async def test_fire_target_agent(session_factory):
    rs = _MockRunService()
    with session_factory() as db:
        a = Agent(name="A", schedule={"enabled": True, "kind": "interval", "interval": {"minutes": 5},
                                      "target": "agent", "prompt": "hi"})
        db.add(a)
        db.commit()
        aid = a.id
    assert await fire_agent_schedule(rs, session_factory, aid) == 202
    assert rs.calls == [("agent", aid, TriggerType.SCHEDULE)]


async def test_fire_target_workflow(session_factory):
    rs = _MockRunService()
    with session_factory() as db:
        wf = Workflow(name="w", graph={})
        db.add(wf)
        db.commit()
        wfid = wf.id
        a = Agent(name="A", schedule={"enabled": True, "kind": "interval", "interval": {"minutes": 5},
                                      "target": "workflow", "workflow_id": wfid})
        db.add(a)
        db.commit()
        aid = a.id
    assert await fire_agent_schedule(rs, session_factory, aid) == 101
    assert rs.calls == [("workflow", wfid, TriggerType.SCHEDULE)]


async def test_fire_disabled_agent_skips(session_factory):
    rs = _MockRunService()
    with session_factory() as db:
        a = Agent(name="A", schedule={"enabled": False})
        db.add(a)
        db.commit()
        aid = a.id
    assert await fire_agent_schedule(rs, session_factory, aid) is None
    assert rs.calls == []


async def test_fire_deleted_agent_skips(session_factory):
    rs = _MockRunService()
    assert await fire_agent_schedule(rs, session_factory, 99999) is None
    assert rs.calls == []
