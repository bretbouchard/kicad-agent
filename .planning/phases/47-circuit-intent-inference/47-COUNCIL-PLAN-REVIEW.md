# The Council of Ricks Plan Review Report

## Stack Assessment

**Detected Project Stack:**
- **Project Type**: Python (kicad-agent)
- **Domain**: EDA / KiCad automation / analog circuit intelligence
- **Build System**: pip install -e . (setuptools + setuptools-scm)
- **Testing**: pytest
- **Key Dependencies**: Pydantic v2, kiutils, networkx, shapely
- **Existing CLI**: `kicad-agent` via `src/kicad_agent/cli.py` (single-file, no subcommand architecture yet)
- **Existing ABC Pattern**: `BenchmarkModel` in `benchmarks/models.py`
- **Existing Rule Pattern**: `violation_classifier.py` ordered rules (first match wins)

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (PCB/EDA specialist), Embedded Firmware Rick (analog circuit patterns)
- **Wave Delta (Pipeline):** GSD Plan Checker (plan review specialist)
- **Wave Epsilon (Fresh Eyes):** Spectral Rick (frequency-domain perspective on signal flow), Thermal Rick (thermal awareness in design rules)
- **Total reviewers this session:** 10/84

---

## Executive Summary
- **Total Issues**: 14
- **Critical (SLC)**: 3
- **High (Architecture/Security)**: 4
- **Medium (Functional)**: 5
- **Low (Style/Completeness)**: 2

---

## Historical Context and Pattern Wisdom (Rickfucius)
**Status**: PATTERNS FOUND

### Relevant Patterns Found

#### Ordered Rules Pattern (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Phase 47-01 uses `_DEFAULT_INTENT_RULES` as an ordered list of `(match_fn, ...)` tuples with first-match-wins semantics. This directly mirrors the `RuleTuple` pattern in `violation_classifier.py` which the project has used since Phase 40. Clean consistency.
- **Recommendation**: Follow pattern -- this is proven in this codebase.

#### Pydantic Schema with Field Validators (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Both `DesignIntent`/`SubcircuitIntent` (47-01) and `DesignFinding`/`DesignReview` (47-02) use Pydantic BaseModel with `Field()` constraints and `@field_validator` methods. Matches the existing `GenerationIntent` pattern in `generation/intent.py` and `BenchmarkModel` patterns.
- **Recommendation**: Follow pattern -- consistent with codebase.

#### Frozen Dataclass for Results (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: `InferenceResult` uses `@dataclass(frozen=True)`, matching `FixOption` and `DiagnosisResult` in `violation_diagnostic.py`. Immutable results are the standard here.
- **Recommendation**: Follow pattern.

### Anti-Patterns Detected

#### Duplicate Field in Test Data (47-01-PLAN.md:237-238)
- **Category**: code
- **Problem**: `ENVELOPE_SUBCIRCUIT` mock data has `control_nets` defined twice -- once as `("ATTACK", "DECAY", "SUSTAIN", "RELEASE")` and again as `("ATTACK", "DECAY")`. In Python, the second assignment silently shadows the first, so the test would only have 2 control nets instead of 4. This is a syntax error in a dataclass constructor (duplicate keyword argument) that would crash at runtime.
- **Historical Evidence**: Similar typos in mock data caused test failures in Phase 41 where question templates had mismatched placeholder counts.
- **Current Violations**: `47-01-PLAN.md` lines 237-238.
- **Recommendation**: Remove the duplicate line. Keep the full ADSR set `("ATTACK", "DECAY", "SUSTAIN", "RELEASE")` for test realism.

#### DOMAIN-03 and DOMAIN-04 Not in REQUIREMENTS.md
- **Category**: architecture
- **Problem**: Phase 47 claims `requirements: [DOMAIN-03]` and Phase 48 claims `requirements: [DOMAIN-04]`, but REQUIREMENTS.md does not contain these requirement IDs. The file stops at BENCH-05. Requirements must be traceable from plans to the formal requirements document.
- **Historical Evidence**: Wave 1 review (Phase 41) flagged the same issue: "BENCH-01 through BENCH-05 should be added to REQUIREMENTS.md." That review was APPROVE-with-conditions, and the requirement was to add them. They were added. Now DOMAIN-03/04 need the same treatment.
- **Recommendation**: Add DOMAIN-03 and DOMAIN-04 to REQUIREMENTS.md before execution.

