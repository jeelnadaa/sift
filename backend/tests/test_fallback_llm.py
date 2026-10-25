"""Tests for Fallback LLM Provider and OpenAI-compatible / Ollama implementation."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy.orm import Session

from app.llm.base import LlmAuthError, LlmError, LlmQuotaError
from app.llm.openai_compatible import OpenAiCompatibleProvider
from app.llm import service as llm_service
from app.models import User
from tests.test_pipeline import setup, fake_llm, run, with_key  # noqa: F401


def test_openai_compatible_provider_generate_json():
    mock_client = MagicMock(spec=httpx.Client)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "category": "interview",
                        "priority": "urgent",
                        "summary": "Technical interview scheduled",
                        "action_needed": True,
                    })
                }
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 45,
        },
    }
    mock_client.post.return_value = mock_resp

    provider = OpenAiCompatibleProvider(
        api_key="sk-test-key-12345",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        client=mock_client,
    )

    result = provider.generate_json(
        system="Extract email details",
        prompt="From: recruiter@example.com\nSubject: Interview Invitation",
        schema={"type": "object"},
    )

    assert result.input_tokens == 120
    assert result.output_tokens == 45
    parsed = json.loads(result.text)
    assert parsed["category"] == "interview"
    assert parsed["priority"] == "urgent"

    # Verify authorization header
    args, kwargs = mock_client.post.call_args
    assert "https://api.openai.com/v1/chat/completions" in args[0]
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test-key-12345"


def test_openai_compatible_error_mapping():
    mock_client = MagicMock(spec=httpx.Client)

    # 401 Unauthorized
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.json.return_value = {"error": {"message": "Invalid API key"}}
    mock_client.post.return_value = resp_401

    provider = OpenAiCompatibleProvider(
        api_key="bad-key",
        model="llama3.2",
        provider_name="ollama",
        client=mock_client,
    )

    with pytest.raises(LlmAuthError):
        provider.generate_json("sys", "prompt", {})

    # 429 Quota
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.json.return_value = {"error": {"message": "Rate limit exceeded"}}
    mock_client.post.return_value = resp_429

    with pytest.raises(LlmQuotaError):
        provider.generate_json("sys", "prompt", {})


def test_save_key_with_fallback_and_status(db: Session, setup):
    user, _, _, _ = setup

    # Mock ping on provider
    mock_provider = MagicMock()
    mock_provider.ping.return_value = None

    orig_factory = llm_service.provider_factory
    try:
        llm_service.provider_factory = MagicMock(return_value=mock_provider)

        cred = llm_service.save_key(
            db=db,
            user_id=user.id,
            provider="gemini",
            model="gemini-2.5-flash",
            api_key="primary-gemini-key-12345",
            fallback_provider="ollama",
            fallback_model="llama3.2",
            fallback_base_url="http://localhost:11434/v1",
            fallback_api_key="ollama-local",
        )

        assert cred.provider == "gemini"
        assert cred.fallback_provider == "ollama"
        assert cred.fallback_model == "llama3.2"
        assert cred.fallback_base_url == "http://localhost:11434/v1"
        assert cred.fallback_key_last4 == "ocal"

        status = llm_service.status(db, user.id)
        assert status["provider"] == "gemini"
        assert status["fallback_provider"] == "ollama"
        assert status["fallback_model"] == "llama3.2"
        assert status["fallback_base_url"] == "http://localhost:11434/v1"
    finally:
        llm_service.provider_factory = orig_factory
