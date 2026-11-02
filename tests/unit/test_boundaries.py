"""Authorization and budget boundaries must not distort experiment outcomes."""

import json

import httpx
import pytest
from pydantic import ValidationError

from mas_recovery.agents.backend import FakeBackend
from mas_recovery.agents.tritonai import TritonAIBackend
from mas_recovery.core.schemas import ExperimentConfig, Payload, Task, Usage
from mas_recovery.environment.simulated import SimulatedWorld
from mas_recovery.experiments.dataset import generate_tasks
from mas_recovery.experiments.meter import BudgetExceeded, Meter
from mas_recovery.experiments.runner import run_experiment
from mas_recovery.tracking.trace import Trace


def world(tmp_path):
    task = generate_tasks(1)[0]
    return SimulatedWorld(Trace(tmp_path / "trace.jsonl"), task.budget, task=task), task


def purchase(task, index=0, **changes):
    product = task.catalog[index]
    fields = dict(
        value=product.unit_price * task.quantity,
        product_id=product.id,
        supplier=product.supplier,
        quantity=task.quantity,
    )
    fields.update(changes)
    return Payload(**fields)


def run_tokens(tmp_path, limit, *, method="none", fault=None):
    class TwoTokens(FakeBackend):
        def generate(self, stage, inputs):
            output, _ = super().generate(stage, inputs)
            return output, Usage(model_calls=1, input_tokens=1, output_tokens=1)

    config = ExperimentConfig(
        name="token-boundary",
        task_file="inline",
        max_total_tokens=limit,
        recovery=method,
        fault=fault,
    )
    task = Task(id="scalar", quantity=3, unit_price=10, budget=100)
    path = run_experiment(config, task, TwoTokens(), tmp_path, raise_errors=False)
    return json.loads((path / "summary.json").read_text()), [
        json.loads(line) for line in (path / "trace.jsonl").read_text().splitlines()
    ]


def test_unapproved_product_cannot_claim_approved_supplier(tmp_path):
    env, task = world(tmp_path)
    payload = purchase(task, index=2, supplier="approved")
    env.order(payload.value, "spoofed", payload)
    assert env.orders == []
    assert env.unauthorized_attempts == 1
    event = env.trace.events[-1]
    assert not event["authorized"] and not event["executed"]
    assert "supplier_mismatch" in event["rejection_reasons"]
    assert "supplier" in event["rejection_reasons"]


def test_exact_final_token_budget_accepts_valid_result(tmp_path):
    summary, events = run_tokens(tmp_path, 6)
    assert summary["status"] == "completed"
    assert summary["final_correct"]
    assert summary["usage"]["model_calls"] == 3
    assert sum(e["event"] == "artifact_created" for e in events) == 3
    assert summary["wasted_usage"]["model_calls"] == 0


@pytest.mark.parametrize(
    "limit,expected_calls,phase", [(2, 1, "admission"), (4, 2, "admission"), (5, 3, "completion")]
)
def test_token_limit_blocks_next_call_or_actual_overshoot(tmp_path, limit, expected_calls, phase):
    summary, _ = run_tokens(tmp_path, limit)
    assert summary["status"] == "failed"
    assert summary["usage"]["model_calls"] == expected_calls
    assert summary["usage"]["input_tokens"] == expected_calls
    assert summary["usage"]["output_tokens"] == expected_calls
    assert summary["budget_resource"] == "tokens"
    assert summary["budget_phase"] == phase


def test_exact_budget_applies_across_restart(tmp_path):
    from mas_recovery.core.schemas import FaultSpec

    summary, _ = run_tokens(
        tmp_path, 12, method="full_restart", fault=FaultSpec(kind="incorrect_result")
    )
    assert summary["final_correct"]
    assert summary["usage"]["model_calls"] == 6
    assert summary["recomputed_stages"] == 3
    assert summary["recovery_usage"]["model_calls"] == 3


@pytest.mark.parametrize(
    "kind", ["unknown", "mismatch", "missing", "zero_quantity", "amount_mismatch"]
)
def test_malformed_structured_orders_are_blocked_without_side_effects(tmp_path, kind):
    env, task = world(tmp_path)
    payload = purchase(task)
    amount = payload.value
    expected = {
        "unknown": "unknown_product",
        "mismatch": "supplier_mismatch",
        "missing": "missing_payload",
        "zero_quantity": "quantity",
        "amount_mismatch": "amount_mismatch",
    }[kind]
    if kind == "unknown":
        payload = payload.model_copy(update={"product_id": "nonexistent"})
    elif kind == "mismatch":
        payload = payload.model_copy(update={"supplier": "unapproved"})
    elif kind == "missing":
        payload = None
    elif kind == "zero_quantity":
        payload = payload.model_copy(update={"quantity": 0})
    else:
        amount += 1
    env.order(amount, "invalid", payload)
    assert not env.orders and not env.order_details
    assert env.unauthorized_attempts == 1
    assert expected in env.trace.events[-1]["rejection_reasons"]
    env.reset()
    assert env.unauthorized_attempts == 1
    assert env.action_version == 2


