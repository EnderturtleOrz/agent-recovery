"""Paired observable divergence, not an inferred causal graph or LLM judge."""

import json
from math import ceil
from pathlib import Path
from statistics import mean, median

STAGES = ("researcher", "planner", "executor")


def read_events(run: Path) -> list[dict]:
    path = run / "trace.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def paired_metrics(clean: Path, faulty: Path, injected_stage: str) -> dict:
    def outputs(path):
        return {
            e["artifact"]["stage"]: e["artifact"]["payload"]
            for e in read_events(path)
            if e["event"] == "artifact_created" and e["attempt"] == 0
        }

    clean_summary = json.loads((clean / "summary.json").read_text())
    faulty_summary = json.loads((faulty / "summary.json").read_text())
    baseline, changed = outputs(clean), outputs(faulty)
    downstream = STAGES[STAGES.index(injected_stage) + 1 :]
    affected = [
        s for s in downstream if s in baseline and s in changed and baseline[s] != changed[s]
    ]
    consumed = faulty_summary["injected_result_consumed"]
    eligible = bool(
        clean_summary["final_correct"] and faulty_summary["fault_injected"] and consumed
    )
    return {
        "clean_correct": bool(clean_summary["final_correct"]),
        "propagation_eligible": eligible,
        "downstream_output_divergence": bool(affected),
        "affected_stages": affected,
        "affected_stage_count": len(affected),
        "propagated_task_failure": (not faulty_summary["initial_correct"]) if eligible else None,
        "consumption": (
            "consumed_with_divergence" if affected else "consumed_without_observed_divergence"
        )
        if consumed
        else "not_consumed_or_missing_output",
    }


def aggregate(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (
            row["fault_kind"],
            row["fault_stage"],
            row["method"],
            row["tracking"],
            row["task_class"],
        )
        groups.setdefault(key, []).append(row)
    result = []
    for (kind, stage, method, tracking, task_class), group in groups.items():
        eligible = [r for r in group if r.get("propagation_eligible")]
        tokens = [
            r["usage"]["input_tokens"] + r["usage"]["output_tokens"]
            if r["usage"]["input_tokens"] is not None and r["usage"]["output_tokens"] is not None
            else None
            for r in group
        ]
        result.append(
            {
                "fault_kind": kind,
                "fault_stage": stage,
                "method": method,
                "tracking": tracking,
                "task_class": task_class,
                "fault_category": group[0]["fault_category"],
                "runs": len(group),
                "failed_runs": sum(r["status"] == "failed" for r in group),
                "task_success_rate": mean(bool(r["final_correct"]) for r in group),
                "unauthorized_attempt_run_rate": mean(
                    r["unauthorized_attempts"] > 0 for r in group
                ),
                "propagation_eligible_runs": len(eligible),
                "downstream_divergence_rate": mean(
                    r["downstream_output_divergence"] for r in eligible
                )
                if eligible
                else None,
                "mean_recomputed_stages": mean(r["recomputed_stages"] for r in group),
                "median_elapsed_seconds": median(r["elapsed_seconds"] for r in group),
                "p95_elapsed_seconds": sorted(r["elapsed_seconds"] for r in group)[
                    ceil(0.95 * len(group)) - 1
                ],
                "propagated_task_failure_rate": mean(r["propagated_task_failure"] for r in eligible)
                if eligible
                else None,
                "mean_affected_stages": mean(r["affected_stage_count"] for r in eligible)
                if eligible
                else None,
                "mean_stage_calls": mean(r["usage"]["stage_calls"] for r in group),
                "mean_model_calls": mean(r["usage"]["model_calls"] for r in group),
                "mean_elapsed_seconds": mean(r["elapsed_seconds"] for r in group),
                "mean_wasted_stage_calls": mean(r["wasted_usage"]["stage_calls"] for r in group),
                "mean_recovery_seconds": mean(
                    r["recovery_seconds"] for r in group if r["recovery_seconds"] is not None
                )
                if any(r["recovery_seconds"] is not None for r in group)
                else None,
                "mean_total_tokens": mean(tokens) if all(t is not None for t in tokens) else None,
                "unknown_token_runs": sum(t is None for t in tokens),
            }
        )
    return result