**Rickfucius Decision**: DOCUMENT DEVIATION -- duplicate field and missing requirements must be resolved before execution.

---

## SLC Validation (Slick Rick)
**Status**: FAIL

### SLC Anti-Patterns Detected
- **Workarounds**: 2 found
- **Stub Methods**: 1 found
- **TODO/FIXME without tickets**: 0 found
- **Incomplete Implementations**: 2 found

### SLC Criteria Assessment

- [x] **Simple**: Obvious purpose, minimal learning
  - [Intuitive interface? yes] IntentInferrer.infer(topology) is clean and self-documenting.
  - [Self-explanatory features? yes] Rule names like BYPASS_CAP_01 are descriptive.
  - [Minimal docs needed? yes] Usage examples are embedded in docstrings.

- [x] **Lovable**: Delightful to use, builds trust
  - [Polished design? yes] Signal flow descriptions like "Audio input -> bypass switch -> VCA -> output buffer" are delightful.
  - [Graceful errors? partial] Engine handles rule errors gracefully (try/except per rule). But CLI _extract_topology has a stub.
  - [Celebrated successes? yes] Markdown report with severity badges and "All design rules passed. Circuit looks good!" message.

- [ ] **Complete**: Full user journey, no gaps
  - [All APIs implemented? no] `_extract_topology` in 48-02 has `pass  # Implementation details`.
  - [Edge cases handled? no] See incomplete implementations below.
  - [No broken flows? no] CLI uses `_MinimalTopology` workaround class.

### Critical SLC Violations

#### SLC-1: `_extract_topology` stub with `pass  # Implementation details` (48-02-PLAN.md:636)
- **Severity**: CRITICAL
- **Description**: The CLI subcommand's `_extract_topology` function has a loop body that is literally `pass  # Implementation details`. This is a stub method -- the exact pattern the Council explicitly removed in Phase 24. The function returns an empty `_MinimalTopology` that will produce zero rule violations on any schematic, making the entire CLI subcommand useless.
- **Fix**: Either (a) implement topology extraction from SchematicGraph (the actual integration point with Phase 46), or (b) defer the CLI subcommand to a Phase 48-03 plan that runs after Phase 46 produces the real `CircuitTopology` builder. The current plan has `depends_on: [48-01]` but should also depend on Phase 46's topology extraction being complete. Option (b) is recommended -- the engine (48-01) and config (48-02 Task 1) can ship now, but the CLI needs real topology data.

#### SLC-2: `_MinimalTopology` workaround class (48-02-PLAN.md:650-654)
- **Severity**: CRITICAL
- **Description**: The plan creates a `_MinimalTopology` class as a workaround for "before Phase 46 is complete." This is exactly the kind of workaround the SLC framework forbids. A class that exists only to paper over a missing dependency is a workaround, not an implementation.
- **Fix**: Remove `_MinimalTopology`. The CLI should use Phase 46's `CircuitTopology` directly. If Phase 46 isn't ready, defer CLI integration.

#### SLC-3: Duplicate `control_nets` field in mock data (47-01-PLAN.md:237-238)
- **Severity**: CRITICAL
- **Description**: `ENVELOPE_SUBCIRCUIT` has `control_nets` specified twice:
  ```python
  control_nets=("ATTACK", "DECAY", "SUSTAIN", "RELEASE"),
  control_nets=("ATTACK", "DECAY"),
  ```
  This is a Python `SyntaxError` for dataclass constructors (duplicate keyword argument). The test file will crash immediately on import. The plan author noted this is a real ADSR envelope from the analog-ecosystem -- the full 4-control version is correct.
- **Fix**: Remove the second `control_nets` line. Keep `("ATTACK", "DECAY", "SUSTAIN", "RELEASE")`.

**SLC Decision**: REJECT -- stub method and workaround class must be removed or deferred.

---

## Security Review (Rick C-137)
**Status**: PASS (with recommendations)

### Threat Assessment

All four plans include STRIDE threat models. Key findings:

