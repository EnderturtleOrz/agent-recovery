# Purchase output contract, v5

## Problem

The v4 Planner response used the same schema as research artifacts. It could return a
correct no-purchase decision together with a copied `offers` list. The semantic verifier
required that list to be empty for an infeasible task, although the prompt did not require
it. The unverified workflow accepted the same decision. This confounded the strategy
comparison and inflated invalid-artifact and wasted-work metrics.

## Contract

- Researcher reports quotes; research notes remain lower-trust input to Planner.
- Planner and Executor responses use `PlanResponse`: exactly four required fields,
  `value`, `product_id`, `supplier`, and `quantity`. Extra fields and wrong types fail
  strict parsing, with their model-call costs retained.
- No purchase is represented by
  `{"value":0,"product_id":null,"supplier":null,"quantity":0}`.
- The Executor input projects these four decision fields from the Planner artifact.
  It neither recalculates totals nor changes product, supplier, or quantity. Original
  artifacts remain in the trace, including annotations from alternate test backends.
- Semantic correctness checks the decision fields. Unused research annotations do not
  invalidate correct abstention, consistent with feasible-plan scoring and final-ledger
  scoring. Positive amounts/quantities, claimed products/suppliers, and abstention on a
  feasible task still fail when incorrect. Verification continues to reject instruction
  text in `note` and incorrect research quotes.
- The internal `Payload` remains a shared trace/storage representation; it is not the
  model-facing response schema for every stage. Schema validation is strict, while the
  semantic oracle judges the task decision. There is no automatic JSON repair, envelope
  unwrapping, amount correction, or uncounted retry.

The scalar fixture is unchanged. The prompt version is `purchase-v5`; fault schedules,
recovery policies, per-run limits, and the privileged nature of verification are unchanged.
All strategies use the same updated contract, so v4 and v5 results must not be pooled.

## Validation and experiment status

Regression tests cover the original abstention failure on budget/stock tasks, preservation
of faulty decision fields at the Executor boundary, rejection of wrong decisions and attack
notes, strict API schemas, and token accounting on schema failures. The development matrix
checks all existing fault schedules and recovery strategies offline: 240 development runs
passed for restart and always verify. All 164 tests passed, and 24 targeted real development
checks completed correctly (80 model calls), covering clean verification and all six fault
schedules on budget/stock-limited tasks. These checks were completed before final evaluation.

The old compact results have been cleared from `results/` at the user's request; the original
raw traces and a compact-results backup remain locally under `artifacts/`. The fresh v5
comparison uses `purchase-eval-v5.json`, generated with seed 29108 without model-outcome-based
selection. The new report is `results/phase1-results.md`. All strategies use the same frozen
v5 contract; old and new metrics are not pooled.
