"""Workflow DTOs (LLD 09)."""
from datetime import datetime

from pydantic import Field

from app.api.schemas.common import OutModel, StrictModel


class NodeDTO(StrictModel):
    id: str = Field(min_length=1)
    type: str  # start | agent | tool | router | end
    ref: int | None = None
    config: dict = Field(default_factory=dict)


class EdgeDTO(StrictModel):
    # JSON uses "from"/"to"; map to from_/to_ via aliases
    from_: str = Field(alias="from")
    to: str
    condition: str | None = None
    model_config = {"populate_by_name": True, "extra": "forbid"}


class GraphDTO(StrictModel):
    nodes: list[NodeDTO] = Field(default_factory=list)
    edges: list[EdgeDTO] = Field(default_factory=list)

    def to_graph(self) -> dict:
        return {
            "nodes": [n.model_dump() for n in self.nodes],
            "edges": [{"from": e.from_, "to": e.to, "condition": e.condition} for e in self.edges],
        }


class WorkflowCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    graph: GraphDTO
    is_template: bool = False


class WorkflowUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    graph: GraphDTO | None = None


class WorkflowOut(OutModel):
    id: int
    name: str
    description: str
    graph: dict
    is_template: bool
    created_at: datetime
    updated_at: datetime


class WorkflowValidateBody(StrictModel):
    graph: GraphDTO


class ValidateResult(OutModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class InstantiateBody(StrictModel):
    name: str | None = None