#### YAML Safe Loading (48-02-PLAN.md)
- **Severity**: N/A (Correct)
- **Category**: injection
- **Description**: The plan correctly uses `yaml.safe_load()` (not `yaml.load()`) for rule configuration. This prevents arbitrary code execution from user-provided YAML files. T-48-06 and T-48-10 both document this mitigation. This is correct practice.
- **Confidence**: 0.95

#### PyYAML Missing from Dependencies (48-02-PLAN.md)
- **Severity**: HIGH
- **Category**: supply_chain
- **Description**: Plan 48-02 uses `import yaml` and calls `yaml.safe_load()`, but `pyproject.toml` does not list `PyYAML` in any dependency group (core, dev, optional). The import will fail at runtime with `ModuleNotFoundError`. No `pip install pyyaml` anywhere in the project.
- **Location**: `src/kicad_agent/analysis/rule_config.py` (to be created)
- **Exploit Scenario**: Not a security exploit, but a build failure. The `yaml` module import is inside the `load()` method body (`import yaml`), so it will only crash when a user actually provides a YAML config file. This is a latent import error.
- **Fix Recommendation**: Add `pyyaml>=6.0` to `pyproject.toml` `[project.dependencies]`. Move `import yaml` to the module top-level (not inside the function body) so the import failure is caught at startup, not at first use.
- **Confidence**: 0.95

#### Config Threshold Validation (48-02-PLAN.md)
- **Severity**: MEDIUM
- **Category**: injection
- **Description**: T-48-07 mentions "Threshold values validated as numeric with reasonable bounds" but the `RuleConfigLoader.load()` implementation does not perform this validation. The `thresholds` dict from YAML is passed directly to `configs[rule_name] = thresholds` without type checking. A YAML file with `thresholds: {max_distance_mm: "INJECT"}` would pass a string to the rule's `check()` method, which would then fail with a TypeError during comparison.
- **Fix Recommendation**: Add threshold validation in `RuleConfigLoader.load()`: verify each threshold value is `int | float` and within documented bounds (e.g., `max_distance_mm` in [0.1, 100.0]). Use Pydantic for this if feasible, or a simple type/bounds check.
- **Confidence**: 0.85

#### Unknown Rule Name Rejection (48-02-PLAN.md)
- **Severity**: N/A (Correct)
- **Category**: tampering
- **Description**: Unknown rule names in YAML config are rejected with `ValueError`. This prevents injection of fake rule configurations. Correct practice.
- **Confidence**: 0.95

**Security Summary**:
- High Severity: 1 (missing PyYAML dependency)
- Medium Severity: 1 (threshold validation gap)
- Low Severity: 0

**Security Decision**: CONDITIONAL APPROVE -- PyYAML must be added to dependencies. Threshold validation should be added but does not block.

---

## Code Quality Review (Rick Sanchez)
**Status**: FAIL

### Issues Found

#### ARCH-1: `topology: Any` in DesignRule ABC violates schema completeness principle (48-01-PLAN.md:320)
- **Severity**: HIGH
- **Category**: anti-pattern
- **Description**: The `DesignRule` ABC's `check()` method signature uses `topology: Any` instead of `CircuitTopology`. The plan explicitly comments `# CircuitTopology from Phase 46` but does not use the type. The review dimension asked specifically: "Schema Completeness -- All Pydantic schemas fully specified? No bare `Any`?" This plan has `Any` in the most important interface in the entire phase -- the abstract method that all 8 built-in rules must implement. Every single `check()` method in every rule inherits this `Any` type.
- **Engineering Principle**: Type safety at interface boundaries. The ABC defines the contract; the contract should be typed.
- **Fix Recommendation**: Use a `TYPE_CHECKING` guard or a Protocol to reference `CircuitTopology` without a runtime import dependency:
  ```python
  from __future__ import annotations
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from kicad_agent.analysis.topology_types import CircuitTopology

  class DesignRule(ABC):
      @abstractmethod
      def check(self, topology: CircuitTopology, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
  ```
  This gives full type safety for static analysis (mypy) while avoiding circular imports.

