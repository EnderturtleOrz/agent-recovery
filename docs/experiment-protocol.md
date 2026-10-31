# Phase 1 experiment protocol

This document defines the intended experiment protocol, including requirements not yet implemented.

## Experimental units and pairing

One unit is task × backend/model × fault schedule × method × replicate. Measure clean performance first, then run matched fault experiments. Hold task/prompt versions, model route, injection location and payload, disclosure timing, and resource budgets constant. Record seeds when supported without assuming remote inference is perfectly deterministic. Report sample counts, distributions, and uncertainty across tasks and repeated trials.

The current smoke configuration injects a numeric output fault once in attempt 0 and reveals its artifact ID after workflow completion. Recovery does not repeat the injection. This one-shot assumption does not model a persistent malicious source.

All recovery methods must receive the same faulty ID and disclosure boundary. Always-verify checks each intermediate result before consumption; include its clean-run verification overhead as well as its behavior under faults.

## Fault matrix

| Category | Case | Required evidence |
| --- | --- | --- |
| Accidental | Incorrect result | A downstream consumer uses the wrong value or fact; an independent oracle checks the result. |
| Accidental | Timeout | Stage failure, scheduling behavior, and partial writes; distinguish injection from network timeouts. |
| Accidental | Stale output | A source version is older than the environment; changing only content is insufficient. |
| Adversarial | Malicious instructions | Instructions enter through a lower-trust result; record unauthorized attempts and executions. |

Cover multiple stages and a shared-state case. Analyze accidental and adversarial cases separately. The deterministic numeric example validates instrumentation; it provides no evidence about prompt-injection resistance.

## Comparison methods

- **Clean:** no injection or recovery; establishes task success and cost.
- **No recovery:** inject and continue; measures propagation.
- **Full restart:** after disclosure, restore supported environment state and rerun all stages; retain original costs and safety history.
- **Always verify:** verify each intermediate result before consumption; define rejection/retry behavior and include extra inference cost. An oracle verifier must be labeled as an upper bound.
- **Selective recovery (Phase 2):** use the same disclosure information, starting state, and budget; rerun invalid work and validate every reused result.

## Metrics

| Metric | Definition | Current support |
| --- | --- | --- |
| Clean/recovered correctness | Independent oracle checks final task state; aggregate over eligible runs. | Per-run booleans. |
| Failure propagation | Downstream/final divergence among paired clean-correct runs whose injected output was consumed. | Integration tests for one chain; no batch aggregation. |
| Affected stages | Observed content changes relative to matched clean outputs; potential dependent descendants are a separate measure. | Trace supports inspection; no aggregator. |
| Unauthorized actions | Attempts and executions counted separately, including pre-recovery history. | Budget rule only. |
| Wasted work | Invalidated/discarded calls, tokens, and time. | Not implemented. |
| End-to-end latency | Initial execution through recovery and final evaluation. | Per run; includes stage trace writes, excludes manifest creation. |
| Recovery latency | Planning, environment restoration, and reruns after fault disclosure. | Per run. |
| Recomputed stages | Actual completed recovery stages; failed retries counted separately. | Successful full restart only. |
| Retained valid work | Validated artifacts actually reused, relative to eligible reusable work. | Restart retains zero; selective reuse not implemented. |
| Inference cost | All agent, verifier, failed, retry, and recovery calls/tokens; optionally prices with a dated price table. | Successful output usage in traces; full aggregation not implemented. |
| Tracking overhead | Matched runs with and without tracking, including time and space. | Trace write timing only, not total overhead. |
| Irreversible effects | Actions that cannot be restored and their consequences. | Requires environment extensions. |

Unknown usage must not be treated as zero. Currently, usage is not persisted if the API returns a response that fails JSON validation; complete failed-call accounting remains a Phase 1 requirement. Failed runs must stay in reported denominators. Final task correctness must be reported separately from safety history.

Stage events currently record structured inputs and artifact outputs. Full LLM request/response records, provider request IDs, prompt versions, complete usage, hard budgets, seeds, and batch matrices remain to be implemented.

## Phase 1 acceptance criteria

1. Reproducible TritonAI clean runs across a task set, with model/prompt/configuration and complete call costs.
2. Explicit schedules for four fault classes, multiple injection locations, and a shared-state case.
3. Paired evidence of actual consumption, distinguishing ignored messages, consumption without effect, and propagated failure.
4. Full restart and always-verify comparisons under matching task/fault matrices and call/token/time budgets.
5. Raw traces, reproducible analysis, aggregate results, and limitations, preserving failures and unauthorized-action history.

Environment drift and irreversible actions are central Phase 2 cases. Phase 1 should preserve resource/version/action interfaces rather than recording only agent messages.
