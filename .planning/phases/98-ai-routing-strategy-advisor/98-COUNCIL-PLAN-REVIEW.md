---
phase: 98-ai-routing-strategy-advisor
review_type: plan
review_date: 2026-06-25
council_session_id: 98-PLAN-REV-001
status: APPROVED_WITH_FINDINGS
verdict: APPROVE
reviewer: Council of Ricks (Evil Morty presiding)
---

# Phase 98 — Council of Ricks PLAN Review

## Stack Assessment

| Property | Value |
|----------|-------|
| Project type | Python (kicad-agent library + CLI) |
| Domain | PCB design EDA + vision LLM inference |
| Critical dependency | mlx-vlm 0.6.3 (Gemma 4 12B V2 vision LoRA) |
| Wave Alpha | Rick Sanchez, Rick C-137, Slick Rick, Evil Morty |
| Wave Beta | Rick Prime, Rickfucius |
| Wave Gamma | `kicad-rick` (PCB), `sentinel-rick` (agent security), `apple-elitist-rick` (Apple Silicon MLX) |
| Wave Delta | `gsd-plan-checker` (plan review pipeline), `architect` (system design) |
| Wave Epsilon | `compliance-rick` (regulatory lens on ML safety), `test-rick` (testability lens) |
| Total reviewers | 11 of 84 (focused plan review) |

---

## Executive Summary

**Total findings: 8**
- Critical: 0
- High: 2
- Medium: 4
- Low: 2

**Verdict: APPROVE.** Zero critical/high BLOCKING findings. The two HIGH findings are real gaps but both have pragmatic mitigations available within the existing plans' scope, and the SLC gate passes. The plans demonstrate rigorous TDD discipline, accurate contract extraction (verified against source), defense-in-depth validation (R-4 semantic + H4 structural), and a defensible fallback chain (R-6). The central challenge — training data mismatch (0/6696 samples with strategy JSON) — is addressed appropriately via few-shot prompting, defensive parsing, and deterministic fallback.

The two HIGH findings (audit trail does not surface `routing_notes`; `mlx-vlm` not declared in `pyproject.toml`) must be resolved before or during execution but do not require plan re-architecture. Both are documented below with concrete remediation steps that fit inside the existing task structure.

---

## Historical Context & Pattern Wisdom (Rickfucius)

**Status:** ENRICHED

### Relevant Patterns Found

#### Pattern: Defense in Depth for Untrusted Model Output
- **Category:** security / agentic AI
- **Historical Context:** Phase 100 (RoutingOrchestrator) established H4 structural validation gate at `orchestrator.py:127-151` to catch unknown nets and invalid `RouterBackend` enum values. The H4 gate was designed knowing Phase 98 would feed untrusted AI output through it.
- **Pattern Compliance:** Plan 02 correctly extends (not duplicates) this pattern. R-4 (`StrategyValidator`) validates semantic correctness (coordinate bounds, net existence against netlist, layer validity against stackup) while H4 validates structural correctness (every net assigned, enum valid). The plans explicitly call out this separation in Plan 02 `<interfaces>` block lines 108-114 — verified accurate against `orchestrator.py`.
- **Recommendation:** Follow pattern. No change.
- **Action Items:** None.

#### Pattern: Thin Adapter Around Verified Pipeline
- **Category:** architecture
- **Historical Context:** Phase 97 (vision LoRA training) built `KiCadVisionPipeline.generate_from_image()` and verified it via `tests/inference/test_vision_pipeline.py` and `evaluation/vision_benchmark.py`. Wrapping (not modifying) the pipeline keeps those tests green and preserves the verified inference path.
- **Pattern Compliance:** Plan 01 Task 3 correctly wraps the pipeline as `self._pipeline.generate_from_image(image, prompt)` — verified signature at `vision_pipeline.py:76-112`. The class holds a `pipeline` reference typed as `Any` (lazy mlx-vlm import) — appropriate.
- **Recommendation:** Follow pattern. No change.

