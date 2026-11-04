"""One config to isolated run outputs. Failures remain measurable observations."""

import hashlib
import json
import platform
import subprocess
import tomllib
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from mas_recovery.agents.backend import Backend, ModelCallError
from mas_recovery.agents.tritonai import INSTRUCTIONS, PROMPT_VERSION
from mas_recovery.core.schemas import Artifact, ExperimentConfig, Payload, Task
from mas_recovery.environment.simulated import SimulatedWorld
from mas_recovery.evaluation.oracle import feasible, task_correct, verify_payload
from mas_recovery.experiments.exports import export_results, reserve_archive
from mas_recovery.experiments.meter import BudgetExceeded, Meter
from mas_recovery.faults.injection import InjectedTimeout
from mas_recovery.recovery.policy import FullRestart
from mas_recovery.tracking.trace import Trace
from mas_recovery.workflows.purchase import build_graph


def load_config(path: Path) -> tuple[ExperimentConfig, Task]:
    config = ExperimentConfig.model_validate(tomllib.loads(path.read_text()))
    task = Task.model_validate_json((path.parent / config.task_file).read_text())
    return config, task


def total_usage(events: list[dict]) -> dict:
    calls = [e for e in events if e["event"] == "call_finished"]
    result = {
        "stage_calls": len(calls),
        "model_calls": sum(e["usage"]["model_calls"] for e in calls),
    }
    for key in ("input_tokens", "output_tokens"):
        unknown = sum(e["usage"][key] is None for e in calls)
        known = sum(e["usage"][key] or 0 for e in calls)
        result[key] = None if unknown else known
        result["known_" + key] = known
        result["unknown_" + key + "_calls"] = unknown
    return result


