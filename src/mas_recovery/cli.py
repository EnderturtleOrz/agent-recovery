"""Command line for single runs, seeded datasets, and paired suites."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from mas_recovery.agents.backend import FakeBackend
from mas_recovery.agents.tritonai import TritonAIBackend, make_client
from mas_recovery.core.schemas import Task
from mas_recovery.experiments.dataset import generate_tasks
from mas_recovery.experiments.runner import load_config, run_experiment
from mas_recovery.experiments.suite import run_suite


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-agent failure propagation experiments")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, default=Path("artifacts"))
    run.add_argument(
        "--backend",
        choices=("fake", "tritonai"),
        help="Override the config backend without editing the TOML file",
    )
    commands.add_parser("models", help="List model IDs accessible to your key")
    generate = commands.add_parser("generate", help="Write seeded synthetic task set")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--count", type=int, default=6)
    generate.add_argument("--seed", type=int, default=291)
    suite = commands.add_parser("suite", help="Run the paired Phase 1 matrix")
    suite.add_argument("--tasks", type=Path, default=Path("data/tasks/purchase-suite.json"))
    suite.add_argument("--backend", choices=("fake", "tritonai"), default="fake")
    suite.add_argument("--repeats", type=int, default=1)
    suite.add_argument("--output", type=Path, default=Path("artifacts"))
    suite.add_argument("--overhead", action="store_true")
    suite.add_argument("--max-calls", type=int, default=12)
    suite.add_argument("--max-seconds", type=float, default=120)
    suite.add_argument("--max-total-tokens", type=int)
    suite.add_argument("--max-output-tokens", type=int, default=2048)
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env", override=False)
    if args.command == "generate":
        tasks = generate_tasks(args.count, args.seed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(json.dumps([t.model_dump() for t in tasks], indent=2) + "\n")
        print(args.output)
        return
    if args.command == "models":
        with make_client() as client:
            response = client.get("models")
            response.raise_for_status()
            for model in response.json()["data"]:
                print(model["id"])
        return
    if args.command == "run":
        config, task = load_config(args.config)
        if args.backend is not None:
            config = config.model_copy(update={"backend": args.backend})
        backend_name = config.backend
    else:
        tasks = [Task.model_validate(t) for t in json.loads(args.tasks.read_text())]
        backend_name = args.backend

    def execute(backend, model=None):
        if args.command == "run":
            if model is None:
                return run_experiment(config, task, backend, args.output)
            return run_experiment(config, task, backend, args.output, model)
        return run_suite(
            tasks,
            backend,
            args.output,
            backend_name=backend_name,
            model=model or "deterministic-fake",
            repeats=args.repeats,
            overhead=args.overhead,
            max_calls=args.max_calls,
            max_seconds=args.max_seconds,
            max_total_tokens=args.max_total_tokens,
            max_output_tokens=args.max_output_tokens,
        )

    try:
        if backend_name == "fake":
            result = execute(FakeBackend())
        else:
            model = os.environ.get("TRITONAI_MODEL")
            if not model:
                parser.error(
                    "Set TRITONAI_MODEL to an accessible model ID (see mas-recovery models)."
                )
            with make_client() as client:
                result = execute(TritonAIBackend(client, model), model)
    except KeyboardInterrupt as error:
        path = getattr(error, "suite_dir", getattr(error, "run_dir", None))
        if path is not None:
            print(f"Interrupted; partial results: {path}", file=sys.stderr)
        raise SystemExit(130) from None
    print(result)
