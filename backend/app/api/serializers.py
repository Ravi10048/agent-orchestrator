"""ORM → DTO helpers (LLD 09). Centralised so secret redaction is applied everywhere."""
from app.api.schemas.agent import AgentOut
from app.api.schemas.tool import ToolOut, redact_auth, redact_headers


def tool_out(tool) -> ToolOut:
    out = ToolOut.model_validate(tool)
    out.auth = redact_auth(tool.auth)  # never expose raw secrets…
    out.headers = redact_headers(tool.headers)  # …including any parked in headers
    return out


def agent_out(agent) -> AgentOut:
    out = AgentOut.model_validate(agent)
    out.tools = [tool_out(t) for t in agent.tools]
    return out