def run_experiment(
    config: ExperimentConfig,
    task: Task,
    backend: Backend,
    output_root: Path,
    model: str = "deterministic-fake",
    *,
    raise_errors: bool = True,
    results_root: Path | None = None,
) -> Path:
    if (
        config.fault
        and config.fault.kind in ("stale_output", "malicious_instruction")
        and not task.catalog
    ):
        raise ValueError("This fault requires a structured catalog task")
    run_dir = output_root / uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    archive = reserve_archive(run_dir, results_root)
    trace = Trace(run_dir / "trace.jsonl", enabled=config.tracking)
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            check=False,
        )
        git_commit = revision.stdout.strip() if revision.returncode == 0 else None
    except OSError:
        # Git is optional provenance metadata, not a runtime dependency.
        git_commit = None
    task_json = json.dumps(task.model_dump(), sort_keys=True)
    source_root = Path(__file__).resolve().parents[1]
    source_hash = hashlib.sha256()
    for source in sorted(source_root.rglob("*.py")):
        source_hash.update(str(source.relative_to(source_root)).encode())
        source_hash.update(source.read_bytes())
    manifest = {
        "schema_version": 2,
        "config": config.model_dump(),
        "task": task.model_dump(),
        "task_sha256": hashlib.sha256(task_json.encode()).hexdigest(),
        "source_sha256": source_hash.hexdigest(),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(
            json.dumps(INSTRUCTIONS, sort_keys=True).encode()
        ).hexdigest(),
        "python": platform.python_version(),
        "langgraph": version("langgraph"),
        "model": model,
        "git_commit": git_commit or None,
        "fault_schedule": (
            "one-shot attempt 0; identity disclosed at completion or injected timeout"
        ),
        "verifier": "privileged programmatic oracle upper bound; zero inference calls",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    world = SimulatedWorld(trace, task.budget, task=task)
    meter = Meter(config, trace)
    started = perf_counter()
    summary: dict = {
        "status": "running",
        "initial_correct": None,
        "final_correct": None,
        "recomputed_stages": 0,
        "retained_artifacts": 0,
        "recovery_seconds": None,
        "task_id": task.id,
        "task_class": (
            "legacy" if not task.catalog else "feasible" if feasible(task) else "infeasible"
        ),
        "method": config.recovery,
        "fault_kind": config.fault.kind if config.fault else None,
        "fault_stage": config.fault.stage if config.fault else None,
        "fault_category": config.fault.category if config.fault else None,
    }
    try:
        timed_out = False
        try:
            build_graph(task, backend, world, trace, 0, config.fault, config, meter).invoke(
                {}, {"configurable": {"thread_id": f"{run_dir.name}:0"}}
            )
            summary["initial_correct"] = task_correct(task, world)
        except InjectedTimeout:
            timed_out = True
            summary["initial_correct"] = False
            if config.recovery != "full_restart":
                raise
        if (
            config.recovery == "full_restart"
            and config.fault is not None
            and any(e["event"] == "fault_injected" for e in trace.events)
        ):
            faulty_id = f"attempt-0:{config.fault.stage}"
            artifacts = [
                Artifact.model_validate(e["artifact"])
                for e in trace.events
                if e["event"] == "artifact_created"
            ]
            recovery_start = perf_counter()
            plan = FullRestart().plan(
                faulty_id, tuple(artifacts), config.fault.stage if timed_out else None
            )
            trace.emit(
                "recovery_started",
                faulty_id=faulty_id,
                plan=asdict(plan),
                disclosure="harness-known location; not automatic detection",
            )
            world.reset()
            try:
                build_graph(task, backend, world, trace, 1, None, config, meter).invoke(
                    {}, {"configurable": {"thread_id": f"{run_dir.name}:1"}}
                )
            finally:
                summary["recovery_seconds"] = perf_counter() - recovery_start
        summary.update(status="completed", final_correct=task_correct(task, world))
    except KeyboardInterrupt as error:
        trace.emit("run_interrupted", error_type="KeyboardInterrupt")
        summary.update(status="interrupted", error_type="KeyboardInterrupt", final_correct=False)
        # The suite can journal this run before propagating the user's interrupt.
        error.run_dir = run_dir
        raise
    except Exception as error:
        error_type = error.error_type if isinstance(error, ModelCallError) else type(error).__name__
        trace.emit("run_failed", error_type=error_type)
        summary.update(status="failed", error_type=error_type, final_correct=False)
        if isinstance(error, BudgetExceeded):
            summary.update(budget_resource=error.resource, budget_phase=error.phase)
            trace.emit("budget_exceeded", resource=error.resource, phase=error.phase)
        if raise_errors:
            raise
    finally:
        events = trace.events
        calls = [e for e in events if e["event"] == "call_finished"]
        rejected = {
            e["artifact_id"] for e in events if e["event"] == "verification" and not e["accepted"]
        }
        restarting = any(e["event"] == "recovery_started" for e in events)
        invalid_ids = {
            e["artifact"]["id"]
            for e in events
            if e["event"] == "artifact_created"
            and not verify_payload(
                task, e["artifact"]["stage"], Payload.model_validate(e["artifact"]["payload"])
            )
        }
        wasted = [
            e
            for e in calls
            if (restarting and e["attempt"] == 0)
            or e["artifact_id"] in rejected | invalid_ids
            or e["status"] == "failed"
            or summary["status"] in ("failed", "interrupted")
        ]
        injected = [e for e in events if e["event"] == "fault_injected"]
        faulty_ids = {e["artifact_id"] for e in injected}
        consumed = any(
            e["event"] == "artifact_created" and faulty_ids.intersection(e["artifact"]["parents"])
            for e in events
        )
        summary.update(
            elapsed_seconds=perf_counter() - started,
            trace_write_seconds=trace.write_seconds,
            unauthorized_attempts=world.unauthorized_attempts,
            unauthorized_executed=sum(
                e["event"] == "tool_action" and not e["authorized"] and e["executed"]
                for e in events
            ),
            fault_injected=bool(injected),
            fault_skipped_reason=next(
                (e["reason"] for e in events if e["event"] == "fault_not_injected"), None
            ),
            injected_result_consumed=consumed,
            recomputed_stages=sum(
                e["event"] == "artifact_created" and e["attempt"] > 0 for e in events
            ),
            verification_checks=sum(e["event"] == "verification" for e in events),
            verification_seconds=sum(
                e["latency_seconds"] for e in events if e["event"] == "verification"
            ),
            invalid_artifact_count=len(invalid_ids),
            usage=total_usage(events),
            wasted_usage=total_usage(wasted),
            wasted_seconds=sum(e["latency_seconds"] for e in wasted),
            recovery_usage=total_usage([e for e in calls if e["attempt"] > 0]),
            trace_bytes=trace.path.stat().st_size if trace.path.exists() else 0,
            propagation_evidence=[
                {"stage": e["stage"], "inputs": e["inputs"]}
                for e in events
                if e["event"] == "stage_started"
                and faulty_ids.intersection(e["parents"])
                and any(
                    a["event"] == "artifact_created" and a["artifact"]["id"] == e["artifact_id"]
                    for a in events
                )
            ],
        )
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        export_results(run_dir, archive)
    return run_dir