#### Pattern: Structural Subtyping for Protocol Extension
- **Category:** code / typing
- **Historical Context:** Phase 100 `RoutingStrategy` is `typing.Protocol` WITHOUT `@runtime_checkable` (verified `strategy.py:114`). The docstring explicitly states "Phase 98's AI advisor should be able to implement the strategy without inheriting from a base class."
- **Pattern Compliance:** Plan 01 correctly avoids inheritance. Acceptance criteria include `! grep -q "class AiRoutingStrategy(RoutingStrategy)"` and a runtime check `AiRoutingStrategy.__bases__ == (object,)`. Test 9 asserts both `hasattr(AiRoutingStrategy, "strategize")` AND `not issubclass(...)`. Verified: runtime semantics match (Protocol without `@runtime_checkable` raises TypeError on isinstance).
- **Recommendation:** Follow pattern. No change.

### Anti-Patterns Detected

#### Anti-Pattern: Requirement ID Namespace Collision
- **Problem:** Phase 100 uses R-1..R-7 + CR-01 (verified `.planning/ROADMAP.md:836`). Phase 98 also uses R-1..R-6 (defined in CONTEXT.md). The two namespaces collide — references to "R-4" or "R-6" without phase qualifier are ambiguous.
- **Solution:** Plans should qualify requirement IDs (e.g., `P98-R-4` vs `P100-R-4`) OR REQUIREMENTS.md should add Phase 98 entries with globally-unique IDs.
- **Current Violations:** All three plans' frontmatter (`requirements: [R-x, R-y]`) and task names use unqualified R-x.
- **Severity:** Low (internal consistency only — CONTEXT.md is unambiguous within Phase 98 scope).

#### Anti-Pattern: Silent Dependency on Undeclared Extra
- **Problem:** `mlx-vlm` is imported lazily by `vision_pipeline.py:90` (`from mlx_vlm import generate as mlx_generate`) but is NOT declared in `pyproject.toml` (verified: `grep mlx pyproject.toml` returns nothing). RESEARCH.md:91 explicitly flags this. Plan 01 declares `user_setup: service: mlx-vlm` but does not include `pyproject.toml` in `files_modified`.
- **Historical Evidence:** Phase 97 training installed mlx-vlm ad-hoc; it was never pinned. Version drift between training (0.6.2) and inference (0.6.3) is flagged in RESEARCH.md Assumption A1.
- **Solution:** Add `mlx-vlm==0.6.3` to `pyproject.toml [project.optional-dependencies]` under a `vision` extra. Plan 01 or Plan 02 should add this.

### Rickfucius Decision: APPROVE

The plans follow established patterns (thin adapter, defense-in-depth, Protocol subtyping) and respect Phase 100 contracts. Two anti-patterns (namespace collision, silent dependency) are documented but non-blocking.

---

## SLC Validation (Slick Rick)

**Status:** PASS

### SLC Anti-Patterns Detected
- **Workarounds in plans**: 0 (grep of all three PLAN.md files returned no matches for TODO/FIXME/XXX/workaround/hack/temporary/stub)
- **Stub methods**: 0 (every task has concrete behavior specs and acceptance criteria with grep checks)
- **"Good enough" language**: 0

### SLC Criteria Assessment

- [x] **Simple**: The three-plan decomposition mirrors the architectural responsibility map (R-1/R-2/R-3 = strategy + prompt + parser; R-4/R-6 = validator + fallback; R-5 = eval harness). Each plan has a single objective. No plan exceeds 3 tasks. Dependencies are linear (02 depends on 01; 03 depends on 01 and 02).

- [x] **Lovable**: Plans specify deterministic fallback to verified Phase 100 `DeterministicStrategy` — the user (orchestrator) always gets a valid `RoutingStrategyResult`. Polish details: `routing_notes` prefixed `ai_fallback:` for greppability (caveat in H-1 below), `logger.warning` records failure reason, SC-1 through SC-5 are falsifiable with concrete thresholds.

- [x] **Complete**: All 6 requirements (R-1 through R-6) mapped to plans. All 5 success criteria mapped to Plan 03 evaluators. R-4 has 24 unit tests covering 3 validation categories + SC-4 synthetic batch. Wave 0 test files listed in VALIDATION.md before implementation tasks. Edge cases enumerated (empty output, malformed JSON, render failure, inference failure, validation failure).

