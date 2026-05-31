# Phase 44: Adversarial Test Generation

**Status:** PLANNING
**Requirements:** BENCH-05
**Depends on:** Phase 41 (PCB MMLU benchmark), Phase 42 (QA dataset)
**Milestone:** v2.5

## Goal

Automated generation of adversarial test cases — deliberately broken schematics, edge cases, and property-based tests that verify kicad-agent doesn't corrupt valid circuits.

## Plans

### Plan 44-01: Adversarial Test Generation (BENCH-05)

**Goal:** Three types of adversarial testing: mutation testing, property-based testing, and fuzzing.

**Type 1: Mutation Testing**
- Take valid schematics from analog-ecosystem
- Apply mutations: swap component values, break wires, remove labels, duplicate nets
- Verify kicad-agent detects the mutations (via ERC or explicit checks)
- Generate questions: "What is wrong with this schematic?"

```python
class SchematicMutation(BaseModel):
    mutation_type: Literal["swap_values", "break_wire", "remove_label", "duplicate_net",
                           "short_pins", "floating_pin", "wrong_polarity"]
    target: str          # Component ref or net name
    original: str        # Original state
    mutated: str         # Mutated state
    description: str     # Human-readable description
    expected_detection: str  # What ERC violation or check should catch this
```

**Type 2: Property-Based Testing**
- Generate random valid circuits from templates
- Verify invariants: operations preserve file validity, ERC doesn't increase after fixes
- Properties: "add_component then remove_component produces same file", "erc_auto_fix never increases violation count"

```python
class CircuitProperty(BaseModel):
    name: str
    description: str
    invariant: str           # Formal description
    test_count: int          # Number of random tests to run
    template: str            # Circuit template to generate from
```

**Type 3: Fuzzing**
- Random S-expression mutations on valid .kicad_sch files
- Verify parser doesn't crash (returns error, not segfault)
- Verify round-trip preserves structure (for valid inputs)

```python
class FuzzResult(BaseModel):
    mutation: str           # What was mutated
    crash: bool             # Did parser crash?
    parse_error: bool       # Did parser return error?
    round_trip_ok: bool     # Did round-trip preserve structure?
    mutation_seed: int      # For reproducibility
```

**Implementation:**
1. Create `src/kicad_agent/benchmarks/adversarial.py` — mutation, property, and fuzz generators
2. Create `benchmarks/adversarial-v1.json` — adversarial test suite
3. CLI: `python -m kicad_agent.benchmarks --adversarial --count 1000`

**Distribution targets:**
- 200 mutation tests (50 per mutation type, 4 types)
- 50 property-based tests (10 per property, 5 properties)
- 500 fuzz tests (random seed-based)
- Total: 750+ adversarial test cases

**Tests:**
- Mutation generator produces valid mutations
- Each mutation has expected_detection field
- Property tests verify invariants on generated circuits
- Fuzz tests don't crash the parser
- All adversarial tests are reproducible (seeded RNG)

**Success Criteria:**
1. 750+ adversarial test cases across 3 types
2. Mutation tests cover 7+ mutation types
3. Property tests verify 5+ invariants
4. Fuzz tests prove parser robustness (no crashes on 500 random mutations)
5. All tests are reproducible with seeds
