import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from mas_recovery.agents.backend import FakeBackend
from mas_recovery.agents.tritonai import TritonAIBackend, make_client
from mas_recovery.experiments.runner import load_config, run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-agent failure propagation experiments")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, default=Path("artifacts"))
    commands.add_parser("models", help="List TritonAI model IDs accessible to your key")
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env", override=False)
    if args.command == "models":
        with make_client() as client:
            response = client.get("models")
            response.raise_for_status()
            for model in response.json()["data"]:
                print(model["id"])
        return
    config, task = load_config(args.config)
    if config.backend == "fake":
        result = run_experiment(config, task, FakeBackend(), args.output)
    else:
        model = os.environ.get("TRITONAI_MODEL")
        if not model:
            parser.error(
                "Set TRITONAI_MODEL to an accessible model ID (see `mas-recovery models`)."
            )
        with make_client() as client:
            result = run_experiment(
                config, task, TritonAIBackend(client, model), args.output, model
            )
    print(result)
