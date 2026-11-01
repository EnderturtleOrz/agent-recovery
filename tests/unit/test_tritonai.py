import json

import httpx
import pytest

from mas_recovery.agents.backend import ModelCallError
from mas_recovery.agents.tritonai import PROMPT_VERSION, TritonAIBackend, make_client


def test_compatible_request_and_usage():
    def handle(request):
        assert str(request.url) == "https://example.test/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "accessible-model"
        assert json.loads(body["messages"][1]["content"]) == {
            "value": 10,
            "quantity": 3,
        }
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
        with pytest.raises(ModelCallError, match="ValidationError"):
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


@pytest.mark.parametrize(
    "stage,inputs,expected",
    [
        ("researcher", {"unit_price": 10}, 10),
        ("planner", {"value": 10, "quantity": 3}, 30),
        ("executor", {"value": 30}, 30),
        ("planner", {"value": 17, "quantity": 3}, 51),
        ("planner", {"value": 0, "quantity": 3}, 0),
    ],
)
def test_scalar_requests_have_only_scalar_instructions_and_schema(stage, inputs, expected):
    def handle(request):
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        assert all(word not in prompt for word in ("catalog", "offers", "budget", "supplier"))
        schema = json.loads(prompt.split("matching this schema: ")[1])
        assert set(schema["properties"]) == {"value"}
        assert schema["required"] == ["value"]
        assert schema["additionalProperties"] is False
        data = json.loads(body["messages"][1]["content"])
        answer = (
            data["unit_price"]
            if stage == "researcher"
            else (data["value"] * data["quantity"] if stage == "planner" else data["value"])
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"value": answer})}}]},
        )

    with httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(handle)
    ) as c:
        backend = TritonAIBackend(c, "test")
        payload, _ = backend.generate(stage, inputs)
    assert payload.value == expected
    assert backend.last_record["prompt_mode"] == "scalar"
    assert backend.last_record["prompt_version"] == PROMPT_VERSION == "purchase-v3"


@pytest.mark.parametrize(
    "stage,inputs",
    [
        ("researcher", {"catalog": []}),
        (
            "planner",
            {
                "research": {"offers": []},
                "quantity": 3,
                "budget": 100,
                "allowed_suppliers": ["approved"],
            },
        ),
        ("executor", {"plan": {"value": 0}}),
    ],
)
def test_structured_requests_never_fall_back_to_scalar_on_empty_data(stage, inputs):
    def handle(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        assert "legacy" not in prompt.lower()
        schema = json.loads(prompt.split("matching this schema: ")[1])
        assert "offers" in schema["properties"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"value":0}'}}]})

    with httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(handle)
    ) as c:
        backend = TritonAIBackend(c, "test")
        backend.generate(stage, inputs)
    assert backend.last_record["prompt_mode"] == "structured"


@pytest.mark.parametrize(
    "inputs",
    [
        {"value": 10, "quantity": 3, "research": {}},
        {"quantity": 3},
    ],
)
def test_ambiguous_inputs_fail_before_api_dispatch(inputs):
    def unexpected(request):
        pytest.fail("Invalid input must not trigger a model request")

    with httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(unexpected)
    ) as c:
        with pytest.raises(ValueError, match="input shape"):
            TritonAIBackend(c, "test").generate("planner", inputs)


def test_scalar_output_cannot_silently_use_structured_response_fields():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value":0,"quantity":0}'}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5},
            },
        )
    )
    with httpx.Client(base_url="https://example.test/v1/", transport=transport) as c:
        with pytest.raises(ModelCallError, match="ValidationError") as error:
            TritonAIBackend(c, "test").generate("planner", {"value": 10, "quantity": 3})
    assert error.value.usage.input_tokens == 7
    assert error.value.usage.output_tokens == 5