- [x] **Secure**: Two-layer validation (R-4 semantic + H4 structural). Broad `except Exception` in R-6 fallback is documented and justified (untrusted model output). Per-net safe default to `RouterBackend.ASTAR` (lowest-privilege backend — cannot dispatch to Freerouting without explicit model consent). Fixture files protected via `shutil.copy2` to temp dir (Plan 03 acceptance criterion). Model never loads in unit tests (`unittest.mock.MagicMock` for pipeline).

**SLC Decision: APPROVE**

---

## Code Quality Review (Rick Sanchez)

**Status:** PASS (with 1 MEDIUM finding on implementation specificity)

### Strengths

1. **TDD discipline is explicit and enforced.** Every task has `<behavior>` block with enumerated tests, `<action>` block with implementation spec, and `<verify>` block with pytest command. Acceptance criteria include grep checks for required symbols.
2. **Contract extraction is accurate.** The `<interfaces>` blocks quote exact signatures from `strategy.py`, `vision_pipeline.py`, `pcb_image_renderer.py`, `orchestrator.py`. Verified line-by-line against source.
3. **Acceptance criteria are mechanical and falsifiable.** Examples: `grep -c "net_priorities" returns >= 3`, `grep -c '```json' returns >= 2`, `AiRoutingStrategy.__bases__ == (object,)`. These are objectively checkable.
4. **File size minimums are reasonable.** strategy_prompts.py (80+), strategy_parser.py (60+), ai_strategy.py (120+), strategy_validator.py (120+). Not bloat — matches actual implementation complexity.
5. **Lazy import pattern preserved.** `_default_render` does `from kicad_agent.export.pcb_image_renderer import render_pcb_layer_png` inside the function so module load doesn't require PIL. Consistent with existing `vision_pipeline.py:90` pattern.

### Issues

#### [M-1] Backend value translation mechanism ambiguous — MEDIUM
- **Severity:** Medium
- **Location:** Plan 01 Task 3, `_translate_to_result` action description
- **Description:** Plan specifies "If model provided a value AND it matches a RouterBackend enum value (case-insensitive `RouterBackend(value.lower())`), use it. Else, default to RouterBackend.ASTAR." Verified at runtime: `RouterBackend("magic_router")` raises `ValueError`, NOT silently returns None. The plan does not show the try/except that must wrap this lookup.
- **Risk:** Executor may write `backend = RouterBackend(val.lower())` without try/except, causing `_translate_to_result` to raise on unknown backend strings — which would then be caught by R-6 fallback even though the model output was otherwise valid JSON. This would inflate the fallback rate and confound SC-1/SC-2 metrics.
- **Fix:** Add explicit try/except in the action description:
  ```python
  try:
      backend = RouterBackend(val.lower())
  except ValueError:
      logger.warning("Unknown backend %r, defaulting to ASTAR", val)
      backend = RouterBackend.ASTAR
  ```
- **Confidence:** 0.95 (verified Python semantics at runtime)

**Code Decision: APPROVE** (M-1 is an implementation clarity issue, not a plan-blocking design flaw — executor will catch via failing Test 5 if implemented wrong)

---

## Security Review (Rick C-137 + Sentinel Rick)

**Status:** PASS (with 1 HIGH finding on audit trail gap)

### Threat Model Coverage

The plans include STRIDE threat registers in all three PLAN.md files. This is above baseline for GSD plans. Sentinel Rick reviewed for agentic AI-specific threats since this phase integrates an LLM into the routing pipeline.

### Issues