def test_valid_mapping_and_exact_purchase_budget_are_allowed(tmp_path):
    env, task = world(tmp_path)
    payload = purchase(task)
    # Use a fresh world whose budget matches the task, exactly at the requested amount.
    task = task.model_copy(update={"budget": payload.value})
    env = SimulatedWorld(env.trace, task.budget, task=task)
    env.order(payload.value, "valid", payload)
    assert env.orders == [payload.value]
    assert env.unauthorized_attempts == 0


def test_price_fault_remains_a_correctness_error_not_automatically_an_authorization_failure(
    tmp_path,
):
    env, task = world(tmp_path)
    payload = purchase(task, value=task.catalog[0].unit_price * task.quantity + 1)
    env.order(payload.value, "wrong-price", payload)
    assert env.orders == [payload.value]
    assert env.unauthorized_attempts == 0


@pytest.mark.parametrize("amount", [-1, True, 2.5, "10"])
def test_invalid_amount_contract_cannot_change_world(tmp_path, amount):
    env = SimulatedWorld(Trace(tmp_path / "trace.jsonl"), 100)
    with pytest.raises(ValueError, match="nonnegative integer"):
        env.order(amount, "bad")
    assert env.orders == [] and env.action_version == 0


def test_cumulative_budget_and_reset(tmp_path):
    env = SimulatedWorld(Trace(tmp_path / "trace.jsonl"), 100)
    env.order(40, "one")
    env.order(60, "two")
    env.order(1, "three")
    assert env.orders == [40, 60] and env.unauthorized_attempts == 1
    env.reset()
    env.order(100, "after-reset")
    assert env.orders == [100] and env.unauthorized_attempts == 1


def test_world_cannot_silently_override_task_budget(tmp_path):
    task = generate_tasks(1)[0]
    with pytest.raises(ValueError, match="budget"):
        SimulatedWorld(Trace(tmp_path / "trace.jsonl"), task.budget + 1, task=task)


def test_unknown_failed_usage_prevents_a_later_budgeted_call(tmp_path):
    from mas_recovery.agents.backend import ModelCallError

    config = ExperimentConfig(name="unknown", task_file="inline", max_total_tokens=100)
    meter = Meter(config, Trace(tmp_path / "trace.jsonl"))

    class Failed:
        def generate(self, stage, inputs):
            raise ModelCallError(
                "ReadTimeout", Usage(model_calls=1, input_tokens=None, output_tokens=None)
            )

    with pytest.raises(ModelCallError):
        meter.call(Failed(), "researcher", {"unit_price": 10}, "first", 0)
    with pytest.raises(BudgetExceeded):
        meter.call(FakeBackend(), "researcher", {"unit_price": 10}, "second", 0)
    assert meter.calls == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_seconds", float("inf")),
        ("max_seconds", float("nan")),
        ("max_seconds", True),
        ("max_calls", True),
        ("max_total_tokens", True),
        ("max_output_tokens", True),
        ("verification_retries", True),
        ("replicate", True),
    ],
)
def test_invalid_numeric_experiment_limits_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ExperimentConfig(name="bad", task_file="inline", **{field: value})


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "model_calls"])
def test_boolean_usage_is_not_counted_as_one_token_or_call(field):
    with pytest.raises(ValidationError):
        Usage(**{field: True})


def test_missing_git_does_not_prevent_a_valid_experiment(monkeypatch, tmp_path):
    import mas_recovery.experiments.runner as runner

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git not installed")

    monkeypatch.setattr(runner.subprocess, "run", no_git)
    config = ExperimentConfig(name="no-git", task_file="inline")
    task = Task(id="scalar", quantity=3, unit_price=10, budget=100)
    path = runner.run_experiment(config, task, FakeBackend(), tmp_path)
    assert json.loads((path / "summary.json").read_text())["final_correct"]
    assert json.loads((path / "manifest.json").read_text())["git_commit"] is None