#### ARCH-2: `InputProtectionRule` contains a known bug that the plan says to "fix before running tests" (48-01-PLAN.md:1071, 1132-1133)
- **Severity**: HIGH
- **Category**: correctness
- **Description**: The plan's own code for `InputProtectionRule` uses `net_name` (undefined variable) instead of `net.name`. The plan acknowledges this at line 1132: "NOTE: Fix the `InputProtectionRule` bug where `net_name` is used instead of `net.name`: This is a deliberate typo that the test will catch -- fix it before running tests." Including known bugs in a plan is not acceptable. The plan should contain correct code. The TDD tests should catch bugs in the implementation, not bugs in the plan itself. If the plan contains bugs deliberately, how does the executor know which bugs are "deliberate" and which are real mistakes?
- **Engineering Principle**: Plans should contain correct code. Tests validate implementations, not plans.
- **Fix Recommendation**: Fix the bug in the plan. Replace `net_name` with `net.name` on line 1071. Remove the NOTE about the deliberate typo.

#### ARCH-3: Functional overlap between Phase 47-02 DesignReviewer and Phase 48-01 DesignRuleEngine (47-02, 48-01)
- **Severity**: MEDIUM
- **Category**: architecture
- **Description**: Phase 47-02 creates a `DesignReviewer` with checks for bypass caps, feedback compensation, power decoupling, input protection, and component values. Phase 48-01 creates a `DesignRuleEngine` with 8 built-in rules covering the exact same checks: `BYPASS_CAP_01`, `FEEDBACK_01`, `POWER_01`, `SIGNAL_01`, etc. Both systems check bypass caps. Both check feedback compensation. Both check input protection. The plans create two parallel, duplicate review systems with different schemas (`DesignFinding` vs `DesignRuleViolation`), different severity enums (`ReviewSeverity` vs `RuleSeverity`), and different check implementations.
- **Engineering Principle**: DRY -- Don't Repeat Yourself. Two systems doing the same thing with different APIs creates confusion and maintenance burden.
- **Fix Recommendation**: Either (a) Phase 47-02 `DesignReviewer` should be built on top of Phase 48-01's `DesignRuleEngine` (use the rules engine as the backend, with a DesignReviewer facade), or (b) Phase 47-02 should be scoped differently to avoid overlap -- focusing on intent-aware suggestions (which are qualitative and opinion-based) while Phase 48 handles pass/fail rule checks (which are binary). Option (b) is better: 47-02 provides human-readable improvement suggestions informed by intent; 48-01 provides structured pass/fail violations. But the overlap in check implementations must be addressed. The helpers (`_find_ics`, `_get_power_nets`, `_has_cap_on_nets`) should live in one place and be imported by both.

#### ARCH-4: DesignRule is an ABC with class-level attributes, not abstract properties (48-01-PLAN.md:299-305)
- **Severity**: MEDIUM
- **Category**: pattern_consistency
- **Description**: The `DesignRule` ABC defines `name`, `category`, `default_severity`, and `description` as class-level attributes without `@abstractmethod` or `@property`. This means a subclass can instantiate without defining these attributes, and the engine would crash when accessing `rule.name`. The existing `BenchmarkModel` ABC in `benchmarks/models.py` correctly uses `@abstractmethod` for its single method. But it has no class-level attributes to validate.
- **Engineering Principle**: ABC contracts should enforce all required attributes.
- **Fix Recommendation**: Use `@abstractmethod` combined with `@property` for `name` and `category`, or validate in `__init_subclass__` that required attributes are defined. Alternatively, use a `__init__` that validates `name` is not empty:
  ```python
  class DesignRule(ABC):
      name: str = ""  # Override in subclass
      ...
      def __init__(self):
          if not self.name:
              raise TypeError(f"{type(self).__name__} must define 'name'")
  ```

#### ARCH-5: `DesignReview.model_post_init` mutates `summary` on a Pydantic BaseModel (47-02-PLAN.md)
- **Severity**: MEDIUM
- **Category**: correctness
- **Description**: `DesignReview.model_post_init` assigns to `self.summary` which mutates the model after initialization. Pydantic v2 models are not frozen by default, so this technically works, but it violates immutability principles established in this project's coding-style rules ("ALWAYS create new objects, NEVER mutate existing ones"). The `DesignRuleReport` in 48-01 has the same pattern. If either model is later marked `frozen=True`, this will break.
- **Fix Recommendation**: Use `@model_validator(mode="after")` instead of `model_post_init`, or compute `summary` as a `@computed_field` property. This avoids mutation:
  ```python
  from pydantic import computed_field

  class DesignReview(BaseModel):
      findings: tuple[DesignFinding, ...] = Field(default_factory=tuple)

      @computed_field
      @property
      def summary(self) -> dict[str, int]:
          counts = {s.value: 0 for s in ReviewSeverity}
          for f in self.findings:
              counts[f.severity.value] += 1
          return counts
  ```

