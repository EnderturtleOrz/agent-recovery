# Architecture

## Execution and state

`experiments/runner.py` builds the LangGraph workflow, runs it against a simulated world, evaluates the result, and optionally executes a recovery plan.

| State | Representation | Responsibility |
| --- | --- | --- |
| Graph | Node outputs and in-memory checkpoints | LangGraph scheduling and continuation |
| Dependencies | Artifact `parents` and versioned `sources` | Record actual inputs for later invalidation |
| Environment | Simulated order list and action events | Authorization, side effects, and reset |

Agents consume explicit inputs. The planner/executor do not receive the evaluator's expected answer. Fault labels and original values remain in harness traces rather than agent-visible payloads.

The current workflow is a single chain. Source fixtures use fixed version `@1`; this is not yet a general shared-state versioning system. `InMemorySaver` checkpoints disappear on process exit, while JSONL traces remain on disk. Graph checkpoints do not restore external side effects.

## Recovery contract

`RecoveryPolicy.plan(faulty_id, artifacts)` returns stages to rerun, artifact IDs to retain, and whether to reset the environment. The runner currently supports full restart only, including clearing simulated orders. Historical traces and unauthorized-attempt counts are preserved.

Phase 2 requires:

- Actual resource read/write versions and dependency invalidation.
- Environment snapshots or compensation, with irreversible actions reported explicitly.
- Partial execution and checks that reused parents, resource versions, and freshness remain valid.
- New artifact IDs for recomputation while preserving historical outputs.
- Independent branches and shared-state readers to measure retained work meaningfully.

## Model calls

The workflow uses HTTPX; the standalone connectivity script uses the optional OpenAI SDK. Both have a 60-second request timeout and disable automatic retries. Invalid JSON, API errors, and timeouts fail the run. Complete failed-call accounting remains part of Phase 1 work.

References: [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence).
