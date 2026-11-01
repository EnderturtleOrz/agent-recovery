"""Behavioral tests of the Phase 1 matrix, failures, safety history and pairing."""

import json

import httpx
import pytest

from mas_recovery.agents.backend import FakeBackend
from mas_recovery.agents.tritonai import TritonAIBackend
from mas_recovery.core.schemas import ExperimentConfig, FaultSpec, Payload, Usage
from mas_recovery.environment.simulated import SimulatedWorld
from mas_recovery.evaluation.analysis import aggregate, paired_metrics
from mas_recovery.evaluation.oracle import feasible, task_correct, valid_plan
from mas_recovery.experiments.dataset import generate_tasks
from mas_recovery.experiments.runner import run_experiment
from mas_recovery.experiments.suite import FAULTS, METHODS, run_suite
from mas_recovery.tracking.trace import Trace


def read(path):
    summary = json.loads((path / "summary.json").read_text())
    events = [json.loads(line) for line in (path / "trace.jsonl").read_text().splitlines()]
    return summary, events


def run(tmp_path, fault=None, method="none", task=None, backend=None, **limits):
    config = ExperimentConfig(
        name="phase1-test", task_file="inline", fault=fault, recovery=method, **limits
    )
    return run_experiment(
        config,
        task or generate_tasks(1)[0],
        backend or FakeBackend(),
        tmp_path,
        raise_errors=False,
    )


@pytest.mark.parametrize("task", generate_tasks())
def test_structured_clean_has_correct_decision_without_truth_leak(tmp_path, task):
    summary, events = read(run(tmp_path, task=task))
    assert summary["final_correct"]
    assert summary["unauthorized_attempts"] == 0
    assert summary["usage"]["stage_calls"] == 3
    inputs = [e["inputs"] for e in events if e["event"] == "stage_started"]
    assert "catalog" not in inputs[1] and "unit_price" not in inputs[2]
    assert "previous_price" not in json.dumps(inputs)


@pytest.mark.parametrize("fault", FAULTS)
@pytest.mark.parametrize("method", METHODS)
def test_fault_matrix_and_recovery(tmp_path, fault, method):
    summary, events = read(run(tmp_path, fault, method))
    assert summary["fault_injected"]
    assert sum(e["event"] == "fault_injected" for e in events) == 1
    if method in ("always_verify", "full_restart"):
        assert summary["status"] == "completed"
        assert summary["final_correct"]
    elif fault.kind == "timeout":
        assert summary["status"] == "failed"
        assert summary["usage"]["stage_calls"] == (0 if fault.stage == "researcher" else 1)
    else:
        assert summary["status"] == "completed"
        assert not summary["final_correct"]
        assert summary["injected_result_consumed"]
    if method == "always_verify":
        assert not summary["injected_result_consumed"]
        assert summary["verification_checks"] >= 3
    if fault.kind == "malicious_instruction" and method != "always_verify":
        assert summary["unauthorized_attempts"] == 1
        assert summary["unauthorized_executed"] == 0
    if method == "full_restart":
        assert summary["recomputed_stages"] == 3
        assert summary["recovery_usage"]["stage_calls"] == 3


def test_stale_output_has_real_old_versions(tmp_path):
    summary, events = read(run(tmp_path, FaultSpec(kind="stale_output")))
    artifact = next(e["artifact"] for e in events if e["event"] == "artifact_created")
    source = next(e for e in events if e["event"] == "stage_started")["inputs"]["catalog"]
    assert all(p["version"] == 2 for p in source)
    assert all(p["version"] == 1 for p in artifact["payload"]["offers"])
    assert all(s.endswith("@1") for s in artifact["sources"] if s.startswith("catalog:"))
    assert summary["wasted_usage"]["stage_calls"] > 0


def test_verifier_does_not_pass_rejected_artifact_downstream(tmp_path):
    _, events = read(run(tmp_path, FaultSpec(kind="incorrect_result"), "always_verify"))
    planner = next(e for e in events if e["event"] == "stage_started" and e["stage"] == "planner")
    assert planner["parents"] == ["attempt-0:researcher:retry-1"]
    assert (
        planner["inputs"]["research"]["offers"][0]["unit_price"]
        == generate_tasks(1)[0].catalog[0].unit_price
    )


def test_verification_retry_limit(tmp_path):
    summary, _ = read(
        run(
            tmp_path,
            FaultSpec(kind="incorrect_result"),
            "always_verify",
            verification_retries=0,
        )
    )
    assert summary["status"] == "failed"
    assert summary["error_type"] == "VerificationFailed"
    assert summary["usage"]["stage_calls"] == 1


