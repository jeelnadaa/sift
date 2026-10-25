"""OpenAI-compatible and Ollama LLM provider.

Supports:
- Local Ollama (default http://localhost:11434/v1)
- OpenAI, Groq, OpenRouter, DeepSeek, or any other OpenAI-compatible REST server.
"""

import json
from typing import Any

import httpx

from app.llm.base import LlmAuthError, LlmError, LlmQuotaError, LlmResult


class OpenAiCompatibleProvider:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama3.2",
        base_url: str | None = None,
        provider_name: str = "openai_compatible",
        client: httpx.Client | None = None,
    ):
        self.name = provider_name
        self.model = model
        self._key = api_key or ""
        self._base_url = (base_url or ("http://localhost:11434/v1" if provider_name == "ollama" else "https://api.openai.com/v1")).rstrip("/")
        self._client = client or httpx.Client(timeout=45)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._key and self._key.strip():
            headers["Authorization"] = f"Bearer {self._key.strip()}"
        return headers

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            r = self._client.post(url, json=body, headers=self._headers())
        except httpx.ConnectError as exc:
            raise LlmError(f"Could not connect to {self.name} at {self._base_url}: connection refused") from exc
        except httpx.TimeoutException as exc:
            raise LlmError(f"Timeout connecting to {self.name} at {self._base_url}") from exc

        if r.status_code == 200:
            return r.json()

        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}

        message = err.get("message", r.text if r.text else f"HTTP {r.status_code}")
        if r.status_code in (401, 403) or "unauthorized" in message.lower() or "invalid api key" in message.lower():
            raise LlmAuthError(message)
        if r.status_code == 429:
            raise LlmQuotaError(message or "Rate limit or quota exceeded")
        if r.status_code == 404:
            raise LlmError(f"Model or endpoint not found ({self.model}) at {self._base_url}")

        raise LlmError(f"HTTP {r.status_code}: {message[:200]}")

    def generate_json(self, system: str, prompt: str, schema: dict, max_output_tokens: int = 600) -> LlmResult:
        system_instruction = (
            f"{system}\n\n"
            f"You MUST respond ONLY with a strictly valid JSON object matching this schema:\n"
            f"{json.dumps(schema, separators=(',', ':'))}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_output_tokens,
        }

        data = self._post("chat/completions", payload)
        choices = data.get("choices", [])
        if not choices:
            raise LlmError(f"Empty choices response from {self.name}")

        text = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        return LlmResult(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", len(prompt) // 4 + 1)),
            output_tokens=int(usage.get("completion_tokens", len(text) // 4 + 1)),
        )

    def embed(self, texts: list[str], task: str, model: str, dims: int) -> list[list[float]]:
        payload = {
            "model": model,
            "input": texts,
        }
        data = self._post("embeddings", payload)
        embeddings = [d.get("embedding", []) for d in data.get("data", [])]
        if len(embeddings) != len(texts):
            raise LlmError(f"Embedding count mismatch: expected {len(texts)}, got {len(embeddings)}")
        return embeddings

    def ping(self) -> None:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": 5,
        }
        self._post("chat/completions", payload)
