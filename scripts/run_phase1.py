"""Run the complete v5 matrix with API pacing outside measured workflows.

No model call is silently retried. Stop after an authentication/quota rejection;
individual run records, including that rejection, remain in the stopped attempt.
"""

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from dotenv import load_dotenv

from mas_recovery.agents.backend import FakeBackend
from mas_recovery.agents.tritonai import PROMPT_VERSION, TritonAIBackend, make_client
from mas_recovery.core.schemas import Task
from mas_recovery.experiments import suite as suite_module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=Path("data/tasks/purchase-eval-v5.json"))
    parser.add_argument("--backend", choices=("fake", "tritonai"), default="tritonai")
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--results-output", type=Path, default=Path("results"))
    parser.add_argument("--seconds-per-model-call", type=float, default=1.2)
    args = parser.parse_args()
    if not 1.0 <= args.seconds_per_model_call <= 10:
        parser.error("seconds-per-model-call must be between 1 and 10")
    if PROMPT_VERSION != "purchase-v5":
        parser.error("This evaluation driver requires purchase-v5")
    tasks = [Task.model_validate(t) for t in json.loads(args.tasks.read_text())]
    load_dotenv(Path.cwd() / ".env", override=False)
    # Capture provenance before inference; do not snapshot potentially edited code at exit.
    source_root = Path(suite_module.__file__).resolve().parents[1]
    source_files = {
        str(p.relative_to(source_root)): p.read_bytes().decode("utf-8")
        for p in sorted(source_root.rglob("*.py"))
    }
    source_hash = hashlib.sha256()
    for filename, content in source_files.items():
        source_hash.update(filename.encode())
        source_hash.update(content.encode())
    lock = Path("uv.lock")
    lock_bytes = lock.read_bytes() if lock.is_file() else None
    origin = args.tasks.with_name(args.tasks.stem + "-manifest.json")
    origin_bytes = origin.read_bytes() if origin.is_file() else None
    original = suite_module.run_experiment
    next_start = 0.0
    queued_seconds = 0.0
    stop_status = None
    suite_path = None
    recorded = 0

    def paced_run(*run_args, **kwargs):
        nonlocal next_start, queued_seconds, stop_status, suite_path, recorded
        if stop_status is not None:
            raise RuntimeError(f"Stopped after HTTP {stop_status}; no automatic retry")
        delay = max(0.0, next_start - time.monotonic())
        if delay:
            waited = time.monotonic()
            try:
                time.sleep(delay)
            finally:
                queued_seconds += time.monotonic() - waited
        started = time.monotonic()
        path = original(*run_args, **kwargs)
        suite_path = path.parent.parent
        row = json.loads((path / "summary.json").read_text())
        next_start = started + row["usage"]["model_calls"] * args.seconds_per_model_call
        recorded += 1
        if row.get("error_type") == "HTTPStatusError":
            for line in (path / "trace.jsonl").read_text().splitlines():
                event = json.loads(line)
                status = (event.get("model_record") or {}).get("status_code")
                if status in (401, 403, 429):
                    stop_status = status
        if recorded == 1 or recorded % 20 == 0 or stop_status is not None:
            print(
                json.dumps(
                    {
                        "recorded": recorded,
                        "raw_suite": str(suite_path),
                        "last_status": row["status"],
                        "stop_http_status": stop_status,
                    }
                ),
                flush=True,
            )
        # Return before stopping so the suite journals this result before next admission.
        return path

    suite_module.run_experiment = paced_run
    try:
        if args.backend == "fake":
            suite_path = suite_module.run_suite(
                tasks, FakeBackend(), args.output, results_root=args.results_output
            )
        else:
            model = os.environ.get("TRITONAI_MODEL")
            if not model:
                parser.error("Configure TRITONAI_MODEL locally")
            with make_client() as client:
                suite_path = suite_module.run_suite(
                    tasks,
                    TritonAIBackend(client, model),
                    args.output,
                    backend_name="tritonai",
                    model=model,
                    results_root=args.results_output,
                )
        if stop_status is not None:
            # A quota rejection on the very last row must not leave a completed manifest.
            for directory in (suite_path, args.results_output / suite_path.name):
                path = directory / "suite-manifest.json"
                if path.is_file():
                    manifest = json.loads(path.read_text())
                    manifest.update(status="failed", infrastructure_stop_http_status=stop_status)
                    path.write_text(json.dumps(manifest, indent=2) + "\n")
            raise RuntimeError(f"Final run received HTTP {stop_status}")
    except KeyboardInterrupt as error:
        # The first run may be interrupted before paced_run receives its returned path.
        suite_path = getattr(error, "suite_dir", suite_path)
        print(f"Interrupted; partial results: {suite_path}", flush=True)
        raise SystemExit(130) from None
    finally:
        suite_module.run_experiment = original
        if suite_path is not None:
            destination = args.results_output / suite_path.name
            note = dict(
                task_source=str(args.tasks),
                prompt_version=PROMPT_VERSION,
                seconds_per_model_call=args.seconds_per_model_call,
                total_admission_wait_seconds=queued_seconds,
                pacing_location="between workflows, outside per-run meters and latency",
                model_retries="none beyond the configured verification-stage retry",
                infrastructure_stop_http_status=stop_status,
                execution_driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            )
            (destination / "source-snapshot.json").write_text(
                json.dumps(
                    {
                        "root": "src/mas_recovery",
                        "source_sha256": source_hash.hexdigest(),
                        "files": source_files,
                    },
                    indent=2,
                )
                + "\n"
            )
            if lock_bytes is not None:
                (destination / "uv.lock").write_bytes(lock_bytes)
            if origin_bytes is not None:
                (destination / "dataset-origin.json").write_bytes(origin_bytes)
            (destination / "execution.json").write_text(json.dumps(note, indent=2) + "\n")
            shutil.copyfile(__file__, destination / "execution-driver.py")
            print(f"Results: {destination}", flush=True)


if __name__ == "__main__":
    main()
