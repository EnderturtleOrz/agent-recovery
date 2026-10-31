# Failure Propagation and Recovery in Multi-Agent Systems

CSE 291A · Option 5 · LangGraph + UCSD TritonAI

Phase 1 scaffold: researcher → planner → executor, controlled numeric faults, dependency traces, and full restart. Additional fault types, always-verify evaluation, and selective recovery remain to be implemented.

## Setup

Use Python 3.12. Run commands from the repository root.

```bash
# uv
uv sync --locked --all-extras --python 3.12
source .venv/bin/activate

# Or standard Python + pip
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -e .
```

On Windows PowerShell, use `py -3.12 -m venv .venv` and `.venv\Scripts\Activate.ps1`.
Instead of activating the environment, uv users can prefix the commands below with `uv run --all-extras`.

## Configuration

Copy `.env.example` to `.env` if it does not exist, then fill in:

```dotenv
OPENAI_BASE_URL=https://tritonai-api.ucsd.edu/v1
OPENAI_API_KEY=<your-tritonai-key>
TRITONAI_MODEL=api-glm-5.3-flash
```

The CLI and SDK example load `.env` automatically; existing shell variables take precedence. `.env` is ignored by Git. Run `mas-recovery models` to list models available to your key. See the [UCSD API reference](https://docs.tritonai.ucsd.edu/llm-api/api-reference).

Experiment settings live in `configs/*.toml`:

| Setting | Supported values |
| --- | --- |
| `backend` | `fake` (offline) or `tritonai` |
| `task_file` | Task JSON path, relative to the TOML file |
| `recovery` | `none` or `full_restart` |
| `[fault]` | Optional; `kind = "incorrect_result"`, `stage = "researcher"` or `"planner"`, positive `delta` |

Copy an existing config to create a new experiment. Task quantities, prices, and budgets are defined in `data/tasks/`; monetary values use integer cents.

## Run

```bash
mas-recovery run --config configs/clean.toml       # Offline baseline
mas-recovery run --config configs/incorrect.toml   # Inject a numeric error
mas-recovery run --config configs/restart.toml     # Inject, reset, and restart
mas-recovery run --config configs/tritonai.toml    # Real model calls
python scripts/tritonai_smoke.py                  # Standalone SDK test
```

Each experiment creates `artifacts/<run-id>/` with `manifest.json` (configuration), `trace.jsonl` (events and dependencies), and `summary.json` (correctness and timing). Use `--output <directory>` to change the output root. Check `summary.json` for correctness: an intentionally faulty run can finish with a successful process exit code.

The offline task's correct total is 30 cents. The example fault changes it to 51; full restart restores it to 30. All orders are simulated.

## Directories

Source modules are under `src/mas_recovery/`:

| Directory | Contents |
| --- | --- |
| `core/` | Shared task, artifact, fault, usage, and configuration schemas |
| `agents/` | Fake and TritonAI backends; stage instructions |
| `workflows/` | LangGraph state, nodes, edges, and stage inputs |
| `faults/` | Controlled output mutation |
| `environment/` | Simulated tools, authorization, and environment reset |
| `tracking/` | JSONL events and artifact provenance |
| `recovery/` | Recovery policy interface and full-restart plan |
| `evaluation/` | Independent task-correctness oracle |
| `experiments/` | Configuration loading, run execution, and result files |

`cli.py` provides the command-line entry point. Other repository directories:

| Directory | Contents |
| --- | --- |
| `configs/` | Runnable experiment configurations |
| `data/tasks/` | Synthetic task fixtures |
| `scripts/` | Standalone TritonAI SDK test |
| `tests/` | Unit tests and offline LangGraph integration tests |
| `docs/` | [Architecture](docs/architecture.md) and [experiment protocol](docs/experiment-protocol.md) |
| `artifacts/` | Generated local results; ignored by Git |
| `.github/workflows/` | Offline CI using uv and dependency caching; no API key required |

## Development

```bash
python -m pytest
ruff check .
ruff format --check .
```

After editing dependencies in `pyproject.toml`, update and commit both dependency snapshots:

```bash
uv lock
uv export --locked --all-extras --no-hashes --no-emit-project --output-file requirements.txt
```

`uv.lock` supports uv installs; the generated `requirements.txt` supports pip. Do not edit the export manually.
