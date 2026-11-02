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

## 怎么跑实验

在仓库根目录、激活环境后运行。`tritonai` 需要先配置 `.env`（见 [API 配置](#real-model-runs)）；
`fake` 不调用 API。单次实验用于检查流程，完整实验组用于汇总比较。

| 实验内容 | 指令 | 可获得结果 |
| --- | --- | --- |
| 正常基线（结构化采购，单次） | `mas-recovery run --config configs/structured.toml --backend tritonai` | 正确性、调用次数、token 和耗时 |
| 错误报价传播（单次） | `mas-recovery run --config configs/incorrect-structured.toml --backend tritonai` | 被修改的报价、下游计划与订单、最终正确性 |
| 过期数据传播（单次） | `mas-recovery run --config configs/stale.toml --backend tritonai` | 旧数据版本、下游输出和最终正确性 |
| 恶意指令传播（单次） | `mas-recovery run --config configs/malicious.toml --backend tritonai` | 越权尝试、拦截原因和最终正确性 |
| 完整重启（单次） | `mas-recovery run --config configs/restart-structured.toml --backend tritonai` | 恢复前后正确性、重跑阶段数和恢复成本 |
| 逐阶段验证（单次） | `mas-recovery run --config configs/verify.toml --backend tritonai` | 验证记录、最终正确性和额外调用开销 |
| 超时后重启（单次） | `mas-recovery run --config configs/timeout.toml --backend tritonai` | 缺失输出、恢复结果和恢复成本 |
| 完整离线实验组 | `mas-recovery suite --backend fake --repeats 2 --overhead` | 264 次运行；检查实验框架，生成汇总表和日志 |
| 完整真实模型实验组 | `mas-recovery suite --backend tritonai --repeats 3 --overhead` | 396 次运行；比较各故障与策略的成功率、传播、安全性、成本和耗时 |

单次结果在终端打印的 `artifacts/<run-id>/` 中，主要看 `summary.json` 和 `trace.jsonl`。
整组结果在 `artifacts/suite-<id>/` 中，主要看 `summary.csv`；逐次结果见 `results.jsonl`，
原始日志见 `runs/`。汇总中的 `run_role` 区分正常基线、验证基线、故障实验和日志开销实验。

运行次数基于默认 6 个任务；真实实验消耗 API 配额，工作流次数不等于模型调用次数。
中途按 Ctrl+C 会停止后续运行，并保存已完成结果和当前中断记录；CLI 会打印部分结果目录。
`summary.csv` 中的中断实验是部分结果，不应当作完整矩阵；可检查 manifest 的 `status` 和 `planned_runs`。

The checked-in suite has **6 tasks**: feasible purchases, insufficient budget, and
insufficient stock. Each has three offers, an authorized supplier list, current catalog
version 2 and an actual previous snapshot at version 1. One SKU must satisfy the entire
quantity; splitting across SKUs and optimizing multiple demand lines are out of scope.
Prices and budgets are integer cents. `unit_price` is retained for legacy fixture compatibility;
structured-task truth comes from `catalog`.

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
