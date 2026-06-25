---
phase: 98
slug: ai-routing-strategy-advisor
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-25
---

# Phase 98 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

Source: `98-RESEARCH.md` § Validation Architecture (lines 422+).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (existing) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_phase98_*.py -q -x` |
| **Full suite command** | `.venv/bin/python -m pytest tests/test_phase98_*.py tests/test_phase100_*.py tests/test_routing*.py -q` |
| **Estimated runtime** | ~20s unit, ~3min full, integration varies (model load + Freerouting) |

---

## Sampling Rate

- **After every task commit:** Run Phase 98 unit tests only. ~20 seconds.
- **After every wave merge:** Run Phase 98 + Phase 100 regression. ~3 minutes.
- **Phase gate:** Full suite green + opt-in integration tests (requires mlx-vlm + trained adapter + kicad-cli).

---

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Status |
|--------|----------|-----------|-------------------|-------------|
| R-1 | AiRoutingStrategy implements Protocol | unit | `pytest tests/test_phase98_ai_strategy.py::TestProtocolCompliance -x` | Wave 0 — new |
| R-2 | JSON extraction from free-text | unit | `pytest tests/test_phase98_strategy_parser.py -x` | Wave 0 — new |
| R-2 | Prompt includes schema + few-shot | unit | `pytest tests/test_phase98_ai_strategy.py::TestPromptConstruction -x` | Wave 0 — new |
| R-3 | Translator builds RoutingStrategyResult | unit | `pytest tests/test_phase98_ai_strategy.py::TestResultTranslation -x` | Wave 0 — new |
| R-4 | Reject out-of-bounds coordinates | unit | `pytest tests/test_phase98_strategy_validator.py::TestCoordinateBounds -x` | Wave 0 — new |
| R-4 | Reject unknown net names | unit | `pytest tests/test_phase98_strategy_validator.py::TestNetValidation -x` | Wave 0 — new |
| R-4 | Reject impossible layers (In3.Cu on 2-layer) | unit | `pytest tests/test_phase98_strategy_validator.py::TestLayerValidation -x` | Wave 0 — new |
| R-4 | 100% synthetic invalid rejection (SC-4) | unit | `pytest tests/test_phase98_strategy_validator.py::TestSyntheticInvalid -x` | Wave 0 — new |
| R-5 | Eval harness smoke test (mocked model) | unit | `pytest tests/test_phase98_eval.py::TestEvalHarnessSmoke -x` | Wave 0 — new |
| R-5 | AI vs deterministic comparison | integration | `pytest tests/test_phase98_eval.py::TestAiVsDeterministic -x -m integration` | Wave 0 — new |
| R-6 | Fallback on empty model output | unit | `pytest tests/test_phase98_ai_strategy.py::TestFallback -x` | Wave 0 — new |
| R-6 | Fallback on invalid JSON | unit | `pytest tests/test_phase98_ai_strategy.py::TestFallbackInvalidJson -x` | Wave 0 — new |
| R-6 | Fallback on validation failure | unit | `pytest tests/test_phase98_ai_strategy.py::TestFallbackValidationFail -x` | Wave 0 — new |
| SC-5 | End-to-end on 3 fixtures | integration | `pytest tests/test_phase98_eval.py::TestEndToEnd -x -m integration` | Wave 0 — new |

---

## Wave 0 Gaps (must land before implementation tasks)

Per TDD discipline, these test files must exist before implementation:

- `tests/test_phase98_ai_strategy.py` — R-1, R-2, R-3, R-6 unit tests
- `tests/test_phase98_strategy_validator.py` — R-4 validation gate tests (SC-4)
- `tests/test_phase98_strategy_parser.py` — R-2 JSON extraction tests
- `tests/test_phase98_eval.py` — R-5 eval harness (unit + integration)
- `tests/conftest_phase98.py` — shared fixtures (mock pipeline, mock image, synthetic board_state)
- `integration` pytest marker registered in pyproject.toml (Phase 100 added it — verify)

---

## Critical Constraint: Training Data Mismatch

The trained adapter was trained on 6696 samples of FREE-TEXT PCB analysis. **Zero samples contain routing strategy JSON.** This phase must:

1. **Few-shot prompting** — prompt includes explicit JSON schema + 2+ exemplars
2. **Robust JSON extraction** — handle markdown fences, bare JSON, brace matching, partial output
3. **R-6 deterministic fallback** — broad `except Exception` falls back to `DeterministicStrategy().strategize()` with `ai_fallback:` routing_notes prefix
4. **Realistic SC-1 expectations** — 95% parseable may be hard to hit; fallback exists for this reason

---

## Integration Test Opt-In

Integration tests are gated to avoid breaking unit test runs:

```python
@pytest.mark.integration
class TestEndToEnd:
    pipeline = pytest.importorskip("mlx_vlm")  # skip if mlx-vlm missing
    if not shutil.which("kicad-cli"):
        pytest.skip("kicad-cli required for DRC verification")
```

Unit tests mock `KiCadVisionPipeline.generate_from_image` to avoid model load (~30s) during TDD cycles.

---

## Regression Coverage

Phase 98 extends Phase 100 infrastructure. These suites MUST remain green:

- `tests/test_phase100_strategy.py` — Protocol contract
- `tests/test_phase100_orchestrator.py` — H4 validation still works with AI strategy plugged in
- `tests/test_phase100_dispatch.py` — DeterministicStrategy fallback path exercised by R-6
- `tests/test_phase100_audit.py` — AI strategy entries land in audit trail correctly

Zero regressions tolerated.
