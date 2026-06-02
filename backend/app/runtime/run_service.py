"""RunService (LLD 06) — owns the run lifecycle outside the executor: validate → create
the Run row → launch the executor as a background asyncio.Task → return run_id
immediately. Holds the per-run stop Events for cooperative cancel. Also provides the
solo-workflow wrapper used by the scheduler (LLD 08)."""
import asyncio
import logging

from app.models import Agent, Run, Workflow
from app.models.enums import RunStatus, TriggerType
from app.runtime.executor import GraphExecutor

log = logging.getLogger("runtime.run_service")


class RunService:
    def __init__(self, session_factory, hub=None, *, max_run_steps: int = 50,
                 default_max_visits: int = 8, run_timeout_s: int = 300):
        self.session_factory = session_factory
        self.executor = GraphExecutor(session_factory, hub=hub, max_run_steps=max_run_steps,
                                      default_max_visits=default_max_visits, run_timeout_s=run_timeout_s)
        self._stops: dict[int, asyncio.Event] = {}
        self._tasks: dict[int, asyncio.Task] = {}

    async def start_run(self, workflow_id: int, run_input: dict | None = None,
                        trigger: TriggerType = TriggerType.MANUAL) -> int:
        with self.session_factory() as db:
            wf = db.get(Workflow, workflow_id)
            if wf is None:
                raise ValueError(f"workflow {workflow_id} not found")
            graph_json = wf.graph
            self.executor.validate_graph(graph_json, db)  # raise GraphValidationError → API 400, NO Run row
            run = Run(workflow_id=workflow_id, tenant_id=wf.tenant_id, status=str(RunStatus.RUNNING),
                      trigger=str(trigger), input=run_input or {})  # run inherits the workflow's tenant
            db.add(run)
            db.commit()
            db.refresh(run)
            run_id = run.id

        stop = asyncio.Event()
        self._stops[run_id] = stop
        self._tasks[run_id] = asyncio.create_task(self._run_and_cleanup(run_id, graph_json, stop))
        log.info("started run %s (workflow=%s, trigger=%s)", run_id, workflow_id, trigger)
        return run_id

    async def _run_and_cleanup(self, run_id: int, graph_json: dict, stop: asyncio.Event) -> None:
        try:
            await self.executor.execute(run_id, graph_json, stop)
        finally:
            self._stops.pop(run_id, None)
            self._tasks.pop(run_id, None)

    async def cancel_run(self, run_id: int) -> bool:
        stop = self._stops.get(run_id)
        if stop is None:
            return False  # not running (finished/unknown) → caller maps to 409
        stop.set()  # checked between nodes; the in-flight node finishes (own timeout)
        return True

    # ── scheduler support (LLD 08): a "scheduled agent" = a 1-node solo workflow ──
    def _ensure_solo_workflow(self, agent_id: int) -> int:
        name = f"__solo_agent_{agent_id}"
        with self.session_factory() as db:
            wf = db.query(Workflow).filter_by(name=name, is_template=False).first()
            if wf:
                return wf.id
            agent = db.get(Agent, agent_id)  # the solo workflow lives in the agent's tenant
            tenant_id = agent.tenant_id if agent else None
            graph = {
                "nodes": [
                    {"id": "start", "type": "start"},
                    {"id": "agent", "type": "agent", "ref": agent_id},
                    {"id": "end", "type": "end"},
                ],
                "edges": [
                    {"from": "start", "to": "agent"},
                    {"from": "agent", "to": "end"},
                ],
            }
            wf = Workflow(tenant_id=tenant_id, name=name, description="system-owned solo agent workflow",
                          graph=graph, is_template=False)
            db.add(wf)
            db.commit()
            db.refresh(wf)
            return wf.id

    async def start_agent_run(self, agent_id: int, run_input: dict | None = None,
                              trigger: TriggerType = TriggerType.MANUAL) -> int:
        wf_id = self._ensure_solo_workflow(agent_id)
        return await self.start_run(wf_id, run_input, trigger)

    async def shutdown(self) -> None:
        for t in list(self._tasks.values()):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
