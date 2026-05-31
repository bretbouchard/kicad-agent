# Phase 42: Circuit QA Dataset

**Status:** PLANNING
**Requirements:** BENCH-03
**Depends on:** Phase 41 (PCB MMLU benchmark dataset)
**Milestone:** v2.5

## Goal

Generate 2000+ open-ended question-answer pairs from real schematics for fine-tuning circuit understanding models. Unlike PCB MMLU (multi-choice), this teaches models to explain circuits.

## Plans

### Plan 42-01: Circuit QA Dataset (BENCH-03)

**Goal:** Generate 2000+ QA pairs across 6 types: violation diagnosis, signal flow, component function, net purpose, design review, value calculation.

**QA Types:**
1. **Violation Diagnosis** — "Why does this schematic have X violation?" with root cause answer
2. **Signal Flow** — "What is the signal path from A to B?" with traced path answer
3. **Component Function** — "What is the purpose of R60?" with circuit-context answer
4. **Net Purpose** — "What is the SC_FILTER net for?" with functional explanation
5. **Design Review** — "What improvements could be made to X?" with actionable suggestions
6. **Value Calculation** — "What value should C47 be for X time constant?" with calculation

**Sources:**
- 55 hardware modules in analog-ecosystem
- Real ERC reports (with known violation types)
- Datasheets (THAT4301, CD4066BE, NE5532, RP2040)
- Netlists and BOMs

**Success Criteria:**
1. 2000+ QA pairs across all 6 types
2. All QA pairs have verifiable answers with source references
3. Dataset enables fine-tuning for circuit understanding
