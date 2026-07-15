# Volta v2 Evaluation Harness

## What this harness does

A Python evaluation harness that measures Volta v2 LoRA adapter quality against a 50-intent held-out test set. The harness loads adapter weights via PEFT+Transformers, runs inference on a GPU, scores predictions using 4 metrics (ERC pass rate, syntactic correctness, schema completeness, BLEU/ROUGE), and writes detailed reports. The result tells whether the v2 adapter is shippable (score >= 0.70) or whether Phase 248 (mlx-upgrade) is required.

## Hardware requirements

**Default:** NVIDIA A100 40GB or better (Vast.ai / Lambda Labs at $0.50-2/hr). 4-bit quantization (bitsandbytes) fits the 23.8GB Gemma-4-12B-IT base + LoRA adapter in <24GB VRAM with batch=1, max_new_tokens=512.

**Memory profile:** ~8.4GB VRAM for 4-bit case:
- Base model (4-bit): ~6.0 GB
- Adapter weights (FP16): ~0.5 GB
- KV cache (batch=1, 512 tokens): ~0.4 GB
- Activations + framework overhead: ~1.5 GB

**Fallback paths:**
- CPU fallback: `--device cpu --quantization none` (full FP16, ~2-4 minutes per case)
- Low VRAM: `--allow-low-vram` flag for GPUs <16GB (risky)

## How to run

```bash
# Install dependencies
pip install -r requirements-eval.txt

# Run full evaluation (50 cases)
python -m tests.eval.volta_v2_harness --output-dir output/

# Smoke test (2 cases, CPU)
python -m tests.eval.volta_v2_harness --limit 2 --device cpu --quantization none

# Offline mode (use HF cache only)
python -m tests.eval.volta_v2_harness --offline

# Use local adapter copy
python -m tests.eval.volta_v2_harness --adapter-path /path/to/local/adapter/
```

## Cost estimate

50 cases * ~5-30s each on A100 4-bit = ~5-25 min * $0.50-1.50/hr = $0.15-$0.60 per run. CPU fallback is ~2 minutes per case = ~100 minutes = ~$3-5 on CPU instances.

## How to interpret results

**Pass gate:** aggregate >= 0.70 (exit code 0); < 0.70 = FAIL (exit code 1)

**Aggregate formula:** 0.4*erc + 0.3*schema + 0.2*syntactic + 0.1*bleu_rouge

**Per-dimension breakdown:**
- ERC pass rate: 0.4 weight - measures electrical rule correctness
- Schema completeness: 0.3 weight - measures component/net coverage (F1 score)
- Syntactic correctness: 0.2 weight - measures valid Python generation
- BLEU/ROUGE vs gold: 0.1 weight - measures code similarity to reference

**Adversarial cases:** 4 special cases (BGA, multi-rail, differential pair, high-current) with `volta_v2_failure_mode: true` flag. These surface model weaknesses.

## How to extend

**Add cases to testset.json:**
- Edit `tests/eval/testset.json` - add entries with id, category, prompt, gold_reference, gold_skidl, required_components, required_nets, difficulty, rationale
- Categories: passive_rc, active, power, digital, connector, analog, protection
- Difficulty: easy (1-2 parts), medium (3-5 parts), hard (>5 parts)

**Add a metric to metrics.py:**
- Create function `my_metric(prediction: str, gold: Case) -> MetricResult`
- Return `MetricResult(score, error_class)` where score is 0.0-1.0
- Add to `evaluate_one()` in volta_v2_harness.py
- Add to aggregate formula if desired

**Add a category:**
- Add to category Literal in testset.py
- Add to testset.json entries
- Update stratification tests

## Error taxonomy reference

| Error class | Description |
|-------------|-------------|
| `model_timeout` | Inference exceeded 60s |
| `model_oom` | GPU out of memory |
| `model_emit_non_skidl` | Model emitted non-SKiDL Python text |
| `model_emit_syntax_error` | Model emitted invalid Python |
| `skidl_erc_failed` | Valid Python but ERC raised exception |
| `gold_erc_failed` | Gold standard error (construction time) |

## Report template

Output files:
- `output/volta-v2-eval-report.json` - Full JSON report with per-sample results
- `output/volta-v2-eval-summary.md` - Human-readable markdown summary

Report format (modeled on Phase 234 PARITY-REPORT.md):
- Base model, adapter, date, seed, device, quantization
- Pass gate status with aggregate score
- Aggregate scores by dimension
- Breakdown by category (N, ERC, Schema, Agg)
- Breakdown by difficulty (N, ERC, Schema, Agg)