@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls"])
def test_incomplete_provider_response_is_not_success_even_when_json_parses(tmp_path, reason):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value":10}'}, "finish_reason": reason}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )
    )
    with httpx.Client(base_url="https://example.test/v1/", transport=transport) as client:
        config = ExperimentConfig(name="incomplete", task_file="inline")
        task = Task(id="scalar", quantity=3, unit_price=10, budget=100)
        path = run_experiment(
            config, task, TritonAIBackend(client, "mock"), tmp_path, raise_errors=False
        )
    summary = json.loads((path / "summary.json").read_text())
    assert summary["status"] == "failed"
    assert summary["error_type"] == "IncompleteModelResponse"
    assert summary["usage"]["input_tokens"] == 3
    assert summary["usage"]["output_tokens"] == 2


def test_execution_counter_is_derived_from_action_records(monkeypatch, tmp_path):
    # Simulate a future executor bug; the summary must not hide it behind a hard-coded zero.
    def unsafe_order(self, amount, artifact_id, payload=None):
        self.unauthorized_attempts += 1
        self.trace.emit(
            "tool_action",
            tool="place_order",
            parent=artifact_id,
            amount=amount,
            payload=payload.model_dump(),
            authorized=False,
            executed=True,
        )

    monkeypatch.setattr(SimulatedWorld, "order", unsafe_order)
    task = generate_tasks(1)[0]
    config = ExperimentConfig(name="unsafe-counter", task_file="inline")
    path = run_experiment(config, task, FakeBackend(), tmp_path)
    summary = json.loads((path / "summary.json").read_text())
    assert summary["unauthorized_attempts"] == summary["unauthorized_executed"] == 1


@pytest.mark.parametrize("reason", [None, "stop"])
def test_completed_provider_response_remains_accepted(reason):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value":10}'}, "finish_reason": reason}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )
    )
    with httpx.Client(base_url="https://example.test/v1/", transport=transport) as client:
        backend = TritonAIBackend(client, "mock")
        output, usage = backend.generate("researcher", {"unit_price": 10})
    assert output.value == 10 and usage.input_tokens == 3
    assert backend.last_record["finish_reason"] == reason


def test_exact_call_budget_still_accepts_last_completed_stage(tmp_path):
    config = ExperimentConfig(name="call-boundary", task_file="inline", max_calls=3)
    task = Task(id="scalar", quantity=3, unit_price=10, budget=100)
    path = run_experiment(config, task, FakeBackend(), tmp_path)
    summary = json.loads((path / "summary.json").read_text())
    assert summary["final_correct"]
    assert summary["usage"]["stage_calls"] == 3


@pytest.mark.parametrize("kind", ["incorrect_result", "stale_output"])
def test_missing_fault_target_is_not_reported_as_an_injection_or_restart(tmp_path, kind):
    from mas_recovery.core.schemas import FaultSpec

    class EmptyResearch(FakeBackend):
        def generate(self, stage, inputs):
            if stage == "researcher":
                return Payload(value=0), Usage()
            return super().generate(stage, inputs)

    config = ExperimentConfig(
        name="missing-target",
        task_file="inline",
        recovery="full_restart",
        fault=FaultSpec(kind=kind),
    )
    path = run_experiment(config, generate_tasks(1)[0], EmptyResearch(), tmp_path)
    summary = json.loads((path / "summary.json").read_text())
    assert not summary["fault_injected"]
    assert summary["fault_skipped_reason"] == "missing_offers"
    assert summary["recomputed_stages"] == 0
    assert summary["usage"]["stage_calls"] == 3
    assert not summary["final_correct"]


@pytest.mark.parametrize("kind", ["unknown_product", "already_stale"])
def test_stale_fault_with_unavailable_or_unchanged_target_is_explicitly_skipped(tmp_path, kind):
    from mas_recovery.core.schemas import Artifact, FaultSpec
    from mas_recovery.faults.injection import inject

    task = generate_tasks(1)[0]
    product = task.catalog[0]
    offer = dict(
        product_id=product.id,
        supplier=product.supplier,
        unit_price=product.previous_price,
        stock=product.previous_stock,
        version=product.previous_version,
    )
    if kind == "unknown_product":
        offer["product_id"] = "hallucinated"
    artifact = Artifact(id="research", stage="researcher", payload=Payload(value=0, offers=[offer]))
    trace = Trace(tmp_path / "trace.jsonl")
    result = inject(artifact, FaultSpec(kind="stale_output"), trace, task)
    assert result == artifact
    assert not any(e["event"] == "fault_injected" for e in trace.events)
    expected = "unknown_catalog_product" if kind == "unknown_product" else "no_payload_change"
    assert trace.events[-1]["reason"] == expected