#### ARCH-6: Signal flow ordering algorithm underspecified (47-01-PLAN.md)
- **Severity**: LOW
- **Category**: completeness
- **Description**: `_build_signal_flow` says "Sort intents: inputs first, then processing, then outputs" but does not define how to classify a subcircuit as "input", "processing", or "output." The only clue is "Uses net names to determine ordering." But what if net names don't follow a convention? What if two subcircuits both claim the same net as output?
- **Fix Recommendation**: Define explicit ordering rules:
  1. Subcircuits with input nets matching `*_IN` patterns but no input from other subcircuits = "input stage"
  2. Subcircuits whose input is another subcircuit's output = "processing stage" (chain)
  3. Subcircuits whose output is not consumed by any other subcircuit = "output stage"
  This is a topological sort on the subcircuit connectivity graph.

**Code Summary**:
- Critical: 0
- High: 2
- Medium: 3
- Low: 1

**Code Decision**: REJECT -- HIGH issues (bare `Any` in ABC, known bug in plan) must be resolved.

---

## Design Review (Rick Prime)
**Status**: PASS (with recommendations)

### Issues Found

#### DESIGN-1: CLI architecture -- register_parser expects existing subcommand infrastructure (48-02-PLAN.md)
- **Severity**: MEDIUM
- **Category**: consistency
- **Description**: Plan 48-02 defines `register_parser(subparsers)` to add the `design-rules` subcommand, but the existing `cli.py` is a single-file CLI with no subcommand architecture. It uses `argparse.ArgumentParser` directly, not `add_subparsers()`. The plan does not include modifying `cli.py` to add subparser support. The `register_parser` function will never be called.
- **Design Principle**: New features must integrate with existing architecture.
- **Fix Recommendation**: Add a task to modify `src/kicad_agent/cli.py` to support subcommands via `add_subparsers()`. This is a prerequisite for the `design-rules` subcommand. Alternatively, document that Phase 48-02 assumes a prior phase has already refactored the CLI.

#### DESIGN-2: Severity naming inconsistency between phases (47-02 vs 48-01)
- **Severity**: LOW
- **Category**: consistency
- **Description**: Phase 47-02 defines `ReviewSeverity` with values `INFO, SUGGESTION, WARNING, CRITICAL`. Phase 48-01 defines `RuleSeverity` with identical values `INFO, SUGGESTION, WARNING, CRITICAL`. Two enums with the same values and different names. Any code that needs to convert between them must map manually.
- **Fix Recommendation**: Define severity once in a shared module (e.g., `analysis/severity.py`) and import it in both phases.

**Design Summary**:
- High: 0
- Medium: 1
- Low: 1

**Design Decision**: CONDITIONAL APPROVE -- CLI integration must be addressed.

---

## KiCad/EDA Domain Review (KiCad Rick)
**Status**: PASS (with recommendations)

### Domain Assessment

#### Circuit Pattern Coverage
The intent inference rules cover the core analog-ecosystem components well:
- THAT4301 (compressor VCA), NE5532 (op-amp buffer/amplifier), CD4066 (analog switch), CD4060 (oscillator), LM358 (integrator/envelope), TL072 (JFET op-amp), PT2399 (delay), RP2040 (MCU), LM7812/LM7912 (regulators). This maps directly to the real hardware modules in the analog-ecosystem project.

#### Design Rule Coverage
The 8 built-in rules cover the most common analog design review checks:
- Bypass caps, feedback compensation, impedance matching, thermal, ground topology, power filtering, input protection, layout complexity. This is a solid set for an audio-focused EDA tool.

### Issues Found

