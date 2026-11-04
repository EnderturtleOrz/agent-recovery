"""Paired Phase 1 matrix with durable per-run results and interruption summaries."""

import csv
import json
from pathlib import Path
from uuid import uuid4

from mas_recovery.core.schemas import ExperimentConfig, FaultSpec, Task
from mas_recovery.evaluation.analysis import aggregate, paired_metrics
from mas_recovery.experiments.exports import export_results, reserve_archive
from mas_recovery.experiments.runner import run_experiment

FAULTS = tuple(
    FaultSpec(kind=kind, stage=stage)
    for kind, stage in (
        ("incorrect_result", "researcher"),
        ("incorrect_result", "planner"),
        ("timeout", "researcher"),
        ("timeout", "planner"),
        ("stale_output", "researcher"),
        ("malicious_instruction", "researcher"),
    )
)
METHODS = ("none", "full_restart", "always_verify")


def run_suite(
    tasks: list[Task],
    backend,
    output_root: Path,
    *,
    backend_name="fake",
    model="deterministic-fake",
    repeats=1,
    overhead=False,
    max_calls=12,
    max_seconds=120.0,
    max_total_tokens=None,
    max_output_tokens=2048,
    results_root: Path | None = None,
) -> Path:
    if (
        type(repeats) is not int
        or repeats < 1
        or not tasks
        or len({t.id for t in tasks}) != len(tasks)
    ):
        raise ValueError("Need positive integer repeats and nonempty tasks with unique IDs")
    if any(not t.catalog for t in tasks):
        raise ValueError("The suite requires structured catalog tasks")
    common = dict(
        task_file="suite-inline",
        backend=backend_name,
        max_calls=max_calls,
        max_seconds=max_seconds,
        max_total_tokens=max_total_tokens,
        max_output_tokens=max_output_tokens,
    )
    ExperimentConfig(name="validate", **common)
    suite = output_root / ("suite-" + uuid4().hex)
    suite.mkdir(parents=True)
    archive = reserve_archive(suite, results_root)
    (suite / "dataset.json").write_text(
        json.dumps([t.model_dump() for t in tasks], indent=2) + "\n"
    )
    journal = suite / "results.jsonl"
    journal.touch()
    rows, overhead_pairs = [], []
    manifest = {
        "schema_version": 3,
        "backend": backend_name,
        "model": model,
        "repeats": repeats,
        "faults": [f.model_dump() for f in FAULTS],
        "methods": METHODS,
        "limits": common,
        "runs": 0,
        "planned_runs": len(tasks)
        * repeats
        * (2 + len(FAULTS) * len(METHODS) + (2 if overhead else 0)),
        "status": "running",
        "overhead": overhead,
        "limitations": [
            "Fake backend is an instrumentation fixture, not model safety evidence.",
            "Output divergence is observational; remote sampling can also change outputs.",
            "Verifier reads ground truth: privileged programmatic upper bound.",
            "Timeout simulates a missing output before dispatch; no partial remote execution.",
            "Token limits can overshoot by one response; unknown usage is not zero.",
            "Overhead pairs measure disk tracing, not all dependency bookkeeping.",
            "Ctrl+C saves partial summaries. Hard kills may prevent cleanup.",
        ],
    }

    def save_manifest():
        manifest["runs"] = len(rows)
        (suite / "suite-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    def record(row):
        # Flush one complete line per finished run rather than waiting for the full suite.
        with journal.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        rows.append(row)
        save_manifest()

    def result_row(path, replicate, role):
        row = json.loads((path / "summary.json").read_text())
        row.update(
            run_id=path.name,
            replicate=replicate,
            run_role=role,
            tracking=json.loads((path / "manifest.json").read_text())["config"]["tracking"],
        )
        return row

    def run(task, replicate, method, fault=None, tracking=True, *, role, reference=None):
        config = ExperimentConfig(
            name="phase1-paired",
            recovery=method,
            fault=fault,
            replicate=replicate,
            tracking=tracking,
            **common,
        )
        try:
            path = run_experiment(config, task, backend, suite / "runs", model, raise_errors=False)
        except KeyboardInterrupt as error:
            path = getattr(error, "run_dir", None)
            if path is not None:
                record(result_row(path, replicate, role))
            raise
        row = result_row(path, replicate, role)
        if fault is not None and reference is not None:
            row.update(paired_metrics(reference, path, fault.stage))
        record(row)
        return path, row

    save_manifest()
    try:
        for replicate in range(repeats):
            for task in tasks:
                clean, _ = run(task, replicate, "none", role="clean")
                run(task, replicate, "always_verify", role="clean_verify")
                for fault in FAULTS:
                    for method in METHODS:
                        run(task, replicate, method, fault, role="fault", reference=clean)
                if overhead:
                    order = (True, False) if replicate % 2 == 0 else (False, True)
                    pair = {}
                    for tracking in order:
                        _, pair[tracking] = run(
                            task, replicate, "none", tracking=tracking, role="overhead"
                        )
                    overhead_pairs.append(
                        {
                            "task_id": task.id,
                            "replicate": replicate,
                            "disk_trace_seconds_difference": pair[True]["elapsed_seconds"]
                            - pair[False]["elapsed_seconds"],
                            "trace_bytes": pair[True]["trace_bytes"],
                            "both_completed": all(
                                r["status"] == "completed" for r in pair.values()
                            ),
                        }
                    )
        manifest["status"] = "completed"
    except KeyboardInterrupt as error:
        manifest["status"] = "interrupted"
        error.suite_dir = suite
        raise
    except Exception:
        manifest["status"] = "failed"
        raise
    finally:
        summary = aggregate(rows)
        (suite / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        with (suite / "summary.csv").open("w", newline="") as stream:
            if summary:
                writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
                writer.writeheader()
                writer.writerows(summary)
        (suite / "overhead.json").write_text(json.dumps(overhead_pairs, indent=2) + "\n")
        save_manifest()
        export_results(suite, archive, suite=True)
    return suite
