"""Seed the 3 built-in Tool rows (idempotent, by unique name) so they appear in the
registry/UI with the right params_schema. Custom HTTP tools are added in the UI."""
from app.models.tool import Tool

SEED = [
    dict(
        name="web_fetch", type="builtin", builtin_key="web_fetch",
        description="Fetch the text of a web page.",
        params_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    ),
    dict(
        name="calculator", type="builtin", builtin_key="calculator",
        description="Evaluate a math expression.",
        params_schema={"type": "object", "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]},
    ),
    dict(
        name="send_telegram", type="builtin", builtin_key="send_telegram",
        description="Send a message to a Telegram chat (defaults to the current/run chat).",
        params_schema={"type": "object",
                       "properties": {"text": {"type": "string"},
                                      "chat_id": {"type": "string", "description": "target chat; optional"}},
                       "required": ["text"]},
    ),
]


def seed_tools(db, tenant_id=None) -> int:
    """Upsert the built-in tools FOR A TENANT (idempotent by (tenant_id, name)). Each tenant gets its
    own copy of the builtins. Returns the number of NEW rows created."""
    created = 0
    for spec in SEED:
        existing = db.query(Tool).filter_by(tenant_id=tenant_id, name=spec["name"]).first()
        if existing:
            for k, v in spec.items():
                setattr(existing, k, v)
        else:
            db.add(Tool(tenant_id=tenant_id, **spec))
            created += 1
    db.commit()
    return created
