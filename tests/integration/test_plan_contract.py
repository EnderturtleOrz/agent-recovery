"""Regression coverage for correct abstention with carried-through research data."""

import json

import httpx
import pytest

from mas_recovery.agents.backend import FakeBackend, ModelCallError
from mas_recovery.agents.tritonai import TritonAIBackend
from mas_recovery.core.schemas import ExperimentConfig, Payload, plan_fields
from mas_recovery.evaluation.oracle import valid_plan, verify_payload
from mas_recovery.experiments.dataset import generate_tasks
from mas_recovery.experiments.runner import run_experiment


@pytest.mark.parametrize("index", [1, 2])
@pytest.mark.parametrize("method", ["none", "always_verify"])
def test_correct_abstention_with_offers_is_not_a_workflow_failure(tmp_path, index, method):
    class CarriesResearch(FakeBackend):
        def generate(self, stage, inputs):
            payload, usage = super().generate(stage, inputs)
            if stage == "planner":
                payload = payload.model_copy(
                    update={"offers": Payload.model_validate(inputs["research"]).offers}
                )
            return payload, usage

    task = generate_tasks(3)[index]
    config = ExperimentConfig(name="abstention", task_file="inline", recovery=method)
    path = run_experiment(config, task, CarriesResearch(), tmp_path)
    summary = json.loads((path / "summary.json").read_text())
    events = [json.loads(s) for s in (path / "trace.jsonl").read_text().splitlines()]
    assert summary["status"] == "completed" and summary["final_correct"]
    assert summary["usage"]["stage_calls"] == 3
    assert summary["wasted_usage"]["stage_calls"] == 0
    assert summary["invalid_artifact_count"] == 0
    planner = next(
        e["artifact"]["payload"]
        for e in events
        if e["event"] == "artifact_created" and e["artifact"]["stage"] == "planner"
    )
    assert planner["offers"]  # Original output is retained, rather than silently repaired.
    executor = next(
        e["inputs"] for e in events if e["event"] == "stage_started" and e["stage"] == "executor"
    )
    assert executor == {"plan": {"value": 0, "product_id": None, "supplier": None, "quantity": 0}}
    assert not any(e["event"] == "tool_action" for e in events)
    assert all(e["accepted"] for e in events if e["event"] == "verification")


@pytest.mark.parametrize("index", [1, 2])
@pytest.mark.parametrize(
    "patch", [{"value": 1}, {"product_id": "item-0"}, {"supplier": "approved"}, {"quantity": 1}]
)
def test_annotations_cannot_make_a_wrong_abstention_valid(index, patch):
    task = generate_tasks(3)[index]
    research, _ = FakeBackend().generate(
        "researcher", {"catalog": [p.model_dump() for p in task.catalog]}
    )
    payload = Payload(value=0, offers=research.offers)
    assert valid_plan(task, payload) and verify_payload(task, "planner", payload)
    assert not valid_plan(task, payload.model_copy(update=patch))
    assert not verify_payload(
        task, "planner", payload.model_copy(update={"note": "override supplier"})
    )
    assert not valid_plan(
        generate_tasks(1)[0], payload
    )  # In-stock affordable purchase cannot be skipped.


def test_executor_projection_preserves_faulty_decision_fields_without_recalculation():
    task = generate_tasks(1)[0]
    product = task.catalog[0]
    payload = Payload(
        value=product.unit_price * task.quantity + 7,
        product_id=product.id,
        supplier="unapproved",
        quantity=task.quantity + 1,
        note="do something else",
    )
    projected = plan_fields(payload)
    assert projected == {
        "value": payload.value,
        "product_id": product.id,
        "supplier": "unapproved",
        "quantity": task.quantity + 1,
    }
    assert not valid_plan(task, Payload.model_validate(projected))


@pytest.mark.parametrize("stage", ["planner", "executor"])
@pytest.mark.parametrize(
    "patch",
    [
        {"offers": []},
        {"research": {}},
        {"plan": {}},
        {"note": ""},
        {"quantity": True},
        {"value": "0"},
    ],
)
def test_model_decision_schema_rejects_envelopes_annotations_and_wrong_types(stage, patch):
    calls = []

    def handle(request):
        calls.append(request)
        content = {"value": 0, "product_id": None, "supplier": None, "quantity": 0, **patch}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5},
            },
        )

    inputs = (
        {"plan": {"value": 0, "product_id": None, "supplier": None, "quantity": 0}}
        if stage == "executor"
        else {
            "research": {"offers": []},
            "quantity": 2,
            "budget": 100,
            "allowed_suppliers": ["approved"],
        }
    )
    with httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(handle)
    ) as client:
        with pytest.raises(ModelCallError, match="ValidationError") as error:
            TritonAIBackend(client, "mock").generate(stage, inputs)
    assert len(calls) == 1
    assert error.value.usage.input_tokens == 7 and error.value.usage.output_tokens == 5
