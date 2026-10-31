"""One config -> one isolated run directory; no secret-bearing config dump."""

import json
import platform
import subprocess
import tomllib
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from mas_recovery.agents.backend import Backend
from mas_recovery.core.schemas import Artifact, ExperimentConfig, Task
from mas_recovery.environment.simulated import SimulatedWorld
from mas_recovery.evaluation.oracle import task_correct
from mas_recovery.recovery.policy import FullRestart
from mas_recovery.tracking.trace import Trace
from mas_recovery.workflows.purchase import build_graph


def load_config(path: Path) -> tuple[ExperimentConfig, Task]:
    config = ExperimentConfig.model_validate(tomllib.loads(path.read_text()))
    task = Task.model_validate_json((path.parent / config.task_file).read_text())
    return config, task


def run_experiment(
    config: ExperimentConfig,
    task: Task,
    backend: Backend,
    output_root: Path,
    model: str = "deterministic-fake",
) -> Path:
    run_dir = output_root / uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    trace = Trace(run_dir / "trace.jsonl")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    manifest = {
        "schema_version": 1,
        "config": config.model_dump(),
        "task": task.model_dump(),
        "python": platform.python_version(),
        "langgraph": version("langgraph"),
        "model": model,
        "git_commit": revision.stdout.strip() or None,
        "fault_schedule": "one-shot on attempt 0; oracle disclosure after completion",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    world = SimulatedWorld(trace, task.budget)
    started = perf_counter()
    summary: dict = {
        "status": "running",
        "initial_correct": None,
        "final_correct": None,
        "recomputed_stages": 0,
        "retained_artifacts": 0,
        "recovery_seconds": None,
    }
    try:
        state = build_graph(task, backend, world, trace, 0, config.fault).invoke(
            {},
            {"configurable": {"thread_id": f"{run_dir.name}:0"}},
        )
        summary["initial_correct"] = task_correct(task, world)
        if config.recovery == "full_restart" and config.fault is not None:
            faulty_id = f"attempt-0:{config.fault.stage}"
            artifacts = tuple(Artifact.model_validate(value) for value in state.values())
            recovery_start = perf_counter()
            plan = FullRestart().plan(faulty_id, artifacts)
            trace.emit("recovery_started", faulty_id=faulty_id, plan=asdict(plan))
            world.reset()
            build_graph(task, backend, world, trace, 1, None).invoke(
                {},
                {"configurable": {"thread_id": f"{run_dir.name}:1"}},
            )
            summary["recomputed_stages"] = len(plan.rerun_stages)
            summary["recovery_seconds"] = perf_counter() - recovery_start
        summary.update(status="completed", final_correct=task_correct(task, world))
    except Exception as error:
        # Avoid provider response bodies/headers in persisted errors; record failure, not success.
        trace.emit("run_failed", error_type=type(error).__name__)
        summary.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        summary.update(
            elapsed_seconds=perf_counter() - started,
            trace_write_seconds=trace.write_seconds,
            unauthorized_attempts=world.unauthorized_attempts,
            unauthorized_executed=0,  # SimulatedWorld enforces the budget before execution.
        )
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return run_dir
