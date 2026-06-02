"""Shared test fixtures. Expanded in LLD 11 (TestClient, mock-LLM, seeded_db).

`session_factory` — a sessionmaker bound to a shared in-memory SQLite (StaticPool), for
components that open their own short-lived sessions (the executor, LLD 06).
`db` — a single session from that factory, for direct ORM tests.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register models on Base.metadata
from app.core.db import Base


@pytest.fixture
def session_factory():
    # StaticPool → one shared connection so every session sees the same in-memory DB.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    SF = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    yield SF
    engine.dispose()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def llm(monkeypatch):
    """Mock the LLM gateway AgentRunner calls — deterministic, no network/keys.
    Set `llm['queue']` for a scripted sequence (popped in order), or `llm['default']`
    for a constant reply once the queue drains."""
    import app.runtime.agent as agent_mod
    from app.llm.types import LLMResult, Usage

    state = {"queue": [], "default": LLMResult(text="ok", usage=Usage(total_tokens=5))}

    async def fake(req, provider=None, fallback=None):
        return state["queue"].pop(0) if state["queue"] else state["default"]

    monkeypatch.setattr(agent_mod, "complete", fake)
    return state


@pytest.fixture
def client(session_factory):
    """TestClient wired to the in-memory DB. Lifespan is skipped (no startup poll/seed); the
    runtime services are set on app.state and get_db is overridden — enough for REST tests."""
    from fastapi.testclient import TestClient

    from app.core.deps import get_db
    from app.main import create_app
    from app.runtime.run_service import RunService
    from app.runtime.scheduler import SchedulerService
    from app.ws.hub import MonitorHub

    app = create_app()
    hub = MonitorHub()
    rs = RunService(session_factory, hub=hub)
    app.state.hub = hub
    app.state.run_service = rs
    app.state.scheduler = SchedulerService(rs, session_factory)

    def _db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    return TestClient(app)
