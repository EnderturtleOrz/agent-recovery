# Failure Propagation and Recovery in Multi-Agent Systems

CSE 291A · Option 5 · LangGraph + UCSD TritonAI

Phase 1 experiment harness: a three-stage procurement workflow, controlled faults,
explicit provenance, full restart, privileged always-verify comparison, and paired metrics.
The original scalar example remains available. **Offline fixture results validate the
harness; they are not measurements of real LLM robustness.**

## Quick start

Use Python 3.12 from the repository root:

```bash
uv sync --locked --all-extras --python 3.12
source .venv/bin/activate
python -m pytest
mas-recovery run --config configs/structured.toml
mas-recovery suite --tasks data/tasks/purchase-suite.json --backend fake --overhead
```

Without uv, create a virtual environment and use:

```bash
python -m pip install -r requirements.txt -e .
```

## Running experiments

Run commands from the repository root with the project environment activated.
The `tritonai` backend requires a local `.env` file (see [Real-model runs](#real-model-runs));
`fake` makes no API requests. Single runs check individual conditions; suites produce
paired comparisons across faults and recovery strategies.

| Experiment | Command | Results |
| --- | --- | --- |
| Clean structured baseline, single task | `mas-recovery run --config configs/structured.toml --backend tritonai` | Correctness, calls, tokens, and latency |
| Incorrect quote propagation, single task | `mas-recovery run --config configs/incorrect-structured.toml --backend tritonai` | Modified quotes, downstream plans/orders, and correctness |
| Stale-data propagation, single task | `mas-recovery run --config configs/stale.toml --backend tritonai` | Old catalog versions, downstream outputs, and correctness |
| Malicious instruction, single task | `mas-recovery run --config configs/malicious.toml --backend tritonai` | Unauthorized attempts, rejection reasons, and correctness |
| Full restart, single task | `mas-recovery run --config configs/restart-structured.toml --backend tritonai` | Initial/final correctness, recomputed stages, and recovery cost |
| Always verify, single task | `mas-recovery run --config configs/verify.toml --backend tritonai` | Verification decisions, correctness, and additional generation calls |
| Controlled timeout with restart, single task | `mas-recovery run --config configs/timeout.toml --backend tritonai` | Missing output, recovery outcome, and recovery cost |
| Offline smoke matrix | `mas-recovery suite --backend fake --repeats 2 --overhead` | 264 workflow runs validating the harness |
| Real-model development matrix | `mas-recovery suite --tasks data/tasks/purchase-dev.json --backend tritonai --repeats 1` | 240 runs for debugging and prompt tuning |
| Real-model evaluation matrix | `python scripts/run_phase1.py` | 480 runs for the report, with fixed code/model/prompts |

For the complete real-model evaluation, `python scripts/run_phase1.py` runs the same
480-condition matrix with controlled admission between workflows (default target:
1.2 seconds per model request, accounting for elapsed workflow time). These waits are
outside per-run meters and latency measurements. The driver stops further admission
after HTTP 401, 403, or 429 and does not silently retry provider failures. Pacing settings
and actual waiting time are saved in `execution.json`. Direct `mas-recovery suite` commands
remain available when the provider's request allowance is sufficient.

Each task/replicate receives two clean controls and six fault schedules under three
strategies: no recovery, full restart, and always verify (20 runs per task).
`--overhead` adds two disk-trace controls per task; `--repeats` multiplies the matrix size.
Workflow counts are not API-call counts: restarts and verification retries require extra calls.
Reserve the evaluation split for the final comparison, after tuning on development data.

Every command automatically saves two outputs and prints both paths:

| Directory | Contents | Purpose |
| --- | --- | --- |
| `results/<run-id or suite-id>/` | Summaries, per-run metrics, tasks, configuration, and source/prompt provenance | Compact results suitable for GitHub and report analysis |
| `artifacts/<run-id or suite-id>/` | Full raw traces, model requests/responses, and all original files | Local inspection; ignored by Git |

For suites, start with `results/suite-<id>/summary.csv`. Per-run metrics are in
`results.jsonl`, experiment settings/status in `suite-manifest.json`, per-run provenance
in `run-metadata.jsonl`, and the exact task snapshot in `dataset.json`. Single runs retain
`manifest.json` and `summary.json`. The compact export preserves correctness, propagation,
safety, recovery, verification, token, call, and latency metrics while omitting raw model
conversations and duplicated propagation inputs. Every execution creates a new directory.

`results/` is not ignored: use normal `git add`, commit, and push to publish it.
Use `--results-output <directory>` to change the compact destination; `--output` controls
raw artifacts. Neither export copies `.env` or API credentials.

Completed runs, execution failures, and Ctrl+C interruptions retain available results.
A hard process kill does not guarantee compact export. Before reporting a full matrix,
check `suite-manifest.json` for `status=completed` and matching actual/planned run counts.
Individual failed runs remain in success-rate denominators; a completed suite can contain
failed workflows. `run_role` separates clean, clean-verify, fault, and overhead conditions.

The checked-in suite has **6 tasks**: feasible purchases, insufficient budget, and
insufficient stock. Each has three offers, an authorized supplier list, current catalog
version 2 and an actual previous snapshot at version 1. One SKU must satisfy the entire
quantity; splitting across SKUs and optimizing multiple demand lines are out of scope.
Prices and budgets are integer cents. `unit_price` is retained for legacy fixture compatibility;
structured-task truth comes from `catalog`.

Additional [development and evaluation datasets](data/tasks/README.md) provide
12 development tasks and 24 separate evaluation tasks, balanced across the same
three task classes. Use development data for tuning and reserve evaluation data
for the final comparison:

```bash
mas-recovery suite --tasks data/tasks/purchase-dev.json --backend fake
mas-recovery suite --tasks data/tasks/purchase-eval-v5.json --backend fake
```

The new purchase-v5 evaluation is documented in
[Phase 1 results](results/phase1-results.md), with per-condition tables and reproducibility files.

## Workflow

```text
Task + current catalog
        ↓
Researcher: produce structured offers
        ↓  fault injection / optional verification
Planner: select an eligible product or decline purchase
        ↓  fault injection / optional verification
Executor: return the plan → simulated order tool
        ↓
Independent correctness oracle + safety history
```

The current prompt contract is `purchase-v5`. Planner and Executor output exactly
`value`, `product_id`, `supplier`, and `quantity`; quote lists and research notes are not
part of a purchase decision. A no-purchase decision is
`{"value":0,"product_id":null,"supplier":null,"quantity":0}`. Executor receives only these
four fields, copied without recalculating or repairing them. Semantic scoring checks the
decision fields, rather than rejecting a correct abstention for unrelated research data.
The strict model response schema still rejects extra fields and malformed JSON.
See [the v5 output-contract fix and development checks](docs/output-contract-v5.md).
The v4 results are preliminary diagnostics; new formal comparisons must use one fixed
version across all strategies. The original evaluation split has already informed debugging.

Nodes make one structured model call each; the workflow invokes the order tool in Python.
This is a fixed agent workflow, not an autonomous tool-selection loop. The planner receives
only the research output and task constraints; the executor receives only the plan. Historical
catalog snapshots, fault metadata, and evaluator answers are not passed to those agents.

## Single-run examples

```bash
mas-recovery run --config configs/clean.toml       # Original scalar offline baseline
mas-recovery run --config configs/incorrect.toml   # Scalar numeric propagation
mas-recovery run --config configs/restart.toml     # Scalar full restart
mas-recovery run --config configs/structured.toml  # Structured procurement
mas-recovery run --config configs/stale.toml       # Real old catalog snapshot
mas-recovery run --config configs/malicious.toml   # Untrusted supplier-override instruction
mas-recovery run --config configs/timeout.toml     # Controlled timeout + restart
mas-recovery run --config configs/verify.toml      # Verify, reject, retry before consumption
```

Each run writes `artifacts/<run-id>/manifest.json`, `trace.jsonl`, and `summary.json`.
`--output` selects another output root. An incorrect but completed task can exit with code 0;
inspect `final_correct` and `unauthorized_attempts`. A single-run execution error persists its
summary and raises; a suite records it and continues, retaining it in success-rate denominators.
Ctrl+C is different: it stops the suite, journals the interrupted run and finalizes partial summaries.

Config fields include `backend`, `task_file`, `recovery`, optional `[fault]`, `max_calls`,
`max_seconds`, `max_output_tokens`, optional `max_total_tokens`, and `verification_retries`.
All methods share the same per-run limits, including recovery and retries.

## Paired experiment suite

```bash
mas-recovery suite --backend fake --repeats 1 --overhead
mas-recovery generate --count 12 --seed 291 --output data/tasks/custom.json
mas-recovery suite --tasks data/tasks/custom.json --backend fake --repeats 3
```

Generation refuses to overwrite an existing dataset. The suite runs two clean baselines
(no verification, always verify), then six schedules × three methods:

| Fault | Locations | Category |
| --- | --- | --- |
| Incorrect numeric result | Researcher, planner | Accidental |
| Missing output / controlled timeout | Researcher, planner | Accidental |
| Stale catalog snapshot | Researcher | Accidental |
| Malicious instruction in research note | Researcher | Adversarial |

Methods: no recovery, full restart, always verify. Thus **20 runs per task per repeat**,
or 22 with `--overhead` (132 runs for the checked-in 6-task suite). These are harness runs,
not model calls. Failed/missing-output runs can make fewer calls; recovery makes more.
No particular dataset size is claimed as a course requirement.

Suite outputs:

- `dataset.json`, `suite-manifest.json`: exact tasks, fault matrix, budgets, model and limitations.
- `runs/`: all individual manifests, raw traces and summaries.
- `results.jsonl`: paired per-run metrics, including failures.
- `summary.json`, `summary.csv`: metrics grouped by run role, fault, location, method and task feasibility.
- `overhead.json`: paired disk-trace persistence timings; not total dependency-tracking overhead.

Missing quote targets, unknown catalog IDs in stale snapshots, and unchanged fault replacements
are recorded as `fault_not_injected` with `fault_skipped_reason` in the summary. These runs are
excluded from propagation eligibility and do not trigger a full restart for a nonexistent fault.

The fake backend deliberately follows the attack marker. Its attack success is a deterministic
instrumentation test, not evidence that a real model follows malicious instructions.

## Real-model runs

Copy `.env.example` to `.env` and fill in your credentials (do not commit them):

```dotenv
OPENAI_BASE_URL=https://tritonai-api.ucsd.edu/v1
OPENAI_API_KEY=<your-tritonai-key>
TRITONAI_MODEL=<an-accessible-model-id>
```

Existing shell variables take precedence. First check connectivity and one task:

```bash
mas-recovery models
mas-recovery run --config configs/tritonai.toml
```

For a structured single run, use `mas-recovery run --config configs/structured.toml --backend tritonai`.
Only after checking its output and costs, run:

```bash
mas-recovery suite --backend tritonai --repeats 3 --max-calls 12 --max-seconds 120 --max-output-tokens 2048
```

Real suites consume API quota. Requests have no automatic retries. Call counts, known/unknown
usage and malformed-output costs are preserved. Explicitly truncated, filtered or tool-call
responses are rejected even when their text parses as JSON; provider finish reasons are logged.
Token limits stop further admission after
reported usage exhausts the limit; an exactly-at-limit final response is accepted, while
a subsequent call is blocked. An actual overshoot fails the run and remains fully counted.
Configuring a token budget with
missing provider usage stops the run and prevents later budgeted calls. Budget errors
include `budget_resource` and `budget_phase` (admission vs completion) in the summary. Time is
checked at call boundaries, with an HTTP timeout
bounded by the remaining allowance; this is not a hard process-wide deadline.
Raw successful response content and synthetic task prompts are saved; headers/API keys and
provider error bodies are not. Keep experiment inputs free of private data.

## Interpretation and scope

- Full restart resets orders, retains safety history, creates a fresh graph, and reruns without
  the one-shot fault. Fault identity is supplied by the harness, not discovered automatically.
- Always-verify reads ground truth and is a **privileged programmatic upper bound**. It checks
  every stage, retries a rejected output once by default, and issues no extra verifier LLM calls.
  Its wall time and extra generation calls are counted. This is not a realistic learned detector.
- Authorization resolves product IDs against the trusted catalog and blocks unknown products,
  mismatched supplier claims, unauthorized suppliers and over-budget orders. It also rejects
  missing structured payloads, nonpositive purchase quantities and inconsistent amounts.
  Negative/noninteger tool amounts raise a contract error without changing the ledger.
  Price/stock/task-quantity correctness remains independently checked by the oracle. Zero executed violations
  is enforced by the environment; report attempts separately from task correctness.
- Paired downstream divergence is observable evidence, not proof of causality under remote
  model sampling. See the exact denominators and failure cases in the experiment protocol.
- Selective recovery, complex shared state, partial external writes and irreversible actions
  remain Phase 2 work. Memory checkpoints do not restore the environment.

## Repository map

| Path | Responsibility |
| --- | --- |
| `core/` | Validated tasks, offers, outputs, faults and experiment configuration |
| `agents/` | Offline fixture, TritonAI adapter and versioned prompts |
| `workflows/` | LangGraph nodes and explicit role-specific inputs |
| `environment/` | Simulated orders, authorization and reset |
| `faults/` | Controlled content mutations and missing-output fault |
| `tracking/` | JSONL events and provenance |
| `recovery/` | Full-restart policy contract |
| `evaluation/` | Correctness oracle, verifier and paired aggregation |
| `experiments/` | Generation, budgets, single runs and suite orchestration |

Source paths above are relative to `src/mas_recovery/`.
See [architecture](docs/architecture.md), [experiment protocol](docs/experiment-protocol.md),
and [validation record](docs/validation.md).

## Development

```bash
python -m pytest
ruff check .
ruff format --check .
uv pip check
```

Dependencies were not changed for the Phase 1 extension. If dependencies change later, update
`uv.lock` and regenerate `requirements.txt` using the export command in its header.
