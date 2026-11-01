"""Small paired Phase 1 matrix; no credential discovery and no silent LLM retries."""

import csv
import json
from pathlib import Path
from uuid import uuid4

from mas_recovery.core.schemas import ExperimentConfig, FaultSpec, Task
from mas_recovery.evaluation.analysis import aggregate, paired_metrics
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
) -> Path:
    if repeats < 1 or not tasks or len({t.id for t in tasks}) != len(tasks):
        raise ValueError("Need positive repeats and nonempty tasks with unique IDs")
    if any(not t.catalog for t in tasks):
        raise ValueError("The suite requires structured catalog tasks")
    # Validate limits before creating any outputs or consuming API calls.
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
    (suite / "dataset.json").write_text(
        json.dumps([t.model_dump() for t in tasks], indent=2) + "\n"
    )
    rows, overhead_pairs = [], []

    def run(task, replicate, method, fault=None, tracking=True):
        config = ExperimentConfig(
            name="phase1-paired",
            recovery=method,
            fault=fault,
            replicate=replicate,
            tracking=tracking,
            **common,
        )
        path = run_experiment(config, task, backend, suite / "runs", model, raise_errors=False)
        row = json.loads((path / "summary.json").read_text())
        row.update(run_id=path.name, replicate=replicate, tracking=tracking)
        return path, row

    for replicate in range(repeats):
        for task in tasks:
            clean, row = run(task, replicate, "none")
            rows.append(row)
            _, row = run(task, replicate, "always_verify")
            rows.append(row)
            for fault in FAULTS:
                for method in METHODS:
                    path, row = run(task, replicate, method, fault)
                    row.update(paired_metrics(clean, path, fault.stage))
                    rows.append(row)
            if overhead:
                # Alternate order to reduce systematic warmup bias. Both retain lean scoring events.
                order = (True, False) if replicate % 2 == 0 else (False, True)
                pair = {}
                for tracking in order:
                    _, extra = run(task, replicate, "none", tracking=tracking)
                    pair[tracking] = extra
                    rows.append(extra)
                overhead_pairs.append(
                    {
                        "task_id": task.id,
                        "replicate": replicate,
                        "disk_trace_seconds_difference": pair[True]["elapsed_seconds"]
                        - pair[False]["elapsed_seconds"],
                        "trace_bytes": pair[True]["trace_bytes"],
                        "both_completed": all(r["status"] == "completed" for r in pair.values()),
                    }
                )
    (suite / "results.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    )
    summary = aggregate(rows)
    (suite / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (suite / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    (suite / "overhead.json").write_text(json.dumps(overhead_pairs, indent=2) + "\n")
    (suite / "suite-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "backend": backend_name,
                "model": model,
                "repeats": repeats,
                "faults": [f.model_dump() for f in FAULTS],
                "methods": METHODS,
                "limits": common,
                "runs": len(rows),
                "overhead": overhead,
                "limitations": [
                    "Fake backend is an instrumentation fixture, not model safety evidence.",
                    "Output divergence is observational; remote sampling can also change outputs.",
                    "Verifier reads ground truth: privileged programmatic upper bound.",
                    "Timeout simulates a missing output before dispatch; "
                    "no partial remote execution.",
                    "Token limits can overshoot by one response; unknown usage is not zero.",
                    "Overhead pairs measure disk tracing, not all dependency bookkeeping.",
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return suite
