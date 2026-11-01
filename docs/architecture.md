# Architecture

## Execution boundaries

The CLI loads a single TOML config or a JSON task set. The runner creates an isolated simulated
world, call meter and trace per run, then compiles a fixed LangGraph chain. Each role receives
only its explicit inputs, not the complete `Task` or the oracle's answer.

| Component | State and responsibility |
| --- | --- |
| LangGraph | Three artifacts in `WorkflowState`; an in-memory checkpoint per invocation |
| Researcher | Current catalog → structured offers; no historical snapshot in its prompt |
| Planner | Research offers + quantity/budget/authorized suppliers → plan or no purchase |
| Executor | Supplied plan → structured output; Python performs the simulated action |
| Provenance | Unique attempt/stage/retry IDs, parent IDs, catalog version sources |
| Environment | Order ledger, cumulative budget enforcement, supplier authorization and monotonic action version |
| Oracle | Checks actual product, supplier, quantity, current price, stock and budget |
| Meter | Counts every backend dispatch, model request, failed response and reported token usage |

An accepted order may still be incorrect (e.g. wrong quantity/price/stock); the environment's
safety guard and the independent correctness oracle serve different purposes. A blocked bad
attempt can leave the correct final empty state on an infeasible task. Safety history therefore
must be reported separately from final correctness.

## Fault and verification order

For content faults: explicit inputs → backend generation → controlled mutation → artifact log
→ optional verification → next node or order. The original model output is preserved in the
model response record and the injection event records before/after values. Agent-visible
payloads do not contain fault labels. The stale injector uses an actual historical catalog and
updates artifact source-version tags accordingly.

For controlled timeout: a stage-start event is logged, then the harness records a missing output
and raises `InjectedTimeout` before backend dispatch. This tests scheduling, missing data and
restart; it does not simulate a partly completed remote request or partial external writes.

Always-verify uses a privileged programmatic oracle. It rejects a semantically invalid output
or controlled missing output and retries that stage within a fixed limit, without reinjecting.
Each rejected artifact remains in history, but only the accepted retry becomes a graph parent.
Malformed JSON, HTTP failures, and exhausted budgets terminate the run; no hidden repair/retry.

## Recovery

`FullRestart.plan()` accepts a known faulty artifact, or a separately identified failed stage
when no artifact exists. No fabricated timeout output is added to the trace. Disclosure occurs
after initial completion, or immediately at the controlled timeout boundary.

The runner resets the order ledger and runs a new graph without repeating the one-shot fault.
Fault detection is supplied by the harness. Initial cost, errors and unauthorized attempts
remain in the run totals. Completed recovery stages are counted from actual events, including
partial progress if recovery fails. History is append-only; retry and recovery IDs differ.

The model backend is stateless across calls. Memory checkpoints are process-local, and are not
used as environment snapshots. Graph replay alone would not restore tools, browser state,
files or orders.

## Reproducibility and accounting

Manifests store task/prompt/source hashes, config, model, dependency version and Git revision
when available. Full successful model messages and request IDs are logged without credential
headers. API errors preserve type, request accounting and any available usage, not response
error bodies. Invalid JSON after a billed response still retains reported usage.

Unknown token fields remain null, with known subtotals and unknown-call counts. Call and time
admission checks span the entire run, including retries/recovery. HTTP timeout is bounded by
remaining time; token enforcement occurs after usage is reported and can overshoot once.

Disabled disk tracking still keeps lean scoring events in memory. The overhead comparison
therefore measures persistence/serialization overhead, not total provenance bookkeeping.

## Phase 2 extensions

Keep the current Phase 1 chain for comparison. Add branches and shared-state readers only when
implementing selective recovery, then introduce real resource read/write versions, invalidation,
partial rerun scheduling, environment snapshots/compensation, and validation of reused artifacts.
Report irreversible effects explicitly. The current full reset is valid only for this simulated ledger.