def test_partial_recovery_budget_is_counted(tmp_path):
    summary, _ = read(
        run(tmp_path, FaultSpec(kind="incorrect_result"), "full_restart", max_calls=4)
    )
    assert summary["status"] == "failed"
    assert summary["error_type"] == "BudgetExceeded"
    assert summary["recomputed_stages"] == 1
    assert summary["usage"]["stage_calls"] == 4
    assert summary["recovery_seconds"] is not None
    assert summary["final_correct"] is False


def mock_backend(content="not json", usage=None, status=200):
    def handler(request):
        return httpx.Response(
            status,
            json={"choices": [{"message": {"content": content}}], "usage": usage or {}},
            headers={"x-request-id": "mock-request"},
        )

    client = httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(handler)
    )
    return client, TritonAIBackend(client, "mock")


def test_bad_json_keeps_cost_and_sanitized_request(tmp_path):
    client, backend = mock_backend(usage={"prompt_tokens": 9, "completion_tokens": 4})
    with client:
        summary, events = read(run(tmp_path, backend=backend))
    assert summary["usage"]["model_calls"] == 1
    assert summary["usage"]["input_tokens"] == 9
    assert summary["usage"]["output_tokens"] == 4
    assert summary["wasted_usage"]["model_calls"] == 1
    finished = next(e for e in events if e["event"] == "call_finished")
    assert finished["model_record"]["response_content"] == "not json"
    assert finished["model_record"]["request_id"] == "mock-request"
    assert "Authorization" not in json.dumps(events)


def test_network_failure_unknown_usage_is_not_zero(tmp_path):
    def fail(request):
        raise httpx.ReadTimeout("secret-provider-body", request=request)

    with httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(fail)
    ) as client:
        summary, events = read(run(tmp_path, backend=TritonAIBackend(client, "mock")))
    assert summary["usage"]["model_calls"] == 1
    assert summary["usage"]["input_tokens"] is None
    assert summary["usage"]["unknown_input_tokens_calls"] == 1
    assert "secret-provider-body" not in json.dumps(events)


def test_known_token_limit_stops_after_accounted_response(tmp_path):
    class TokenBackend(FakeBackend):
        def generate(self, stage, inputs):
            payload, _ = super().generate(stage, inputs)
            return payload, Usage(model_calls=1, input_tokens=9, output_tokens=4)

    summary, _ = read(run(tmp_path, backend=TokenBackend(), max_total_tokens=10))
    assert summary["error_type"] == "BudgetExceeded"
    assert summary["usage"]["model_calls"] == 1
    assert summary["usage"]["input_tokens"] == 9


def test_unknown_usage_with_token_budget_fails_closed(tmp_path):
    class Unknown(FakeBackend):
        def generate(self, stage, inputs):
            payload, _ = super().generate(stage, inputs)
            return payload, Usage(model_calls=1, input_tokens=None, output_tokens=None)

    summary, _ = read(run(tmp_path, backend=Unknown(), max_total_tokens=100))
    assert summary["error_type"] == "BudgetExceeded"
    assert summary["usage"]["input_tokens"] is None


def test_paired_metrics_separate_ignored_and_propagated(tmp_path):
    clean = run(tmp_path)
    faulty = run(tmp_path, FaultSpec(kind="incorrect_result"))
    metrics = paired_metrics(clean, faulty, "researcher")
    assert metrics["propagation_eligible"]
    assert metrics["affected_stages"] == ["planner", "executor"]
    assert metrics["propagated_task_failure"]
    verified = run(tmp_path, FaultSpec(kind="incorrect_result"), "always_verify")
    assert not paired_metrics(clean, verified, "researcher")["propagation_eligible"]


def test_safety_history_is_separate_from_no_purchase_correctness(tmp_path):
    task = generate_tasks(3)[1]
    assert not feasible(task)
    trace = Trace(tmp_path / "trace.jsonl")
    world = SimulatedWorld(trace, task.budget, task=task)
    world.order(task.budget + 1, "bad", Payload(value=task.budget + 1, supplier="unapproved"))
    assert task_correct(task, world)
    assert world.unauthorized_attempts == 1
    world.reset()
    assert world.unauthorized_attempts == 1


def test_wrong_product_quantity_price_and_supplier_are_rejected_by_oracle():
    task = generate_tasks(1)[0]
    product = feasible(task)[0]
    valid = Payload(
        value=product.unit_price * task.quantity,
        product_id=product.id,
        supplier=product.supplier,
        quantity=task.quantity,
    )
    assert valid_plan(task, valid)
    for patch in (
        {"value": valid.value + 1},
        {"quantity": task.quantity + 1},
        {"supplier": "unapproved"},
        {"product_id": "missing"},
    ):
        assert not valid_plan(task, valid.model_copy(update=patch))


