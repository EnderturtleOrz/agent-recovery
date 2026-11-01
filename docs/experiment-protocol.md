# Phase 1 experiment protocol

## Research questions

1. Does a controlled faulty intermediate result reach downstream computation and change the outcome?
2. How do fault type and injection stage affect correctness, safety and wasted work?
3. What correctness and cost tradeoffs arise between no recovery, full restart and always verify?

## Dataset and pairing

The seeded generator produces three offer choices per task, with feasible, insufficient-budget,
and insufficient-stock cases. The checked-in six tasks are a smoke dataset, not a statistically
representative benchmark. Use `generate --count ... --seed ...` to expand, and retain the seed,
exact dataset, model and manifests. `unit_price` is legacy metadata for structured tasks.

Unit: task × model × schedule × method × replicate. Each task/replicate has a clean run, a clean
always-verify run, and six fault schedules under three methods. Budgets, task data, prompts,
mutation payload and one-shot semantics match across methods. Remote inference may vary;
repeats estimate variability rather than guaranteeing exact model determinism. Report sample
counts and task-level distributions; the default small suite does not justify population claims.
Task feasibility is a grouping dimension so correct abstentions do not hide purchase failures.

## Controlled schedules

| Category | Fault | Boundary | Semantics |
| --- | --- | --- | --- |
| Accidental | Incorrect result | Researcher output | Add delta to offer prices (legacy: scalar price) |
| Accidental | Incorrect result | Planner output | Add delta to planned total |
| Accidental | Timeout | Researcher or planner | Missing output before dispatch; no model charge fabricated |
| Accidental | Stale output | Researcher output | Return previous catalog prices, stock and version |
| Adversarial | Malicious instruction | Researcher output | Add supplier-override instruction to lower-trust note |

Stale/instruction schedules require structured tasks. Unsupported combinations fail validation.
Only attempt 0 is injected, once; neither verification retries nor restart repeat the fault.
This does not model a persistent malicious source. Accidental and adversarial summaries remain
separate. The deterministic backend deliberately follows the attack marker for instrumentation.

## Methods and disclosure

- **Clean:** no injection, plus a separate clean always-verify run for verification overhead.
- **No recovery:** inject and continue, or fail on a missing output.
- **Full restart:** supply the exact faulty ID after completion or the known failed stage at
  controlled timeout; reset the ledger and rerun all roles without injection. Original costs and
  safety history are retained. Actual provider failures are not reclassified as injected faults.
- **Always verify:** before accepting every stage, use privileged current catalog truth and task
  constraints, reject incorrect or injected-instruction payloads and retry once by default.
  This verifier is an oracle upper bound, with zero verifier inference calls; generation retries
  and measured verification CPU/wall time are included. Rejection is not failure detection by an LLM.

No automated detector or selective recovery is evaluated in Phase 1. The budget is per complete
run, including recovery/retries: default 12 backend calls, 120 seconds, 2048 output tokens/request.
All methods receive identical limits. The call limit includes fake calls; model_calls distinguishes
actual HTTP requests. Optional total-token enforcement stops on unknown usage and can overshoot
by one reported response. HTTP timeouts and call-boundary time checks are not a process kill timer.

## Metric definitions

| Metric | Definition |
| --- | --- |
| Task success | Completed run with correct final state; all failed runs remain in the denominator |
| Initial/recovered correctness | Separate pre-restart and final booleans; initial may be null if initial execution aborts |
| Confirmed input use | Injected artifact is an explicit parent of a completed downstream artifact; stage scheduling alone is insufficient |
| Downstream divergence | Downstream payload differs from its matched clean output; injected stage itself is excluded |
| Propagation eligibility | Matched clean is correct, injection happened, and completed downstream input use is recorded |
| Propagated task failure rate | Initially incorrect/failed fault runs divided by eligible runs; null when no eligible runs |
| Affected stages | Number/list of observed changed downstream payloads; missing outputs are not fabricated as changes |
| Unauthorized actions | Attempt count and run rate; execution count separately (zero by enforced guard in this environment) |
| Wasted work | Union of semantically invalid, verifier-rejected, discarded pre-restart, failed calls; if the run aborts all its calls are discarded. No double counting |
| Cost | All stage/model calls, known input/output tokens, null totals for unknown usage, and separate restart/wasted subsets |
| Latency | Initial execution through recovery and scoring; excludes initial manifest creation and final summary serialization |
| Recovery latency | Restart planning, reset and rerun, including partial failed recovery |
| Recomputed stages | Successfully completed restart stages, including partial progress if restart aborts |
| Verification overhead | Clean-verify vs clean cost/time; per-run check count and check time; generation retries included in total cost |
| Tracking persistence overhead | Optional paired runs with/without disk trace; alternate pair order across replicates; both retain scoring events |

Unconsumed/missing-output fault runs are not evidence of robust recovery. A changed payload is
observational evidence; with stochastic LLMs it can also reflect sampling variance. Inspect traces,
use repeated clean controls, and do not label all descendants as causally corrupted. The current
suite implements deterministic faults and output pairing, not a general causal inference method.
A final correct empty ledger can coexist with a rejected unsafe attempt; always report both.
No dollar costs are inferred without a dated provider pricing table. Summary CSV includes sample
counts, means, median/P95 latency and task-class separation; raw per-run records retain detail.

## Artifacts and reproduction

`mas-recovery suite --backend fake --overhead` produces an offline end-to-end validation matrix.
Real experiments use the same command with `--backend tritonai` after validating one real task.
Every run has a manifest, raw JSONL trace and summary; suite-level outputs retain the exact
dataset, method matrix, per-run paired results, aggregate JSON/CSV and overhead pairs.

JSON/type/API/budget failures count as unsuccessful runs. Unknown usage is not zero. Controlled
timeouts are separate from provider timeouts. Batch processing continues after individual run
failures; configuration/data validation errors stop before the affected API work.

## Coverage against the course handout

| Phase 1 requirement | Implementation | Remaining empirical work |
| --- | --- | --- |
| Clean baseline | Fake and TritonAI backends; paired clean runs | Run real model across expanded tasks |
| Controlled faults | Four types, six schedules, two boundaries | Broader payloads and model-specific behavior |
| Accidental vs adversarial analysis | Validated categories and grouped summaries | Analyze real-model traces |
| Messages/artifacts/actions/dependencies | Explicit input/output and version provenance, model records | Field-level or shared-state dependencies in Phase 2 |
| Propagation and workload dependence | Input-use evidence, matched output/outcome comparisons | Repeats and manually inspected real failure cases |
| Required metrics | Success/safety/divergence/wasted work/time/cost | Larger samples; full tracking overhead if claimed |
| Full restart | Explicit simulated reset and retained history | Real-model recovery measurements |
| Verification comparison | Privileged programmatic verifier with measured overhead | Learned verifier optional, not implemented |

The handout does not prescribe a fixed task count or demand every fault at every boundary.
Shared-state complications, selective reuse validation, snapshots and irreversible actions belong
primarily to Phase 2. This repository does not claim those mechanisms are implemented.