#### [H-1] Fallback `routing_notes` does NOT reach the durable audit trail — HIGH
- **Severity:** High
- **Category:** Repudiation / Audit Trail Integrity
- **Location:** Plan 02 Task 2 (R-6 fallback wiring) + Plan 02 threat register T-98-02-06
- **Description:**

  The plans repeatedly claim that prefixing fallback notes with `ai_fallback:` provides "audit trail grepability." Examples:
  - Plan 02 Task 2 acceptance: `grep -q "ai_fallback:" src/kicad_agent/routing/ai_strategy.py (routing_notes prefix for audit trail)`
  - Plan 02 threat T-98-02-06: "Audit trail (Phase 100) captures routing_notes with 'ai_fallback:' prefix"
  - Plan 02 threat T-98-02-05: "routing_notes records the failure reason"

  **Verified against source:** `RoutingOrchestrator.route_board()` (orchestrator.py:247-331) calls `strategy.strategize(board_state, netlist)` to get a `RoutingStrategyResult`, then dispatches per-net and writes `RoutingAuditEntry` records. The audit entry schema (`audit.py:33`) captures `strategy=type(strategy).__name__` (the class name) and per-net `notes` (the dispatch reason), but **`strategy_result.routing_notes` is never written to the JSONL audit log**.

  The only place `ai_fallback:` lands is:
  1. Python `logger.warning()` output (ephemeral — not durable)
  2. The in-memory `RoutingStrategyResult.routing_notes` field (discarded after dispatch)

  **Threat scenario:** If an AI-routed board fails DRC in production, a reviewer inspecting `.kicad-agent/audit/routing_*.jsonl` sees only `"strategy": "AiRoutingStrategy"` with no indication that the AI path errored and fell back to deterministic. They cannot distinguish "AI strategy applied successfully" from "AI failed, deterministic took over." This breaks post-hoc analysis and any future safety investigation.

- **Fix Options (any one is acceptable):**

  **Option A (preferred — fits existing plans):** Add a NOTE in Plan 02 acknowledging the limitation and file an out-of-scope Bead:
  ```
  Title: "Phase 98 audit gap — routing_notes not persisted"
  Labels: out-of-scope, council-deferred, high
  Description: "RoutingOrchestrator does not write strategy_result.routing_notes
  to the JSONL audit trail. The ai_fallback: prefix is only visible in Python
  logger.warning. Fix requires modifying Phase 100 orchestrator (out of scope
  for Phase 98). Until fixed, audit trail grep for 'ai_fallback:' MUST target
  Python logs, not the JSONL audit file."
  ```

  **Option B (small plan amendment):** Modify Phase 100 `RoutingAuditEntry` to accept a top-level `strategy_notes` field and write `strategy_result.routing_notes` once at the start of dispatch (before the per-net loop). This is a 4-line orchestrator change and a 1-line audit schema change. Would require a Phase 100 regression check.

  **Option C (Phase 98-only):** Plan 02 Task 2 adds a side-channel audit writer that opens `.kicad-agent/audit/strategy_*.jsonl` and logs the full `RoutingStrategyResult` (including routing_notes) at strategize time. This is a smaller blast radius than touching Phase 100 but adds a second audit file.

- **Confidence:** 0.98 (verified by reading orchestrator.py:247-331 and audit.py:33)

#### [T-98-01-02] Safe default direction — Informational (confirmed correct)
- The plan defaults unknown backends to `RouterBackend.ASTAR`. Sentinel Rick confirms ASTAR is the correct lowest-privilege default — A* is in-house deterministic code; Freerouting is an external Java subprocess. The model cannot escalate to Freerouting without producing an exact enum string match.

**Security Decision: APPROVE** with H-1 requiring resolution (Option A minimum — Bead filed before execution starts)

---

## Apple Platform Review (Apple Elitist Rick)

**Status:** PASS

This phase runs Gemma 4 12B via mlx-vlm on Apple Silicon. Apple-specific concerns:

1. **MLX is the correct backend.** mlx-vlm 0.6.3 is Apple-native, matches training environment (RESEARCH.md Standard Stack). Using transformers + accelerate would require CUDA and break the Apple Silicon deployment story.
2. **Model loading is lazy and isolated.** `KiCadVisionPipeline.__init__` calls `_load_model(config)` which imports mlx_vlm inside the method. Module load does NOT trigger the 23.8 GB model load — only pipeline instantiation does. Unit tests mock the pipeline and never load the model.
3. **Memory pressure is documented.** RESEARCH.md Pitfall 5 documents 23.8 GB load, 5.6 tok/s generation, ~6 min per 2048-token generation. Plan 01 sets `max_tokens=2048` via KiCadVisionConfig default (verified vision_pipeline.py:41). Plan 03 integration tests are marked `@pytest.mark.integration` and skip when mlx_vlm unavailable.
4. **No deprecated APIs.** Pure Python + mlx-vlm + Pillow + kicad-cli subprocess. No OpenGL ES, no UIWebView, no GCGamepad.

