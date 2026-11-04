"""A fresh offline matrix must support report creation without hand-copied files."""

import hashlib
import json
import re
import sys
from pathlib import Path

from scripts import analyze_phase1, run_phase1


def test_fresh_evaluation_exports_provenance_and_regenerates_report(monkeypatch, tmp_path):
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_phase1",
            "--backend",
            "fake",
            "--tasks",
            str(repo / "data/tasks/purchase-eval-v5.json"),
            "--output",
            str(tmp_path / "artifacts"),
            "--results-output",
            str(tmp_path / "results"),
        ],
    )
    run_phase1.main()
    (suite,) = (tmp_path / "results").iterdir()
    assert (suite / "source-snapshot.json").is_file()
    assert json.loads((suite / "dataset-origin.json").read_text())["seed"] == 29108
    raw = tmp_path / "artifacts" / suite.name
    monkeypatch.setattr(sys, "argv", ["analyze", "--suite", str(suite), "--raw", str(raw)])
    analyze_phase1.main()
    report = tmp_path / "results/phase1-results.md"
    content = report.read_text()
    assert "An earlier entire attempt was interrupted" not in content
    assert "### Infrastructure restart" not in content
    assert all((report.parent / link).is_file() for link in re.findall(r"\]\(([^)]+)\)", content))
    before = hashlib.sha256(report.read_bytes()).hexdigest()
    monkeypatch.setattr(sys, "argv", ["analyze", "--suite", str(suite)])
    analyze_phase1.main()
    validation = json.loads((suite / "validation.json").read_text())
    assert before == validation["report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert (
        validation["analysis_script_sha256"]
        == hashlib.sha256((suite / "analysis-code.py").read_bytes()).hexdigest()
    )
    assert json.loads((suite / "audit.json").read_text())["passed"]
