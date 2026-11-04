"""Admission pacing does not inflate workflow timing or retry quota failures."""

import json
import sys

import pytest

from scripts import run_phase1


@pytest.mark.parametrize("quota_error", [False, True])
def test_pacing_is_outside_workflows_and_stops_after_journaling(monkeypatch, tmp_path, quota_error):
    suite = tmp_path / "artifacts/suite-test"
    compact = tmp_path / "results" / suite.name
    compact.mkdir(parents=True)
    clock = [0.0]
    calls, recorded = [], []

    def sleep(seconds):
        clock[0] += seconds

    def original(*args, **kwargs):
        path = suite / "runs" / str(len(calls))
        path.mkdir(parents=True)
        row = {
            "status": "failed" if quota_error else "completed",
            "usage": {"model_calls": 3},
            "elapsed_seconds": 1.0,
        }
        if quota_error:
            row["error_type"] = "HTTPStatusError"
        (path / "summary.json").write_text(json.dumps(row))
        (path / "trace.jsonl").write_text(json.dumps({"model_record": {"status_code": 429}}) + "\n")
        clock[0] += 1.0
        calls.append(path)
        return path

    def suite_run(*args, **kwargs):
        for _ in range(2):
            path = run_phase1.suite_module.run_experiment()
            recorded.append(path)  # Same result-before-next-admission ordering as the suite.
        return suite

    monkeypatch.setattr(run_phase1.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(run_phase1.time, "sleep", sleep)
    monkeypatch.setattr(run_phase1.suite_module, "run_experiment", original)
    monkeypatch.setattr(run_phase1.suite_module, "run_suite", suite_run)
    root = tmp_path / "tasks.json"
    root.write_text('[{"id":"x","quantity":1,"unit_price":1,"budget":2}]')
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_phase1",
            "--backend",
            "fake",
            "--tasks",
            str(root),
            "--results-output",
            str(tmp_path / "results"),
        ],
    )
    if quota_error:
        with pytest.raises(RuntimeError, match="Stopped after HTTP 429"):
            run_phase1.main()
        assert len(calls) == len(recorded) == 1
    else:
        run_phase1.main()
        assert len(calls) == len(recorded) == 2
        assert clock[0] == pytest.approx(4.6)
        assert all(
            json.loads((path / "summary.json").read_text())["elapsed_seconds"] == 1.0
            for path in calls
        )
    assert run_phase1.suite_module.run_experiment is original
    metadata = json.loads((compact / "execution.json").read_text())
    assert metadata["total_admission_wait_seconds"] == pytest.approx(0 if quota_error else 2.6)
    assert metadata["infrastructure_stop_http_status"] == (429 if quota_error else None)


def test_quota_rejection_on_final_row_marks_both_manifests_failed(monkeypatch, tmp_path):
    suite = tmp_path / "artifacts/suite-final"
    compact = tmp_path / "results" / suite.name
    for directory in (suite, compact):
        directory.mkdir(parents=True)
        (directory / "suite-manifest.json").write_text('{"status":"completed","runs":1}')
    taskfile = tmp_path / "tasks.json"
    taskfile.write_text('[{"id":"x","quantity":1,"unit_price":1,"budget":2}]')

    def original(*args, **kwargs):
        path = suite / "runs/last"
        path.mkdir(parents=True)
        (path / "summary.json").write_text(
            json.dumps(
                {"status": "failed", "error_type": "HTTPStatusError", "usage": {"model_calls": 1}}
            )
        )
        (path / "trace.jsonl").write_text('{"model_record":{"status_code":429}}\n')
        return path

    def suite_run(*args, **kwargs):
        run_phase1.suite_module.run_experiment()
        return suite

    monkeypatch.setattr(run_phase1.suite_module, "run_experiment", original)
    monkeypatch.setattr(run_phase1.suite_module, "run_suite", suite_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_phase1",
            "--backend",
            "fake",
            "--tasks",
            str(taskfile),
            "--results-output",
            str(tmp_path / "results"),
        ],
    )
    with pytest.raises(RuntimeError, match="Final run received HTTP 429"):
        run_phase1.main()
    for directory in (suite, compact):
        assert json.loads((directory / "suite-manifest.json").read_text())["status"] == "failed"
    assert (
        json.loads((compact / "execution.json").read_text())["infrastructure_stop_http_status"]
        == 429
    )


def test_interrupt_before_first_result_still_archives_execution_metadata(monkeypatch, tmp_path):
    suite = tmp_path / "artifacts/suite-first-interrupt"
    compact = tmp_path / "results" / suite.name
    compact.mkdir(parents=True)
    taskfile = tmp_path / "tasks.json"
    taskfile.write_text('[{"id":"x","quantity":1,"unit_price":1,"budget":2}]')

    def suite_run(*args, **kwargs):
        error = KeyboardInterrupt()
        error.suite_dir = suite
        raise error

    monkeypatch.setattr(run_phase1.suite_module, "run_suite", suite_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_phase1",
            "--backend",
            "fake",
            "--tasks",
            str(taskfile),
            "--results-output",
            str(tmp_path / "results"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        run_phase1.main()
    assert error.value.code == 130
    assert (compact / "execution.json").is_file()
    assert (compact / "source-snapshot.json").is_file()
    assert json.loads((compact / "execution.json").read_text())["total_admission_wait_seconds"] == 0
