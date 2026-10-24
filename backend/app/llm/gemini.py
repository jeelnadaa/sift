"""Gemini via the REST generateContent endpoint (ai.google.dev/api/generate-content).

- Auth: x-goog-api-key header (never a URL parameter, so keys don't end up in logs).
- JSON output: generationConfig.responseMimeType=application/json + responseSchema.
- Thinking: we ask for the minimal level; a model that rejects thinkingConfig is retried
  without it and remembered for the process lifetime.
"""
import httpx

from app.llm.base import LlmAuthError, LlmError, LlmQuotaError, LlmResult

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_no_thinking_config: set[str] = set()


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None):
        self.model = model
        self._key = api_key
        self._client = client or httpx.Client(timeout=30)

    def _post(self, body: dict) -> dict:
        r = self._client.post(f"{BASE}/{self.model}:generateContent", json=body, headers={"x-goog-api-key": self._key})
        if r.status_code == 200:
            return r.json()
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        message = err.get("message", "")
        reasons = {d.get("reason") for d in err.get("details", []) if isinstance(d, dict)}
        if r.status_code in (401, 403) or "API_KEY_INVALID" in reasons or "api key not valid" in message.lower():
            raise LlmAuthError(err.get("status") or f"HTTP {r.status_code}")
        if r.status_code == 429:
            raise LlmQuotaError(err.get("status") or "RESOURCE_EXHAUSTED")
        if r.status_code == 404:
            raise LlmError(f"model not found: {self.model}")
        raise LlmError(f"HTTP {r.status_code}: {message[:160]}")

    def generate_json(self, system: str, prompt: str, schema: dict, max_output_tokens: int = 600) -> LlmResult:
        config = {
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "temperature": 0,
            "maxOutputTokens": max_output_tokens,
        }
        if self.model not in _no_thinking_config:
            config["thinkingConfig"] = {"thinkingLevel": "minimal"}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": config,
        }
        try:
            data = self._post(body)
        except LlmError as exc:
            if "thinkingConfig" in config and "thinking" in str(exc).lower():
                _no_thinking_config.add(self.model)
                config.pop("thinkingConfig")
                data = self._post(body)
            else:
                raise
        usage = data.get("usageMetadata", {})
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as exc:
            raise LlmError("empty response") from exc
        return LlmResult(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)),
        )

    def ping(self) -> None:
        body = {"contents": [{"role": "user", "parts": [{"text": "Reply with OK."}]}], "generationConfig": {"maxOutputTokens": 5}}
        self._post(body)