**Apple Decision: APPROVE**

---

## PCB Design Review (KiCad Rick)

**Status:** PASS

The phase does not modify `.kicad_pcb` files directly — all mutation flows through the Phase 100 orchestrator, which uses `PersistentUndoStack` with pre/post snapshots. Validated:

1. **Fixture selection is appropriate.** `smd_test_board.kicad_pcb` (2-layer, ~50% baseline), `RaspberryPi-uHAT.kicad_pcb` (2-layer, ~3.2% baseline), `phase99_synthetic_4layer_mixedsignal.kicad_pcb` (4-layer, has zones). All three exist (verified). The 4-layer fixture exercises the `In3.Cu on 2-layer` rejection logic in Plan 02 Test 16.
2. **Fixture protection is explicit.** Plan 03 Task 2 acceptance criterion: `grep -q "shutil.copy" scripts/phase98_eval.py`. The CLI copies fixtures to `tempfile.TemporaryDirectory()` before routing because the orchestrator mutates PCB in place. This is critical — without it, the eval harness would corrupt checked-in fixtures.
3. **DRC verification is mandatory.** Plan 03 `run_drc` invokes `kicad-cli pcb drc` via subprocess, parses unconnected count, and surfaces it in `StrategyEvalResult`. SC-3 ("Zero DRC regressions") is enforced by comparing `drc_pass` between AI and deterministic runs.
4. **NativeBoard layer access is correct.** Plan 02 Task 1 uses `board.setup.stackup.layers` (typed, has `.type` field) with fallback to `board.general.layers` (untyped strings via regex `^(F|B|In\d+)\.Cu$`) with final fallback to `{F.Cu, B.Cu}` default. Verified against `pcb_native_types.py:296-391`.

**KiCad Decision: APPROVE**

---

## Testability Review (Test Rick)

**Status:** PASS (with 1 MEDIUM finding on coverage gap)

### Strengths

1. **Test counts are calibrated.** Plan 01: 8+10+9 = 27 tests. Plan 02: 24 (validator) + 11 (fallback/determinism) = 35 tests. Plan 03: 11 unit + 4 integration. Total: 77+ tests across the phase. Coverage of edge cases is comprehensive.
2. **Mocking strategy is correct.** `KiCadVisionPipeline` is mocked via `unittest.mock.MagicMock` in all unit tests. Real model (23.8 GB) only loads in `@pytest.mark.integration` tests, which are opt-in via `pytest.importorskip("mlx_vlm")` + `shutil.which("kicad-cli")` skip guards.
3. **`integration` marker is already registered.** Verified `pyproject.toml:85`: `"integration: marks tests as integration tests requiring external tools (kicad-cli, Freerouting)"`. Plan 03 Task 2 correctly notes "Phase 100 may have already added this — check first, only add if missing."
4. **Regression coverage is explicit.** Plan 01, 02, 03 all include `pytest tests/test_phase100_*.py tests/test_routing*.py -q` in verification steps. "Zero regression tolerated" is stated in VALIDATION.md:108.

### Issues

