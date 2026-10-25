"""LLM provider interface. Providers only talk HTTP; gating, caps, caching and usage
accounting live in app.llm.service so every provider gets them."""
from dataclasses import dataclass
from typing import Protocol


class LlmError(Exception):
    pass


class LlmAuthError(LlmError):
    """Key invalid, revoked or not allowed. The key is marked invalid."""


class LlmQuotaError(LlmError):
    """429 / quota exhausted on the user's own provider account."""


class LlmPaced(LlmQuotaError):
    """Sift itself held the call back to stay under the user's request limits (per minute, per
    day). The key is fine; nothing was sent."""


@dataclass
class LlmResult:
    text: str
    input_tokens: int
    output_tokens: int


class LlmProvider(Protocol):
    name: str

    def generate_json(self, system: str, prompt: str, schema: dict, max_output_tokens: int = 600) -> LlmResult: ...
    def embed(self, texts: list[str], task: str, model: str, dims: int) -> list[list[float]]: ...
    def ping(self) -> None: ...  # minimal call to validate the key; raises LlmAuthError / LlmQuotaError
