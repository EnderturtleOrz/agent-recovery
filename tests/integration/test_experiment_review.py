"""Stage-specific faults, independent controls, and interrupted batch durability."""

import json
import sys
from pathlib import Path

import httpx
import pytest

from mas_recovery import cli
from mas_recovery.agents.backend import FakeBackend
from mas_recovery.agents.tritonai import TritonAIBackend
from mas_recovery.core.schemas import Artifact, ExperimentConfig, FaultSpec, Payload, Task
from mas_recovery.experiments.dataset import generate_tasks
from mas_recovery.experiments.runner import run_experiment
from mas_recovery.experiments.suite import run_suite
from mas_recovery.faults.injection import inject
from mas_recovery.tracking.trace import Trace


def test_planner_numeric_fault_changes_total_even_if_output_contains_offers(tmp_path):
    task = generate_tasks(1)[0]
    offers, _ = FakeBackend().generate(
        "researcher", {"catalog": [p.model_dump() for p in task.catalog]}
    )
    payload = Payload(value=30, offers=offers.offers)
    artifact = Artifact(id="plan", stage="planner", payload=payload)
    changed = inject(
        artifact,
        FaultSpec(kind="incorrect_result", stage="planner"),
        Trace(tmp_path / "trace.jsonl"),
        task,
    )
    assert changed.payload.value == 37
    assert changed.payload.offers == payload.offers


def test_scalar_fault_changes_scalar_value_even_with_extraneous_offers(tmp_path):
    task = Task(id="legacy", quantity=3, unit_price=10, budget=100)
    data = generate_tasks(1)[0]
    offers, _ = FakeBackend().generate(
        "researcher", {"catalog": [p.model_dump() for p in data.catalog]}
    )
    artifact = Artifact(
        id="research", stage="researcher", payload=Payload(value=10, offers=offers.offers)
    )
    changed = inject(
        artifact, FaultSpec(kind="incorrect_result"), Trace(tmp_path / "trace.jsonl"), task
    )
    assert changed.payload.value == 17
    assert changed.payload.offers == artifact.payload.offers


def test_extra_overhead_runs_do_not_inflate_clean_baseline_counts(tmp_path):
    suite = run_suite(generate_tasks(3), FakeBackend(), tmp_path, overhead=True)
    summary = json.loads((suite / "summary.json").read_text())
    assert sum(g["runs"] for g in summary if g["run_role"] == "clean") == 3
    assert sum(g["runs"] for g in summary if g["run_role"] == "clean_verify") == 3
    assert sum(g["runs"] for g in summary if g["run_role"] == "overhead") == 6
    assert sum(g["runs"] for g in summary if g["run_role"] == "fault") == 54
    manifest = json.loads((suite / "suite-manifest.json").read_text())
    assert manifest["status"] == "completed"
    assert manifest["runs"] == manifest["planned_runs"] == 66


def test_ctrl_c_preserves_finished_and_interrupted_runs_and_stops_batch(tmp_path):
    class InterruptFourth(FakeBackend):
        calls = 0

        def generate(self, stage, inputs):
            self.calls += 1
            if self.calls == 4:
                suite = next(tmp_path.glob("suite-*"))
                rows = [
                    json.loads(line) for line in (suite / "results.jsonl").read_text().splitlines()
                ]
                assert len(rows) == 1 and rows[0]["run_role"] == "clean"
                assert (
                    json.loads((suite / "suite-manifest.json").read_text())["status"] == "running"
                )
                raise KeyboardInterrupt()
            return super().generate(stage, inputs)

    backend = InterruptFourth()
    with pytest.raises(KeyboardInterrupt):
        run_suite(generate_tasks(1), backend, tmp_path, overhead=True)
    assert backend.calls == 4
    suite = next(tmp_path.glob("suite-*"))
    rows = [json.loads(line) for line in (suite / "results.jsonl").read_text().splitlines()]
    assert [r["status"] for r in rows] == ["completed", "interrupted"]
    assert rows[1]["final_correct"] is False
    assert rows[1]["wasted_usage"]["stage_calls"] == 1
    manifest = json.loads((suite / "suite-manifest.json").read_text())
    assert manifest["status"] == "interrupted" and manifest["runs"] == 2
    assert manifest["planned_runs"] == 22
    assert (suite / "summary.csv").exists()
    groups = json.loads((suite / "summary.json").read_text())
    assert sum(g["interrupted_runs"] for g in groups) == 1
    events = [
        json.loads(line)
        for line in (suite / "runs" / rows[1]["run_id"] / "trace.jsonl").read_text().splitlines()
    ]
    call = next(e for e in events if e["event"] == "call_finished")
    assert call["status"] == "interrupted"


def test_interrupted_provider_request_retains_attempt_cost_and_is_not_retried(tmp_path):
    requests = []

    def interrupt(request):
        requests.append(request)
        raise KeyboardInterrupt()

    with httpx.Client(
        base_url="https://example.test/v1/", transport=httpx.MockTransport(interrupt)
    ) as client:
        config = ExperimentConfig(name="interrupt", backend="tritonai", task_file="inline")
        task = Task(id="legacy", quantity=3, unit_price=10, budget=100)
        with pytest.raises(KeyboardInterrupt) as error:
            run_experiment(config, task, TritonAIBackend(client, "mock"), tmp_path)
    assert len(requests) == 1
    summary = json.loads((error.value.run_dir / "summary.json").read_text())
    assert summary["status"] == "interrupted"
    assert summary["usage"]["model_calls"] == 1
    assert summary["usage"]["input_tokens"] is None
    assert summary["wasted_usage"]["model_calls"] == 1


@pytest.mark.parametrize("repeat", [True, 0, 1.5, "2"])
def test_bad_repeat_counts_fail_before_creating_suite(tmp_path, repeat):
    with pytest.raises(ValueError, match="integer"):
        run_suite(generate_tasks(1), FakeBackend(), tmp_path, repeats=repeat)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("override", ["fake", "tritonai"])
def test_single_run_backend_override_is_reflected_in_manifest_config(
    monkeypatch, tmp_path, override
):
    root = Path(__file__).resolve().parents[2]
    config = root / "configs" / ("tritonai.toml" if override == "fake" else "structured.toml")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRITONAI_MODEL", "mock")
    monkeypatch.setattr(
        cli, "make_client", lambda: httpx.Client(base_url="https://example.test/v1/")
    )

    def inspect(config, task, backend, output, *model):
        assert config.backend == override
        assert isinstance(backend, FakeBackend if override == "fake" else TritonAIBackend)
        return tmp_path

    monkeypatch.setattr(cli, "run_experiment", inspect)
    monkeypatch.setattr(
        sys, "argv", ["mas-recovery", "run", "--config", str(config), "--backend", override]
    )
    cli.main()


def test_cli_interrupt_reports_partial_results_and_returns_130(monkeypatch, tmp_path, capsys):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(tmp_path)

    def interrupt(*args, **kwargs):
        error = KeyboardInterrupt()
        error.suite_dir = tmp_path / "partial-suite"
        raise error

    monkeypatch.setattr(cli, "run_suite", interrupt)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mas-recovery",
            "suite",
            "--backend",
            "fake",
            "--tasks",
            str(root / "data/tasks/purchase-suite.json"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 130
    assert "partial-suite" in capsys.readouterr().err