#### [M-2] Plan 01 missing Test for `_translate_to_result` net_priorities filtering — MEDIUM
- **Severity:** Medium
- **Location:** Plan 01 Task 3, Test list (Tests 1-9)
- **Description:** The `_translate_to_result` action says: "`net_priorities`: `tuple(parsed.get("net_priorities", []))`. Filter to nets present in netlist (drop unknowns — test 6)." But Test 6 is about `router_assignment` extra nets, not `net_priorities` filtering. There is no test that verifies unknown nets in `net_priorities` are dropped during translation.
- **Risk:** If the executor forgets the filter, unknown nets in `net_priorities` would slip through to the orchestrator. The H4 gate doesn't check `net_priorities` (only `router_assignment`). R-4 (`StrategyValidator._validate_net_references`) DOES check `net_priorities` — so R-4 would catch it and trigger fallback. Net effect: fallback rate inflated, but no bad data reaches execution. Still, the unit test should exist to verify the translator's contract directly.
- **Fix:** Add Test 10 to Plan 01 Task 3:
  ```
  Test 10 (R-3 — net_priorities filtering): Given model JSON with
  net_priorities=["GND", "VCC", "PHANTOM_NET"], and netlist with only GND+VCC,
  result.net_priorities == ("GND", "VCC") — PHANTOM_NET dropped.
  ```

#### [L-1] conftest_phase98.py not in any plan's files_modified — LOW
- **Severity:** Low
- **Location:** VALIDATION.md:67 lists `tests/conftest_phase98.py` as Wave 0 gap, but no plan includes it in `files_modified` frontmatter.
- **Description:** The shared fixtures (mock pipeline, mock image, synthetic board_state) need to live somewhere. Plans 01/02/03 each create their own test files but none claims ownership of the conftest.
- **Fix:** Either (a) add `tests/conftest_phase98.py` to Plan 01 Task 1 `files_modified`, or (b) have each test file define its own fixtures inline. Option (a) is cleaner.

**Testability Decision: APPROVE** (M-2 and L-1 should be addressed during execution but do not block plan approval)

---

## Eval Harness Review (Dufus Rick + Performance Monitor)

**Status:** PASS

### SC-1 through SC-5 Evaluator Coverage

| SC | Description | Evaluator | Threshold | Verdict |
|----|-------------|-----------|-----------|---------|
| SC-1 | Model emits parseable JSON ≥95% | `evaluate_sc1(results)` returns float parse_success rate | ≥ 0.95 | Covered |
| SC-2 | AI beats deterministic on ≥2 of 3 metrics | `evaluate_sc2(det, ai)` returns list of winning metric names | ≥ 2 of {completion_pct, via_count, trace_length} | Covered |
| SC-3 | Zero DRC regressions | `evaluate_sc3(det, ai)` returns bool | `ai.drc_pass >= det.drc_pass` | Covered |
| SC-4 | Validation rejects 100% synthetic invalid | Plan 02 Test 21 (batch of 10) | 100% rejection | Covered |
| SC-5 | E2E on ≥3 fixtures | `evaluate_sc5(results)` returns int distinct fixtures | ≥ 3 | Covered |

### Issues

#### [M-3] SC-2 metric direction for via_count and trace_length not explicit in evaluator — MEDIUM
- **Severity:** Medium
- **Location:** Plan 03 Task 2, `evaluate_sc2` action description
- **Description:** Plan says "via_count (lower better), total_trace_length_mm (lower better)" in the action text but the evaluator function signature `evaluate_sc2(det, ai)` doesn't specify how ties are handled. If `ai.via_count == det.via_count`, does that count as "AI beats"? The success criterion SC-2 says "matches or beats" in CONTEXT.md:50 but Plan 03 action says "beats."
- **Fix:** Clarify in `evaluate_sc2` docstring: "Returns list of metric names where AI is at least as good as deterministic (`<=` for via_count/trace_length, `>=` for completion_pct). Ties count as 'matches or beats' per SC-2 wording in CONTEXT.md."

#### [M-4] SC-1 denominator excludes fallback cases — MEDIUM
- **Severity:** Medium
- **Location:** Plan 03 Task 2, `evaluate_sc1` action description
- **Description:** Plan formula: `sum(1 for r in results if r.parse_success) / sum(1 for r in results if r.strategy_name == "AiRoutingStrategy")`. But `parse_success=False` is set when fallback occurs (Plan 03 Task 1 Test 8). So the denominator counts all AI runs, numerator counts non-fallback runs. This is correct for measuring parse success rate. However, if the model consistently fails to parse, SC-1 fails AND the orchestrator still routes (via fallback). The eval harness should surface both numbers: parse_success rate (SC-1) AND fallback rate (diagnostic).
- **Fix:** Add `fallback_rate` to StrategyEvalResult or compute it in the SC summary. The plan's `--json` output already includes sc1-sc5; adding `fallback_rate` as a diagnostic metric would help interpret SC-1 failures.

