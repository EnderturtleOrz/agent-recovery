"""Report archives retain measured results and provenance without raw conversations."""

import json
import sys
from pathlib import Path

import pytest

from mas_recovery import cli
from mas_recovery.agents.backend import FakeBackend
from mas_recovery.core.schemas import ExperimentConfig
from mas_recovery.experiments.dataset import generate_tasks
from mas_recovery.experiments.runner import run_experiment
from mas_recovery.experiments.suite import run_suite


def test_suite_archive_preserves_metrics_and_provenance_without_raw_inputs(tmp_path):
    source = run_suite(
        generate_tasks(3),
        FakeBackend(),
        tmp_path / "artifacts",
        overhead=True,
        results_root=tmp_path / "results",
    )
    archive = tmp_path / "results" / source.name
    assert set(p.name for p in archive.iterdir()) == {
        "README.md",
        "dataset.json",
        "suite-manifest.json",
        "summary.json",
        "summary.csv",
        "overhead.json",
        "results.jsonl",
        "run-metadata.jsonl",
    }
    for name in [
        "dataset.json",
        "suite-manifest.json",
        "summary.json",
        "summary.csv",
        "overhead.json",
    ]:
        assert (archive / name).read_bytes() == (source / name).read_bytes()
    original = [json.loads(s) for s in (source / "results.jsonl").read_text().splitlines()]
    rows = [json.loads(s) for s in (archive / "results.jsonl").read_text().splitlines()]
    metadata = [json.loads(s) for s in (archive / "run-metadata.jsonl").read_text().splitlines()]
    assert len(rows) == len(original) == len(metadata) == 66
    for full, compact, manifest in zip(original, rows, metadata, strict=True):
        assert compact == {k: v for k, v in full.items() if k != "propagation_evidence"}
        raw_manifest = json.loads((source / "runs" / full["run_id"] / "manifest.json").read_text())
        assert "task" not in manifest
        assert manifest["task_id"] == full["task_id"]
        assert manifest["run_id"] == full["run_id"]
        assert {k: v for k, v in manifest.items() if k not in ("task_id", "run_id")} == {
            k: v for k, v in raw_manifest.items() if k != "task"
        }
    assert sum(p.stat().st_size for p in archive.rglob("*") if p.is_file()) < sum(
        p.stat().st_size for p in source.rglob("*") if p.is_file()
    )


@pytest.mark.parametrize("failure", [ValueError, KeyboardInterrupt])
def test_single_failure_still_exports_status_and_usage(tmp_path, failure):
    class Broken(FakeBackend):
        def generate(self, stage, inputs):
            if stage == "planner":
                raise failure("stop")
            return super().generate(stage, inputs)

    with pytest.raises(failure):
        run_experiment(
            ExperimentConfig(name="failure", task_file="inline"),
            generate_tasks(1)[0],
            Broken(),
            tmp_path / "artifacts",
            results_root=tmp_path / "results",
        )
    (archive,) = (tmp_path / "results").iterdir()
    summary = json.loads((archive / "summary.json").read_text())
    assert summary["status"] == ("failed" if failure is ValueError else "interrupted")
    assert summary["usage"]["stage_calls"] >= 1
    assert not summary["final_correct"]
    assert "propagation_evidence" not in summary
    assert (archive / "manifest.json").exists()


def test_interrupted_suite_exports_partial_rows_and_planned_count(tmp_path):
    class Interrupting(FakeBackend):
        count = 0

        def generate(self, stage, inputs):
            self.count += 1
            if self.count == 5:
                raise KeyboardInterrupt()
            return super().generate(stage, inputs)

    with pytest.raises(KeyboardInterrupt):
        run_suite(
            generate_tasks(1),
            Interrupting(),
            tmp_path / "artifacts",
            results_root=tmp_path / "results",
        )
    (archive,) = (tmp_path / "results").iterdir()
    manifest = json.loads((archive / "suite-manifest.json").read_text())
    rows = [json.loads(s) for s in (archive / "results.jsonl").read_text().splitlines()]
    assert manifest["status"] == "interrupted"
    assert manifest["runs"] == len(rows) == 2
    assert manifest["planned_runs"] == 20
    assert rows[-1]["status"] == "interrupted"
    assert len((archive / "run-metadata.jsonl").read_text().splitlines()) == 2


def test_unwritable_export_destination_fails_before_backend_call(tmp_path):
    class NeverCalled(FakeBackend):
        def generate(self, stage, inputs):
            pytest.fail("must validate the export destination before model dispatch")

    target = tmp_path / "results"
    target.write_text("not a directory")
    with pytest.raises(OSError):
        run_suite(generate_tasks(1), NeverCalled(), tmp_path / "artifacts", results_root=target)


def test_cli_exports_to_results_by_default_and_keeps_older_run(monkeypatch, tmp_path, capsys):
    config = Path(__file__).resolve().parents[2] / "configs/structured.toml"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["mas-recovery", "run", "--config", str(config)])
    cli.main()
    (first,) = (tmp_path / "results").iterdir()
    saved = (first / "summary.json").read_bytes()
    cli.main()
    assert len(list((tmp_path / "results").iterdir())) == 2
    assert (first / "summary.json").read_bytes() == saved
    assert "Compact results: results/" in capsys.readouterr().out
