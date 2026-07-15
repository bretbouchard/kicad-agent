# Phase 246 Plan 01: Python eval harness for Volta v2 adapter

Built a Python eval harness that measures Volta v2 LoRA adapter quality against a 50-intent held-out test set, independent of the Swift/MLX binding used by the macOS app. The harness loads the same `bretbouchard/volta-pcb-adapter-v2` weights via peft+transformers, runs inference on a GPU, scores against gold references, and writes a report. The result tells us whether the v2 adapter is shippable (score >= 0.70) or whether Phase 248 (mlx-upgrade) is required.

## Completed Tasks

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 0 | HF availability verification | c7622b4 | tests/eval/verify_hf_availability.py |
| 1 | Build 50-intent held-out test set | 0c5c3af | tests/eval/testset.py, tests/eval/testset.json |
| 2 | Implement 4 metric functions | 0c5c3af | tests/eval/metrics.py |
| 3 | Build eval harness runner | 0c5c3af | tests/eval/volta_v2_harness.py |
| 4 | requirements-eval.txt + docs/EVAL-HARNESS.md | (pre-existing) | requirements-eval.txt, docs/EVAL-HARNESS.md |
| 5 | Test fixes (collection, deps, skidl API, smoke mock) | d0463af | tests/eval/{conftest,testset,metrics,test_volta_v2_harness}.py |
| 6 | pytest filter for skidl unraisable warning | b33a2f4 | pytest.ini, tests/eval/conftest.py |

## Acceptance Criteria Results

| REQ | Statement | Status |
| --- | --------- | ------ |
| REQ-246-01 | 50 cases, 20/20/10, 7 categories (>=5 each), 4 adversarial | PASSED — 50 cases; categories: passive_rc=8, active=7, power=7, digital=7, connector=7, analog=7, protection=7; difficulty: 20/20/10; 4 adversarial |
| REQ-246-02 | 4 metric functions with exact algorithms | PASSED — `erc_pass_rate`, `syntactic_correctness`, `schema_completeness`, `bleu_rouge_vs_gold` |
| REQ-246-03 | Model loading: HF cache + 3-attempt retry + SHA256 + `--offline` | PASSED — `load_model_with_retry()` with backoff; SHA256 verify against `adapter_config.json` hash |
| REQ-246-04 | Hardware: 4-bit + A100 40GB default; CPU fallback | PASSED — `--device`, `--quantization` CLI flags; OOM halving; low-VRAM guard |
| REQ-246-05 | Pass gate: 0.4*erc + 0.3*schema + 0.2*syntactic + 0.1*bleu_rouge; >= 0.70 | PASSED — `aggregate_score()` + `is_pass()` + `PASS_GATE = 0.70` |
| REQ-246-06 | Error taxonomy (6 classes) | PASSED — `model_timeout`, `model_oom`, `model_emit_non_skid`, `model_emit_syntax_error`, `skidl_erc_failed`, `gold_erc_failed` |
| REQ-246-07 | Reproducibility (5 RNG seeds, default 42) | PASSED — `set_all_seeds()` covers torch, numpy, random, transformers |
| REQ-246-08 | Output: JSON + markdown report | PASSED — `write_report()` emits `volta-v2-eval-report.json` + `volta-v2-eval-summary.md` |
| REQ-246-09 | HF availability check (prerequisite) | PASSED — `verify_hf_availability.py` checks 5 required files + 524MB safetensors size |
| REQ-246-10 | Output directory auto-creation | PASSED — `os.makedirs(output_dir, exist_ok=True)` in main |

## Test Results

```
tests/eval/test_volta_v2_harness.py .................................. 28 passed in 4.41s
```

All 28 unit tests pass:
- 2 verify_hf_availability tests
- 7 testset loader tests
- 11 metrics tests
- 4 harness runner tests
- 4 verification tests (smoke, integration, etc.)

## Key Files Created

- `tests/eval/__init__.py` — Package init for eval tests
- `tests/eval/verify_hf_availability.py` — Task 0 prerequisite (HF file check)
- `tests/eval/testset.py` — TestCase + TestSet loader (with `__test__ = False` to prevent pytest collection)
- `tests/eval/testset.json` — 50 stratified test cases (8 categories >= 5, 20/20/10 difficulty, 4 adversarial)
- `tests/eval/metrics.py` — 4 metric functions + ERROR_TAXONOMY + aggregate_score + is_pass
- `tests/eval/volta_v2_harness.py` — main runner with set_all_seeds, load_model_with_retry, evaluate_one, write_report
- `tests/eval/test_volta_v2_harness.py` — 28 unit tests
- `tests/eval/conftest.py` — pytest config: collection ignore + warning filters
- `requirements-eval.txt` — pinned deps (rouge_score==0.1.2, nltk==3.9.1, etc.)
- `docs/EVAL-HARNESS.md` — usage docs (pre-existing)

## Key Files Modified

- `pytest.ini` — added `ignore::pytest.PytestUnraisableExceptionWarning` filter (skidl library leaks file handles during KiCad library load)

## Key Decisions

1. **skidl ERC API**: Use `skidl.ERC()` bound method, not `from skidl import erc` (which is the module, not callable). The `set_default_tool` import must be available in the sandbox namespace for the prediction script to call it.
2. **BLEU-4 requires >=4 tokens**: Identical strings shorter than 4 tokens have no 4-grams and method1 smoothing returns <1.0. The unit test uses an 8-token reference to validate the 1.0 path.
3. **Smoke test mocks model load**: `test_main_smoke` patches `load_model_with_retry` so the test never tries to download the 23.8GB base model. This is a plumbing smoke test, not an end-to-end inference test.
4. **TestSet/TestCase have `__test__ = False`**: Project `pytest.ini` has `python_classes = Test*` which causes pytest to try collecting these dataclasses. The opt-out flag prevents spurious collection warnings.

## Deviations from Plan

None material. The 4 commits after `0c5c3af` (d0463af, b33a2f4) are test infrastructure fixes (collection, missing deps, skidl API, smoke mock, pytest warning filter) required to verify the must-haves. They do not change the harness design.

## Outstanding / Deferred

- **End-to-end inference run on GPU**: Not run. Requires HF auth token + A100-class GPU. The plumbing is verified via `test_main_smoke`; the full 50-case run is the operation that needs to be executed on vast.ai with the actual v2 adapter.
- **CI integration**: Eval harness is not yet wired into CI. Recommended as a follow-up so a future model regression is caught automatically.

## Commits

- `c7622b4` feat(246-00): add HF availability verification with local fallback
- `0c5c3af` feat(246-01): eval harness core — test set, metrics, harness runner
- `d0463af` fix(246-01): test fixes for skidl erc, bleu-4, smoke mock
- `b33a2f4` fix(246-01): pytest filter for skidl unraisable warning
