"""Compact, versionable results; raw prompts and traces stay in artifacts."""

import json
import shutil
from pathlib import Path


def reserve_archive(source: Path, results_root: Path | None) -> Path | None:
    """Check the destination before inference, and never overwrite an older export."""
    if results_root is None:
        return None
    destination = results_root / source.name
    raw, compact = source.resolve(), destination.resolve()
    if compact.is_relative_to(raw) or raw.is_relative_to(compact):
        raise ValueError("Results and raw artifact directories must be separate")
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def compact_metrics(row: dict) -> dict:
    # This field duplicates stage inputs, rather than storing a measured metric.
    return {key: value for key, value in row.items() if key != "propagation_evidence"}


def export_results(source: Path, destination: Path | None, *, suite: bool = False) -> None:
    if destination is None:
        return
    names = (
        ("dataset.json", "suite-manifest.json", "summary.json", "summary.csv", "overhead.json")
        if suite
        else ("manifest.json",)
    )
    for name in names:
        shutil.copyfile(source / name, destination / name)
    if suite:
        with (destination / "results.jsonl").open("w") as metrics:
            with (destination / "run-metadata.jsonl").open("w") as provenance:
                for line in (source / "results.jsonl").read_text().splitlines():
                    row = json.loads(line)
                    metrics.write(json.dumps(compact_metrics(row), sort_keys=True) + "\n")
                    manifest = json.loads(
                        (source / "runs" / row["run_id"] / "manifest.json").read_text()
                    )
                    # Tasks are already stored once in dataset.json.
                    manifest.pop("task")
                    manifest.update(run_id=row["run_id"], task_id=row["task_id"])
                    provenance.write(json.dumps(manifest, sort_keys=True) + "\n")
        status = json.loads((source / "suite-manifest.json").read_text())["status"]
    else:
        row = json.loads((source / "summary.json").read_text())
        (destination / "summary.json").write_text(json.dumps(compact_metrics(row), indent=2) + "\n")
        status = row["status"]
    (destination / "README.md").write_text(
        "# Experiment results\n\n"
        f"Status: **{status}**. Raw artifact directory ID: `{source.name}`.\n\n"
        "This archive keeps metrics, task data and reproducibility metadata. "
        "Raw model requests/responses and trace events remain in the original artifacts "
        "directory. No .env file or API credentials are copied.\n\n"
        "Only completed experiment groups should be reported as full matrices. "
        "Failed runs remain in success-rate denominators. "
        "Fake-backend results validate instrumentation, not real-model robustness.\n"
    )
