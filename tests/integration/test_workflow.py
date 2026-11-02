import json
from pathlib import Path

import pytest

from mas_recovery.agents.backend import FakeBackend
from mas_recovery.core.schemas import ExperimentConfig, FaultSpec, Task
from mas_recovery.experiments.runner import run_experiment

TASK = Task(id="test", quantity=3, unit_price=10, budget=100)


def read_run(path):
    return (
        json.loads((path / "summary.json").read_text()),
        [json.loads(line) for line in (path / "trace.jsonl").read_text().splitlines()],
    )


def config(**kwargs):
    return ExperimentConfig(name="test", task_file="unused.json", **kwargs)


def test_clean_graph_reaches_correct_world(tmp_path):
    summary, events = read_run(run_experiment(config(), TASK, FakeBackend(), tmp_path))
    assert summary["initial_correct"] is True
    assert summary["final_correct"] is True
    assert summary["recomputed_stages"] == 0
    artifacts = [event["artifact"] for event in events if event["event"] == "artifact_created"]
    assert [a["payload"]["value"] for a in artifacts] == [10, 30, 30]
    assert artifacts[1]["parents"] == [artifacts[0]["id"]]
    assert artifacts[2]["parents"] == [artifacts[1]["id"]]


@pytest.mark.parametrize("stage,expected", [("researcher", 51), ("planner", 37)])
def test_fault_is_consumed_and_changes_downstream_action(tmp_path, stage, expected):
    fault = FaultSpec(kind="incorrect_result", stage=stage)
    summary, events = read_run(run_experiment(config(fault=fault), TASK, FakeBackend(), tmp_path))
    assert summary["final_correct"] is False
    action = next(event for event in events if event["event"] == "tool_action")
    assert action["amount"] == expected
    assert action["executed"] is True
    executor_input = next(
        event
        for event in events
        if event["event"] == "stage_started" and event["stage"] == "executor"
    )
    assert executor_input["inputs"]["value"] == expected


def test_restart_restores_world_without_erasing_fault_history(tmp_path):
    fault = FaultSpec(kind="incorrect_result")
    summary, events = read_run(
        run_experiment(
            config(fault=fault, recovery="full_restart"),
            TASK,
            FakeBackend(),
            tmp_path,
        )
    )
    assert summary["initial_correct"] is False
    assert summary["final_correct"] is True
    assert summary["recomputed_stages"] == 3
    assert summary["retained_artifacts"] == 0
    assert sum(event["event"] == "artifact_created" for event in events) == 6
    assert sum(event["event"] == "fault_injected" for event in events) == 1
    actions = [event["amount"] for event in events if event["event"] == "tool_action"]
    assert actions == [51, 30]
    reset = next(event for event in events if event["event"] == "environment_reset")
    assert reset["before"] == [51]
    assert reset["after"] == []


def test_restart_preserves_unauthorized_attempt_count(tmp_path):
    task = TASK.model_copy(update={"budget": 40})
    summary, _ = read_run(
        run_experiment(
            config(fault=FaultSpec(kind="incorrect_result"), recovery="full_restart"),
            task,
            FakeBackend(),
            tmp_path,
        )
    )
    assert summary["final_correct"] is True
    assert summary["unauthorized_attempts"] == 1
    assert summary["unauthorized_executed"] == 0


def test_failure_is_persisted_and_not_counted_as_success(tmp_path):
    class BrokenBackend:
        def generate(self, stage, inputs):
            raise TimeoutError("provider details must not be persisted")

    with pytest.raises(TimeoutError):
        run_experiment(config(), TASK, BrokenBackend(), tmp_path)
    run_dir = next(tmp_path.iterdir())
    summary, _ = read_run(run_dir)
    assert summary["status"] == "failed"
    assert summary["final_correct"] is False
    assert "provider details" not in (run_dir / "trace.jsonl").read_text()


def test_checked_in_configs_load():
    from mas_recovery.experiments.runner import load_config

    root = Path(__file__).resolve().parents[2]
    for path in (root / "configs").glob("*.toml"):
        _, task = load_config(path)
        assert task.quantity > 0
        assert task.budget > 0