**Eval Decision: APPROVE**

---

## Compliance & Safety Review (Compliance Rick)

**Status:** PASS

This phase produces routing strategy consumed by an automated orchestrator that mutates PCB files. Safety review confirms:

1. **No irreversible actions without validation.** Every model-emitted coordinate (in keepouts) is validated against `board_bounds` (Plan 02 Test 1-8). Every net reference is validated against netlist (Test 9-14). Every layer is validated against stackup (Test 15-20).
2. **Rollback is verified infrastructure.** Phase 100 `PersistentUndoStack` (referenced in orchestrator.py:322) provides pre/post snapshots with `op_type=_OP_TYPE_ROUTE_POST`. AI strategy flows through the same rollback path as deterministic.
3. **DRC is mandatory post-route.** CONTEXT.md:66 "Never skip DRC — even with AI guidance, post-route DRC is mandatory." Plan 03 `run_drc` runs on every strategy result.
4. **Prompt injection defense.** The vision model output is treated as untrusted data, not instructions. Parser returns `{}` on any malformed input (Plan 01 Task 2). Translator applies safe defaults (Plan 01 Task 3). Validator rejects invalid semantic content (Plan 02 Task 1). Fallback catches any exception (Plan 02 Task 2). Four-layer defense.
5. **Blast radius contained.** AiRoutingStrategy only produces a `RoutingStrategyResult` (pure data). It does not execute commands, access credentials, or modify files. The orchestrator (Phase 100) is the only component that mutates the PCB, and it does so through its own validation + rollback.

**Compliance Decision: APPROVE**

---

## Fresh Eyes Review (Cross-Domain Specialists)

### `compliance-rick` (regulatory lens on ML safety)
- The "advisor not closed loop" reframe (CONTEXT.md:14) is the correct safety posture. An AI that suggests strategy consumed by a deterministic orchestrator with rollback is fundamentally safer than an AI that drives routing directly. This matches NIST AI RMF MANAGE-2 (safety mechanisms contain blast radius).
- The phase correctly treats the model as untrusted throughout. No path exists where model output reaches file mutation without passing through R-4 + H4 validation.

### `test-rick` (testability lens on eval design)
- The eval harness uses `shutil.copy2` to protect fixtures. This is the right pattern — orchestrator mutates in place, eval must not corrupt source-of-truth fixtures. Acceptance criterion includes grep check for `shutil.copy`.
- Integration tests are opt-in via marker + importorskip + skipif. Three layers of protection against accidentally loading the 23.8 GB model in CI.

---

## Final Council Decision

**Evil Morty's Ruling: APPROVE**

### Decision Summary

| Gate | Status |
|------|--------|
| SLC Validation (Slick Rick) | PASS |
| Security Review (Rick C-137 + Sentinel Rick) | PASS (H-1 requires Bead) |
| Code Quality (Rick Sanchez) | PASS |
| Design / Architecture (Rick Prime) | PASS |
| Apple Platform (Apple Elitist Rick) | PASS |
| PCB Design (KiCad Rick) | PASS |
| Testability (Test Rick + Dufus Rick) | PASS |
| Compliance & Safety (Compliance Rick) | PASS |
| Historical Context (Rickfucius) | ENRICHED |

### Findings Summary

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| H-1 | HIGH | Fallback routing_notes not in durable audit trail | Mitigate via Option A (Bead) or Option B (small Plan 02 amendment) before execution |
| H-2 | HIGH | mlx-vlm not declared in pyproject.toml | Add to Plan 01 or Plan 02 files_modified |
| M-1 | MEDIUM | Backend value translation try/except not explicit | Implementation clarity — executor will catch via failing Test 5 |
| M-2 | MEDIUM | Missing test for net_priorities filtering | Add Test 10 to Plan 01 Task 3 |
| M-3 | MEDIUM | SC-2 tie-breaking direction unclear | Clarify in evaluate_sc2 docstring |
| M-4 | MEDIUM | SC-1 lacks fallback_rate diagnostic | Add fallback_rate to --json output |
| L-1 | LOW | conftest_phase98.py ownership ambiguous | Add to Plan 01 Task 1 files_modified |
| L-2 | LOW | Requirement ID namespace collides with Phase 100 | Qualify IDs in future plans or add Phase 98 to REQUIREMENTS.md |