#### DOMAIN-1: Intent inference depends on Phase 46 output interfaces that may not exist yet (47-01)
- **Severity**: HIGH
- **Category**: dependency
- **Description**: Plan 47-01 says `depends_on: [46-01]` and uses `CircuitTopology`, `ComponentNode`, `NetNode`, `Subcircuit`, and `Connection` from Phase 46. The plan says "these files are being written simultaneously." If Phase 46 changes the interface (different field names, different dataclass structure), Phase 47's code breaks silently. The interface section in 47-01 shows expected types, but these are not a contract -- they are a wish.
- **KiCad-Specific Concern**: The `ComponentNode.pin_nets: dict[str, str]` field maps pin names to net names. But KiCad multi-unit symbols (like CD4066BE with 5 units) have pins spread across units. The pin name alone may not be unique. The interface needs to clarify whether `pin_nets` includes unit information or whether all units are merged.
- **Fix Recommendation**: Create a shared `analysis/topology_types.py` file that both Phase 46 and Phase 47 import from. This file becomes the single source of truth for the topology interface. Phase 46 writes to it, Phase 47 reads from it. Changes are immediately visible.

#### DOMAIN-2: `check()` methods access `topology.components` and `topology.nets` by attribute name but topology type is `Any` (48-01)
- **Severity**: MEDIUM
- **Category**: correctness
- **Description**: Every built-in rule does `for comp in topology.components` and `for net in topology.nets`. These attribute accesses are untyped because `topology: Any`. If Phase 46 names these fields differently (e.g., `component_nodes` instead of `components`), every rule breaks at runtime with `AttributeError`. This is the downstream consequence of ARCH-1.
- **Fix Recommendation**: See ARCH-1 fix. Type the parameter properly.

#### DOMAIN-3: Feedback detection algorithm assumes op-amp pin names are "+" and "-" (48-01-PLAN.md:FeedbackCompRule)
- **Severity**: LOW
- **Category**: correctness
- **Description**: `FeedbackCompRule.check()` uses `comp.pin_nets.get("-")` and `comp.pin_nets.get("OUT")` to find feedback paths. But KiCad op-amp symbols use various pin naming conventions: NE5532 uses `+`, `-`, `OUT`; TL072 uses `3` (non-inv), `2` (inv), `1` (out) for unit A. The `_OPAMP_LIB_PATTERNS` list includes both named-pin and numbered-pin symbols. The feedback detection will silently fail for numbered-pin op-amps because `pin_nets.get("-")` returns None.
- **Fix Recommendation**: Add pin name mappings per op-amp family, or use a more robust feedback detection that looks for any pair of pins connected through a resistor (one is the inverting input by IC convention, the other is the output).

**Domain Summary**:
- High: 1
- Medium: 1
- Low: 1

**Domain Decision**: CONDITIONAL APPROVE -- shared topology types and pin name handling must be addressed.

---

## Requirement Coverage Assessment

| Requirement | Phase | Plan | Coverage |
|------------|-------|------|----------|
| DOMAIN-03 (not in REQUIREMENTS.md) | 47 | 47-01, 47-02 | COVERED -- intent inference + design review schemas, engines, and tests. But requirement ID does not exist in formal requirements. |
| DOMAIN-04 (not in REQUIREMENTS.md) | 48 | 48-01, 48-02 | COVERED -- design rule ABC, 8 built-in rules, engine, config, reports, CLI. But requirement ID does not exist in formal requirements. |

**Coverage Gap**: DOMAIN-03 and DOMAIN-04 are referenced by plans but do not exist in `REQUIREMENTS.md`. They must be added for traceability. The Wave 1 review (Phase 41) flagged the identical issue for BENCH-01 through BENCH-05 and required they be added to REQUIREMENTS.md. Same standard applies here.

**Recommended requirement text for REQUIREMENTS.md:**

```
### Domain Intelligence (Phase 47)

- [ ] **DOMAIN-03**: Intent inference engine identifies circuit designer intent from topology + subcircuit data using deterministic rule-based matching; produces structured DesignIntent with subcircuit-level analysis, signal flow descriptions, and confidence scores; identifies compressor, buffer, switch, oscillator, and envelope intents from real analog-ecosystem circuit patterns

### Domain-Specific Design Rules (Phase 48)

- [ ] **DOMAIN-04**: Pluggable design rules engine with 8 built-in rules (bypass caps, feedback compensation, impedance, thermal, ground, power, signal protection, layout) runs against circuit topology; rules configurable via YAML (enable/disable, custom thresholds); reports in JSON and Markdown; CLI subcommand `kicad-agent design-rules <schematic>` works end-to-end
```

