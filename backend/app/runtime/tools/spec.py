"""Turn Tool rows into OpenAI function specs. `params_schema` is the single source of
truth — it's both the LLM-advertised `parameters` and the arg validator (LLD 03)."""


def to_openai_spec(tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.params_schema or {"type": "object", "properties": {}},
        },
    }


def build_tool_specs(agent) -> list[dict]:
    # ONLY the agent's mapped tools (allow-list / "skills")
    return [to_openai_spec(t) for t in agent.tools]
