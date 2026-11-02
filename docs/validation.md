# Validation record

## Experiment execution and README review

- 132 tests passed, including 12 new regression cases for stage-specific numeric injection,
  independent baseline/overhead groups, interruption accounting and backend overrides.
- The final 264-run offline matrix completed with 24 expected no-recovery injected timeouts and
  zero unexpected execution failures. Primary clean controls: 12; clean verification: 12;
  scheduled fault runs: 216; separate overhead controls: 24.
- Real SIGINT was sent to an offline CLI subprocess: it stopped further dispatch, exited
  with code 130 and retained one finished run plus the interrupted run and partial summaries.
- The README's seven single-run experiment commands were each exercised with `--backend fake`.
  All configs loaded and ran; the two full-suite command counts were checked against the matrix.
- Artifact dependencies, trusted authorization, ledger replay, source hashes and CSV aggregation
  were audited. No real model API requests were made in this review.

Evidence: [experiment-review-validation.json](experiment-review-validation.json).
Raw matrix: [summary.csv](../artifacts/experiment-review-validation/suite-a9089f77a4b348aea0e86a06e7f71c85/summary.csv).
Ctrl+C evidence: [partial suite](../artifacts/experiment-review-sigint/suite-abeb38a937644c8099a58daa54ca2129/suite-manifest.json).
Earlier records below refer to their respective historical source hashes.

## Authorization and budget boundary regression checks

The PR review identified a supplier-claim bypass and rejection of an exactly-at-limit final
token response. Both were reproduced before fixing. Trusted catalog authorization now checks
product existence, actual supplier approval and claim consistency. Token checks distinguish
admission from completion: equality accepts the completed result and prohibits another call.

Related checks cover malformed order inputs, cumulative budget/reset, sticky unknown token
usage after failure, real execution-counter derivation, nonfinite/boolean numeric limits,
incomplete provider finish reasons, optional Git metadata and unapplied/no-op fault schedules.
Price and stock correctness remain separate oracle checks so numeric propagation experiments
retain their meaning.

- All **120 tests** passed (43 new boundary regression cases); lint, formatting, whitespace and
  locked-environment dependency checks passed.
- The complete 264-run offline matrix was rerun: 240 completed, 24 expected no-recovery injected
  timeouts, and zero unexpected execution failures. Full restart was correct in 72/72 runs;
  always-verify (including clean controls) was correct in 84/84 runs.
- Independent artifact audit checked trusted supplier mapping, ledger replay, historical safety
  counts, downstream parent inputs, source hashes, aggregate JSON and every CSV cell.
- A live baseline was attempted, but preflight found no `.env`, model setting or API key in the
  execution environment. No provider request was made; real-provider regression is not claimed.

Machine-readable evidence: [boundary-validation.json](boundary-validation.json).
Raw local suite: [summary.csv](../artifacts/boundary-validation/suite-3fc132e651944af9aa02ef120f50eed0/summary.csv).
Earlier validation records below remain historical.

## Prompt-v3 regression and real-provider checks

After a real scalar baseline returned 0 instead of 30, scalar and structured tasks were
separated into explicit input-shape contracts, independent instructions and response schemas.
Scalar responses now accept only a nonnegative integer `value`; no stock/supplier/budget rules
are sent to scalar roles. Structured tasks never fall back to scalar mode on empty offers.
Prompt version is `purchase-v3`; per-call traces record `prompt_mode`.

- 77 tests passed; lint, formatting and diff checks passed.
- Two real TritonAI scalar baselines both returned 10 → 30 → 30, with final correctness true.
- One real structured procurement baseline also completed correctly.
- Nine actual model calls were used for these checks. No automatic retries or answer correction.
- These are limited real-provider smoke checks, not a completed real-model fault matrix.

Machine-readable evidence and artifact paths: [prompt-v3-validation.json](prompt-v3-validation.json).
The older offline record below is retained as historical purchase-v2 validation; its source hash
identifies that earlier implementation and is not the current v3 source hash.

## Original Phase 1 offline validation (purchase-v2)

Validation was completed against the original repository on 2026-11-01 (America/Los_Angeles).
Python 3.12.10; exact `uv.lock` environment with all extras, including the optional OpenAI SDK.
The lockfile and pip export remain unchanged. All 48 installed packages passed compatibility checks.

## Checks

- 66 automated tests passed, including the original scalar workflow regression tests.
- Ruff lint and formatting passed; `git diff --check` passed.
- Tested four fault classes, both supported injection boundaries, all three methods, source
  versions, verifier rejection/retry, partial failed recovery, call/time/token budgets, unknown
  usage, malformed JSON, HTTP errors and provider timeouts.
- HTTP mocks exercised the actual TritonAI adapter, structured prompts and response parsing,
  full restart, usage totals, missing usage and billed malformed-output accounting.
- Full matrix: six structured tasks, two replicates, six fault schedules, three methods,
  two clean baselines and optional paired disk-trace timing: **264 runs**.
- 240 completed; 24 expected injected-timeout failures in the no-recovery method; **zero
  unexpected execution failures**. A completed run can still have an intentionally incorrect
  task result; completion is not success.
- Full restart: 72/72 correct; always-verify (including clean controls): 84/84 correct.
- Actual model API calls in this offline matrix: zero.

## Independent artifact audit

Every tracked run was replayed to verify event sequence, artifact-parent integrity, downstream
inputs against actual parent payloads, simulated final order state and retained unauthorized
attempts. Every run's source hash matched the code. Aggregate JSON was regenerated from raw
rows and every CSV cell was checked against aggregate JSON.

Machine-readable record: [validation-results.json](validation-results.json).

Raw run manifests, messages and tool actions remain in the ignored local artifact directory:
[offline suite](../artifacts/validation/suite-d3b7353d490f47b39156ebb4a6251793/summary.csv).
These local artifacts are not automatically included in Git; include/export them deliberately
when submitting experimental evidence.

## Reproduce

From the repository root, after the README setup:

```bash
python -m pytest
ruff check .
ruff format --check .
uv pip check
mas-recovery suite --backend fake --repeats 2 --overhead
```

Generated run IDs and timings vary; compare outcomes and counts, not byte-for-byte traces.
The CI also runs a one-replicate offline matrix.

## Limits of this evidence

No API key or repository `.env` was available, so real TritonAI calls were **not** made. Real
model compatibility, task success, prompt-injection resistance, latency and billed cost still
require the real-model procedure in the README. Fake-backend attack behavior is deliberately
scripted and supports no conclusion about real models.

Always-verify is a privileged programmatic oracle, not a learned detector. Controlled timeouts
simulate missing outputs, not partial remote execution. Disk-trace timing excludes the common
in-memory provenance bookkeeping. Selective recovery and shared-state rollback remain Phase 2.
