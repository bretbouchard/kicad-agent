# Phase 52: Synthetic Circuit Generation

**Score Impact:** Training Corpus 8 -> 9
**Requirement:** CORPUS-01
**Depends On:** Phase 45 (circuit topology graph)

---

## Objective

Procedurally generate 10,000+ valid, diverse synthetic circuits for training data diversity. Template-based parameterized generation produces circuits that pass ERC validation, covering common analog building blocks with wide parameter sweeps.

---

## Why

The existing training infrastructure (`generator.py`, `chains.py`) produces maze routing samples and board-level data. There is no systematic generation of *circuit-level* training data -- actual electronic circuits with components, nets, and valid connectivity. Synthetic circuits fill this gap by:

1. Providing parameter-diverse examples for circuit recognition training
2. Generating adversarial edge cases (near-invalid parameter ranges)
3. Supplying labeled data where circuit function is known a priori
4. Enabling controlled experiments with known ground truth

---

## Plans

| Plan | Description | Files | Est. Tasks |
|------|-------------|-------|------------|
| [52-01](./52-01-PLAN.md) | Circuit template library + parameterized generation | `circuit_templates.py`, `synthetic_generator.py` | 2 |
| [52-02](./52-02-PLAN.md) | Mass generation pipeline + dataset packaging | `synthetic_generator.py` (extended), `mass_generate.py` | 2 |

---

## Success Criteria

- 10,000+ unique synthetic circuits generated
- All generated circuits pass ERC with 0 errors
- Coverage across 10+ circuit categories (amplifier, filter, buffer, etc.)
- Parameter range diversity within each category
- JSONL dataset compatible with existing `TrainingPipelineConfig`
- Train/val/test split (80/10/10)
