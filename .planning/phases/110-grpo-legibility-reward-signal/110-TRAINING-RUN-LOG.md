# Phase 110 Training Run Log

**Instance:** <vastai instance ID — fill in after launch>
**Started:** <ISO timestamp>
**Completed:** <ISO timestamp or "interrupted">
**Wall time:** <hours>

## Hyperparameters

- Base model: <path>
- LoRA rank: 16
- LoRA alpha: 32
- SFT learning rate: <from config>
- GRPO learning rate: <from config>
- SFT steps: <actual>
- GRPO steps: <actual>
- Save steps: 50
- Seed: 42
- Max checkpoint MB: 100

## Data

- SFT rows: <count from srs_labels.jsonl>
- GRPO rows: <count from exploration.jsonl>

## Reward Trajectory (GRPO)

<plot or table: step -> reward_mean, correctness, completeness, legibility>

## Post-Rollout Critique Stats

- critiques registered: <count>
- critiques model_used=gemma4: <count>
- critiques model_used=claude (R-4 fallback): <count>
- critiques model_used=none (R-6 fallback): <count>
- malformed critiques caught (LO-110-11): <count>

## Final Adapter

- Path: /Volumes/Storage/models/kicad-agent/adapters/legibility-v1/
- File count: <N>
- Total size: <MB>

## Held-Out Fixture Eval (HI-110-08)

- Fixture: <path>
- Phase 97 baseline SRS overall: <value>
- Phase 110 adapter SRS overall: <value>
- Absolute delta: <value> (must be >= 0.02 to count as "improved")

## Issues Encountered

<SIGTERM events, host failures, fallback-to-local incidents>

## Operator Sign-off

- [ ] Adapter loads without error on local Mac
- [ ] SRS overall improvement >= 0.02 absolute on held-out fixture (HI-110-08)
- [ ] No regression on correctness/completeness