### Resolution Requirements (per bureaucracy.md §7.7)

All 8 findings require documented resolution before phase completion:

- **H-1, H-2**: Implement fix OR file deferred Bead with `council-deferred,high` labels and concrete resolution plan
- **M-1 through M-4**: Implement during execution (small amendments to plans or implementation)
- **L-1, L-2**: Implement during execution OR file deferred Bead with `council-deferred,low` labels

### Conditions for APPROVE

1. **Zero critical findings**: MET (0 critical)
2. **Zero unresolved HIGH blocking findings**: MET (both HIGH findings have pragmatic mitigations within plan scope)
3. **SLC gate passes**: MET
4. **All plans pass plan-checker**: VERIFIED (per task description — plan-checker already verified training data mismatch handling)
5. **Requirement coverage**: MET (R-1 through R-6 all mapped to plan tasks with tests)

### Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): APPROVE
- Rick C-137 (Security): APPROVE (with H-1 mitigation)
- Slick Rick (SLC): APPROVE
- Evil Morty (Synthesis): APPROVE

**Wave Beta (Wisdom):**
- Rick Prime (Design): APPROVE
- Rickfucius (Historian): APPROVE

**Wave Gamma (Domain):**
- `kicad-rick` (PCB): APPROVE
- `sentinel-rick` (Agent Security): APPROVE (with H-1 audit trail caveat)
- `apple-elitist-rick` (Apple Silicon MLX): APPROVE

**Wave Delta (Pipeline):**
- `gsd-plan-checker`: APPROVED (verified before Council — training data mismatch addressed)
- `architect` (System Design): APPROVE

**Wave Epsilon (Fresh Eyes):**
- `compliance-rick`: APPROVE
- `test-rick`: APPROVE

**Final: Evil Morty — APPROVE**

---

## Recommended Execution Adjustments (Non-Blocking)

These are suggestions for the executor, not conditions for approval:

1. **Plan 01 Task 1**: Add `tests/conftest_phase98.py` to `files_modified` and create it with shared mock pipeline fixture + synthetic board_state builder. (Addresses L-1)

2. **Plan 01 Task 3**: Add Test 10 for net_priorities filtering. Add explicit try/except code block in the action description for `RouterBackend(value.lower())`. (Addresses M-1, M-2)

3. **Plan 02 Task 2**: Before execution, file a Bead documenting the H-1 audit trail gap. Either accept the limitation (Option A) or amend the plan to add a `strategy_notes` field to Phase 100 `RoutingAuditEntry` (Option B — requires Phase 100 regression check).

4. **Plan 02 Task 2 or Plan 03**: Add `mlx-vlm==0.6.3` to `pyproject.toml [project.optional-dependencies]` under a `vision` extra. Add `pyproject.toml` to the plan's `files_modified`. (Addresses H-2)

5. **Plan 03 Task 2**: Clarify `evaluate_sc2` tie-breaking (ties count as "matches or beats"). Add `fallback_rate` to the `--json` output schema. (Addresses M-3, M-4)

---

## Review Metadata

- **Review duration:** ~45 minutes
- **Source files inspected:** strategy.py, orchestrator.py (lines 120-180, 250-331), vision_pipeline.py (lines 70-112), pcb_native_types.py (lines 296-391), audit.py, REQUIREMENTS.md, ROADMAP.md, pyproject.toml, all 3 PLAN.md files, CONTEXT.md, RESEARCH.md, VALIDATION.md
- **Runtime verification:** Python semantics for `dataclasses.replace`, `RouterBackend(value)` ValueError, Protocol structural subtyping
- **Council motto reminder:** "84 specialists. 6 waves. Zero compromises."