---

## Missing Edge Cases

### What the Plans Do Not Address

1. **Empty subcircuits list**: Phase 47-01 `IntentInferrer.infer()` receives a topology with `subcircuits=()`. The plan does not specify what happens. The `_infer_overall_type` method would receive an empty intents list. The success criteria say "handles empty topology gracefully" but the implementation does not show this path.

2. **Multi-unit IC handling**: CD4066 has 5 units in KiCad. The `ComponentNode` for each unit is separate in the schematic. Does Phase 46 group them into one subcircuit, or does Phase 47 see 5 separate "CD4066" components? The intent rules match on `lib_id` substring, so multiple matches could fire for the same physical IC.

3. **Config file with no `rules:` key**: 48-02 `RuleConfigLoader.load()` does `raw.get("rules", {})` which gracefully defaults to empty dict. But what if the YAML file has `rules: null`? `yaml.safe_load("rules: null")` produces `{"rules": None}`, and `None.items()` would raise `AttributeError`.

4. **Rule with zero violations and zero findings**: Both `DesignReview` and `DesignRuleReport` compute summaries from findings/violations. What does the summary look like for a perfect design? `{INFO: 0, SUGGESTION: 0, WARNING: 0, CRITICAL: 0}`. The Markdown report should say "No violations found" -- and it does (48-02). Good.

5. **Topology with no ICs**: The `_find_ics` helper in 47-02 and `_IC_LIB_PATTERNS` in 48-01 match only known IC lib_ids. A schematic with only passives (resistors, caps, inductors) produces zero ICs, zero subcircuits, zero intent. The plan handles this via "empty topology" test, but real schematics with only passives are common (RC filters, voltage dividers, passive crossovers).

6. **Concurrent rule execution**: The `DesignRuleEngine` runs rules sequentially. With 8 rules, this is fine. But the plan does not mention whether rules should be stateless (no shared mutable state between rules). If two rules both modify the topology or shared config, ordering matters. The plan does not address this.

7. **Markdown report escaping**: The `generate_markdown_report` function does not escape special Markdown characters in violation descriptions or suggestions. If a component ref or net name contains `*`, `_`, or `#`, it could break the Markdown formatting.

---

## Disagreement Resolution

No disagreements between Council members on this review. All specialists converge on the same core findings:

1. SLC violations: `_extract_topology` stub and `_MinimalTopology` workaround
2. Architecture: bare `Any` in ABC, known bug in plan code, functional overlap
3. Dependencies: PyYAML missing, DOMAIN-03/04 not in REQUIREMENTS.md
4. Domain: shared topology types needed, op-amp pin naming

---

## Final Council Decision

**Evil Morty's Ruling**: **REJECT**

### Decision Summary
- **SLC Validation**: FAIL (3 violations)
- **Security Review**: CONDITIONAL APPROVE (1 HIGH: missing PyYAML dependency)
- **Code Quality**: FAIL (2 HIGH, 3 MEDIUM)
- **Design Review**: CONDITIONAL APPROVE (1 MEDIUM: CLI integration)
- **KiCad Domain**: CONDITIONAL APPROVE (1 HIGH: shared topology types)
- **Historical Context**: DOCUMENT DEVIATION (duplicate field, missing requirements)

### All Issues to Fix Before Approval (sorted by severity)

#### CRITICAL (blocks approval)

1. **[CRITICAL] Remove `_extract_topology` stub and `_MinimalTopology` workaround** (48-02-PLAN.md:617-654)
   - The `pass  # Implementation details` body and `_MinimalTopology` class are SLC violations.
   - **Recommended fix**: Split 48-02 into two tasks that reflect actual dependency reality:
     - Task 1 (ship now): YAML config loader + JSON/Markdown report generators (no topology dependency)
     - Task 2 (defer): CLI subcommand -- depends on Phase 46 `CircuitTopology` being complete. Move to a 48-03 plan or add explicit dependency on Phase 46.
   - The engine and config are useful without the CLI. Do not ship a broken CLI.