def test_seed_reproducibility():
    assert generate_tasks(6, 17) == generate_tasks(6, 17)
    assert generate_tasks(6, 17) != generate_tasks(6, 18)


def test_full_suite_keeps_failures_and_separates_categories(tmp_path):
    suite = run_suite(generate_tasks(3), FakeBackend(), tmp_path, overhead=True)
    rows = [json.loads(line) for line in (suite / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 66  # 3 tasks x (2 clean + 6 faults x 3 methods + 2 overhead)
    assert sum(r["status"] == "failed" for r in rows) == 6
    assert any(r["fault_category"] == "adversarial" for r in rows)
    summary = json.loads((suite / "summary.json").read_text())
    timeout = next(r for r in summary if r["fault_kind"] == "timeout" and r["method"] == "none")
    assert timeout["task_success_rate"] == 0
    assert timeout["runs"] == timeout["failed_runs"]
    assert (
        sum(
            r["failed_runs"]
            for r in summary
            if r["fault_kind"] == "timeout" and r["method"] == "none"
        )
        == 6
    )
    assert timeout["propagation_eligible_runs"] == 0
    assert timeout["propagated_task_failure_rate"] is None
    assert (suite / "summary.csv").exists()
    assert len(json.loads((suite / "overhead.json").read_text())) == 3
    assert aggregate(rows) == summary


def test_mock_real_model_workflow_and_usage(tmp_path):
    fake = FakeBackend()

    def handler(request):
        data = json.loads(request.content)
        inputs = json.loads(data["messages"][1]["content"])
        stage = (
            "researcher"
            if "catalog" in inputs
            else "planner"
            if "research" in inputs
            else "executor"
        )
        payload, _ = fake.generate(stage, json.loads(data["messages"][1]["content"]))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": payload.model_dump_json()}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            },
        )

    with httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(handler)
    ) as client:
        summary, _ = read(
            run(
                tmp_path,
                FaultSpec(kind="incorrect_result"),
                "full_restart",
                backend=TritonAIBackend(client, "mock"),
            )
        )
    assert summary["final_correct"]
    assert summary["usage"]["model_calls"] == 6
    assert summary["usage"]["input_tokens"] == 72
    assert summary["usage"]["output_tokens"] == 48
    assert summary["recovery_usage"]["model_calls"] == 3


def test_failed_consumer_is_not_claimed_as_consumption(tmp_path):
    class FailsPlanner(FakeBackend):
        def generate(self, stage, inputs):
            if stage == "planner":
                raise TimeoutError("consumer did not return")
            return super().generate(stage, inputs)

    summary, _ = read(run(tmp_path, FaultSpec(kind="incorrect_result"), backend=FailsPlanner()))
    assert not summary["injected_result_consumed"]
    assert summary["status"] == "failed"


def test_nonpropagating_attack_is_not_misreported_as_recovery(tmp_path):
    class IgnoresNote(FakeBackend):
        def generate(self, stage, inputs):
            if stage == "planner":
                inputs = json.loads(json.dumps(inputs))
                inputs["research"]["note"] = ""
            return super().generate(stage, inputs)

    backend = IgnoresNote()
    clean = run(tmp_path, backend=backend)
    faulty = run(tmp_path, FaultSpec(kind="malicious_instruction"), backend=backend)
    summary, _ = read(faulty)
    metrics = paired_metrics(clean, faulty, "researcher")
    assert summary["final_correct"] and summary["unauthorized_attempts"] == 0
    assert metrics["consumption"] == "consumed_without_observed_divergence"
    assert metrics["propagated_task_failure"] is False
    assert summary["recomputed_stages"] == 0


def test_http_failure_stays_in_denominator(tmp_path):
    client, backend = mock_backend(status=429)
    with client:
        summary, _ = read(run(tmp_path, backend=backend))
    assert summary["status"] == "failed"
    assert summary["error_type"] == "HTTPStatusError"
    assert summary["usage"]["model_calls"] == 1
    assert summary["usage"]["input_tokens"] is None


def test_time_budget_stops_before_backend_dispatch(tmp_path):
    summary, _ = read(run(tmp_path, max_seconds=0.000001))
    assert summary["status"] == "failed"
    assert summary["error_type"] == "BudgetExceeded"
    assert summary["usage"]["stage_calls"] == 0
