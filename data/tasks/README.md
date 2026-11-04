# Procurement datasets

All datasets are synthetic, use integer cents, and load directly into the existing
`mas-recovery suite --tasks ...` command. Each task contains three products, an
authorized supplier list, a current catalog at version 2, and a previous snapshot
at version 1. The cheaper unauthorized product tests supplier filtering.

| File | Purpose | Seed | Tasks | Feasible | Insufficient budget | Insufficient stock |
| --- | --- | --- | --- | --- | --- | --- |
| `purchase-suite.json` | Original smoke suite | 291 | 6 | 2 | 2 | 2 |
| `purchase-dev.json` | Development and prompt tuning | 29101 | 12 | 4 | 4 | 4 |
| `purchase-eval.json` | Historical evaluation used during v4 debugging | 29104 | 24 | 8 | 8 | 8 |
| `purchase-eval-v5.json` | Fresh v5 evaluation, frozen before inference | 29108 | 24 | 8 | 8 | 8 |

The development and evaluation files use the existing seeded generator. They have
distinct task IDs and no identical task contents within or across these four array
datasets, even when task IDs are ignored. Seeds were selected to avoid duplicate
contents, without evaluating model performance. These splits sample the same
simple task distribution; they do not establish generalization to new task types.

Use the development split to adjust prompts, fault handling, and recovery policies.
The original evaluation split informed contract debugging. Use the fresh v5 evaluation
split for the new comparison; its seed was selected by content overlap checks only, not
model outcomes. See `purchase-eval-v5-manifest.json` for the selection record. The evaluation
data is public, so this separation is an experiment practice rather than an enforced
access boundary.

## Run

From the repository root with the project environment activated:

```bash
mas-recovery suite --tasks data/tasks/purchase-dev.json --backend fake
mas-recovery suite --tasks data/tasks/purchase-eval-v5.json --backend fake
```

At one replicate, these schedule 240 and 480 workflow runs respectively. Add
`--overhead` for 264 and 528 runs. Multiply these counts by `--repeats`; workflow
runs are not model-call counts. The fake backend makes no model API requests.
For real-model measurements, configure TritonAI as described in the root README
and change the backend to `tritonai`. Offline results validate the harness, not
real-model robustness.

## Reproduce

Generate to new paths because the generator refuses to overwrite existing files:

```bash
mas-recovery generate --count 12 --seed 29101 --output /tmp/purchase-dev-reproduced.json
mas-recovery generate --count 24 --seed 29108 --output /tmp/purchase-eval-v5-reproduced.json
```

`purchase.json` and `purchase-structured.json` are individual task objects for
single-run configurations, rather than arrays for the suite.