2. **[CRITICAL] Fix duplicate `control_nets` in ENVELOPE_SUBCIRCUIT mock data** (47-01-PLAN.md:237-238)
   - Remove the second `control_nets=("ATTACK", "DECAY")` line.
   - Keep `control_nets=("ATTACK", "DECAY", "SUSTAIN", "RELEASE")` for ADSR realism.

3. **[CRITICAL] Add DOMAIN-03 and DOMAIN-04 to REQUIREMENTS.md** (REQUIREMENTS.md)
   - Requirements must be traceable from plans to the formal requirements document.
   - See recommended text in Requirement Coverage Assessment section above.

#### HIGH (strongly recommended, near-blocking)

4. **[HIGH] Type `topology` parameter as `CircuitTopology` in DesignRule ABC** (48-01-PLAN.md:320)
   - Use `TYPE_CHECKING` guard to avoid runtime import dependency.
   - This fixes the downstream `Any` propagation into all 8 rule `check()` methods.

5. **[HIGH] Fix `net_name` bug in InputProtectionRule plan code** (48-01-PLAN.md:1071)
   - Replace `net_name` with `net.name`. Remove the "deliberate typo" NOTE.
   - Plans should contain correct code. Period.

6. **[HIGH] Add `pyyaml>=6.0` to pyproject.toml dependencies** (48-02-PLAN.md)
   - Move `import yaml` to module top-level (not inside function body).
   - The function-body import hides the missing dependency until runtime.

7. **[HIGH] Create shared topology types module** (47-01, 48-01)
   - `src/kicad_agent/analysis/topology_types.py` should define `CircuitTopology`, `ComponentNode`, `NetNode`, `Subcircuit`, `Connection`.
   - Both Phase 46 and Phase 47/48 import from this single source of truth.
   - Prevents interface drift between simultaneously-written phases.

#### MEDIUM (must fix before execution)

8. **[MEDIUM] Address functional overlap between Phase 47-02 DesignReviewer and Phase 48-01 DesignRuleEngine**
   - Both implement bypass cap checks, feedback checks, and input protection checks.
   - Extract shared helper functions (`_find_ics`, `_get_power_nets`, `_has_cap_on_nets`) into a shared `_topology_helpers.py`.
   - Document the architectural difference: 47-02 is intent-aware qualitative review; 48-01 is structured pass/fail rules.

9. **[MEDIUM] Add threshold validation in RuleConfigLoader** (48-02-PLAN.md)
   - Validate that YAML threshold values are numeric (`int | float`) and within documented bounds.
   - Prevent `TypeError` in rule `check()` methods when bad config is loaded.

10. **[MEDIUM] Use `@computed_field` instead of `model_post_init` for summary** (47-02, 48-01)
    - Both `DesignReview` and `DesignRuleReport` mutate `self.summary` in `model_post_init`.
    - Replace with `@computed_field @property def summary(self)` for immutability.

11. **[MEDIUM] Add CLI subcommand infrastructure to cli.py** (48-02-PLAN.md)
    - Current `cli.py` uses `ArgumentParser` directly with no subcommand support.
    - Add `subparsers = parser.add_subparsers()` and wire `register_parser()` into the main CLI flow.
    - Or document that this is a prerequisite from a prior phase.

12. **[MEDIUM] Handle op-amp pin name variations in feedback detection** (48-01-PLAN.md:FeedbackCompRule)
    - Add pin name mappings per op-amp family (NE5532: +/-/OUT, TL072 unit A: 3/2/1, etc.).
    - Or use a position-based approach (pin 2 = inverting, pin 3 = non-inverting, pin 1/7 = output for dual op-amps).

#### LOW (recommended improvements)

13. **[LOW] Define signal flow ordering algorithm explicitly** (47-01-PLAN.md)
    - Specify how subcircuits are classified as input/processing/output stages.
    - Use topological sort on the subcircuit connectivity graph.

14. **[LOW] Unify severity enums** (47-02, 48-01)
    - `ReviewSeverity` and `RuleSeverity` have identical values. Define once in a shared module.

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. Every agent reviews. Every finding is fixed. Fresh eyes catch blind spots. Domain experts catch details. Evil Morty makes the final call. No appeals."

**Review Completed**: 2026-05-31
**Review Duration**: Wave 2 (Phases 47-48)
