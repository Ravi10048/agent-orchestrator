"""Provider abstraction (LLD 02). A native-only provider (e.g. Anthropic Messages API)
would subclass this; for now one OpenAI-compatible impl covers Groq/Gemini/Ollama."""
from abc import ABC, abstractmethod

from app.llm.types import LLMRequest, LLMResult


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, req: LLMRequest) -> LLMResult: ...
    # Optional (deferred): async def stream(self, req) -> AsyncIterator[str]
