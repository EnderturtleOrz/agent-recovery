import json

import httpx
import pytest
from pydantic import ValidationError

from mas_recovery.agents.tritonai import TritonAIBackend, make_client


def test_compatible_request_and_usage():
    def handle(request):
        assert str(request.url) == "https://example.test/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "accessible-model"
        assert json.loads(body["messages"][1]["content"]) == {"value": 10, "quantity": 3}
        assert "temperature" not in body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value": 30}'}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    with httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(handle)
    ) as c:
        payload, usage = TritonAIBackend(c, "accessible-model").generate(
            "planner",
            {"value": 10, "quantity": 3},
        )
    assert payload.value == 30
    assert usage.model_calls == 1
    assert usage.input_tokens == 20
    assert usage.output_tokens == 5


def test_unknown_usage_is_not_zero():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value": 10}'}}],
            },
        )
    )
    with httpx.Client(base_url="https://example.test/v1/", transport=transport) as c:
        _, usage = TritonAIBackend(c, "test").generate("researcher", {"unit_price": 10})
    assert usage.input_tokens is None
    assert usage.output_tokens is None


@pytest.mark.parametrize("content", ['{"value": "30"}', '{"value": -1}', "not json"])
def test_invalid_model_output_fails_without_repair(content):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
            },
        )
    )
    with httpx.Client(base_url="https://example.test/v1/", transport=transport) as c:
        with pytest.raises(ValidationError):
            TritonAIBackend(c, "test").generate("executor", {"value": 30})


def test_missing_key_has_actionable_error(monkeypatch):
    monkeypatch.delenv("TRITONAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TRITONAI_API_KEY"):
        make_client()


def test_ucsd_default_endpoint_and_authorization(monkeypatch):
    monkeypatch.setenv("TRITONAI_API_KEY", "mock-key")
    monkeypatch.delenv("TRITONAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with make_client() as client:
        assert str(client.base_url) == "https://tritonai-api.ucsd.edu/v1/"
        assert client.headers["Authorization"] == "Bearer mock-key"


def test_openai_environment_aliases(monkeypatch):
    monkeypatch.delenv("TRITONAI_API_KEY", raising=False)
    monkeypatch.delenv("TRITONAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "mock-alias-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    with make_client() as client:
        assert str(client.base_url) == "https://example.test/v1/"
        assert client.headers["Authorization"] == "Bearer mock-alias-key"


def test_tritonai_variables_take_precedence(monkeypatch):
    monkeypatch.setenv("TRITONAI_API_KEY", "mock-specific-key")
    monkeypatch.setenv("TRITONAI_BASE_URL", "https://specific.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "mock-other-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://other.example/v1")
    with make_client() as client:
        assert str(client.base_url) == "https://specific.example/v1/"
        assert client.headers["Authorization"] == "Bearer mock-specific-key"
