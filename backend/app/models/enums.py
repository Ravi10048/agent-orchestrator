"""String enums shared across the app. `StrEnum` (3.11+) so members ARE their string
value — serialize cleanly to JSON/DB and `str(x)` yields the value, not `Class.MEMBER`."""
from enum import StrEnum


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    CHANNEL = "channel"


class ToolType(StrEnum):
    BUILTIN = "builtin"
    HTTP = "http"


class ChannelType(StrEnum):
    INTERNAL = "internal"
    TELEGRAM = "telegram"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    NODE_STARTED = "node_started"
    NODE_FINISHED = "node_finished"
    AGENT_MESSAGE = "agent_message"
    TOOL_CALL = "tool_call"
    TOKEN_USAGE = "token_usage"
    ERROR = "error"
    RUN_FINISHED = "run_finished"
