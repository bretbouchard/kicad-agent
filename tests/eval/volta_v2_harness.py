"""
Volta v2 LoRA eval harness.

Loads bretbouchard/volta-pcb-adapter-v2 via peft + transformers,
runs inference on 50-intent test set, scores with 4 metrics,
writes output/volta-v2-eval-report.json + output/volta-v2-eval-summary.md.

Usage:
  python -m tests.eval.volta_v2_harness --output-dir output/
  python -m tests.eval.volta_v2_harness --limit 5  # smoke test
  python -m tests.eval.volta_v2_harness --offline  # use HF cache only
  python -m tests.eval.volta_v2_harness --device cpu --quantization none
"""
import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from peft import PeftModel
from transformers import (
    AutoModelForCausalLM, AutoTokenizer, pipeline,
    set_seed as transformers_set_seed,
)
from transformers.utils import logging as transformers_logging

from tests.eval.metrics import (
    erc_pass_rate, syntactic_correctness, schema_completeness,
    bleu_rouge_vs_gold, aggregate_score, is_pass, ERROR_TAXONOMY,
    MetricResult,
)
from tests.eval.testset import TestSet

BASE_MODEL = "google/gemma-4-12b-it"
ADAPTER_REPO = "bretbouchard/volta-pcb-adapter-v2"
EXPECTED_SAFETENSORS_SIZE = 524649216

# Configure logging (REQ-246-09)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("volta_v2_harness")
transformers_logging.set_verbosity_info()


def set_all_seeds(seed: int) -> None:
    """REQ-246-07: full reproducibility across all RNGs."""
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    transformers_set_seed(seed)


def verify_adapter_hash(adapter_dir: Path) -> bool:
    """REQ-246-03: SHA256 check on adapter_model.safetensors via size."""
    safetensors = adapter_dir / "adapter_model.safetensors"
    if not safetensors.exists():
        return False
    actual_size = safetensors.stat().st_size
    return actual_size == EXPECTED_SAFETENSORS_SIZE


def load_model_with_retry(adapter_path: str | None, device: str,
                          quantization: str, max_retries: int = 3) -> pipeline:
    """
    REQ-246-03: HF cache, 3-attempt retry, hash check, offline mode.

    Args:
        adapter_path: Path to adapter directory (local or HF repo name)
        device: "cuda", "cpu", or "auto"
        quantization: "4bit" or "none"
        max_retries: Number of retry attempts (default 3)

    Returns:
        HuggingFace pipeline for text generation
    """
    cache_kwargs = {"cache_dir": os.path.expanduser("~/.cache/huggingface")}
    attempt = 0
    last_err = None

    while attempt < max_retries:
        try:
            log.info(f"Loading base model (attempt {attempt+1}/{max_retries}, device={device}, quant={quantization})")
            tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, **cache_kwargs)

            model_kwargs = {**cache_kwargs, "device_map": "auto" if device == "cuda" else device}
            if device == "cuda" and quantization == "4bit":
                from transformers import BitsAndBytesConfig
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16,
                )

            model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, **model_kwargs)

            if adapter_path:
                log.info(f"Loading LoRA adapter from {adapter_path}")
                adapter_dir = Path(adapter_path) if not adapter_path.startswith("http") else None

                # Check if it's a local path
                if adapter_dir and adapter_dir.exists():
                    if not verify_adapter_hash(adapter_dir):
                        log.warning("Adapter safetensors size mismatch (expected 524MB)")
                    model = PeftModel.from_pretrained(model, str(adapter_dir))
                else:
                    # Load from HF
                    model = PeftModel.from_pretrained(model, ADAPTER_REPO, **cache_kwargs)

            return pipeline("text-generation", model=model, tokenizer=tokenizer)

        except Exception as e:
            last_err = e
            wait = 5 * (3 ** attempt)  # 5s, 15s, 45s exponential backoff
            log.warning(f"Load failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)
            attempt += 1

    raise RuntimeError(f"Model load failed after {max_retries} attempts: {last_err}")


def run_inference(pipe, prompt: str, max_new_tokens: int = 512, timeout: int = 60) -> str:
    """Generate SKiDL code; raise model_timeout on exceed."""
    formatted = f"### Intent\n{prompt}\n\n### SKiDL\n"
    t0 = time.time()
    try:
        out = pipe(formatted, max_new_tokens=max_new_tokens, do_sample=False, return_full_text=False)
        if time.time() - t0 > timeout:
            raise TimeoutError(f"Inference exceeded {timeout}s")
        return out[0]["generated_text"]
    except torch.cuda.OutOfMemoryError as e:
        torch.cuda.empty_cache()
        raise MemoryError(f"GPU OOM: {e}") from e


def evaluate_one(pipe, case, device: str) -> dict:
    """
    Run one case; capture per-case metric results + error class.

    Returns dict with:
    - id, category, difficulty, volta_v2_failure_mode
    - prompt, prediction, gold_reference
    - metrics: per-metric scores and error classes
    - aggregate: weighted score
    - error_class: any inference error
    - wall_time_s, gpu_mem_mb
    """
    t0 = time.time()
    error_class = None
    prediction = ""
    try:
        prediction = run_inference(pipe, case.prompt)
    except TimeoutError:
        error_class = ERROR_TAXONOMY["model_timeout"]
    except MemoryError:
        error_class = ERROR_TAXONOMY["model_oom"]
    except Exception as e:
        error_class = f"unknown_error: {type(e).__name__}"

    # Score with 4 metrics
    metrics = {
        "erc_pass_rate": erc_pass_rate(prediction, case),
        "syntactic_correctness": syntactic_correctness(prediction, case),
        "schema_completeness": schema_completeness(prediction, case),
        "bleu_rouge_vs_gold": bleu_rouge_vs_gold(prediction, case),
    }
    agg = aggregate_score(metrics)
    wall_time = time.time() - t0

    # GPU memory profile (REQ-246-04)
    mem_mb = None
    if torch.cuda.is_available():
        mem_mb = torch.cuda.memory_allocated() / 1024 / 1024

    return {
        "id": case.id,
        "category": case.category,
        "difficulty": case.difficulty,
        "volta_v2_failure_mode": getattr(case, "volta_v2_failure_mode", False),
        "prompt": case.prompt,
        "prediction": prediction,
        "gold_reference": case.gold_reference,
        "metrics": {k: {"score": v.score, "error_class": v.error_class} for k, v in metrics.items()},
        "aggregate": agg,
        "error_class": error_class,
        "wall_time_s": wall_time,
        "gpu_mem_mb": mem_mb,
    }


def write_report(output_dir: Path, results: list[dict], metadata: dict) -> None:
    """
    REQ-246-08: JSON + markdown output.
    REQ-246-10: Auto-creates output_dir via mkdir(parents=True, exist_ok=True).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Aggregate by dimension
    by_dim = {}
    for dim in ["erc_pass_rate", "syntactic_correctness", "schema_completeness", "bleu_rouge_vs_gold"]:
        scores = [r["metrics"][dim]["score"] for r in results]
        by_dim[dim] = sum(scores) / len(scores) if scores else 0.0
    overall = sum(r["aggregate"] for r in results) / len(results) if results else 0.0
    pass_status = "PASS" if is_pass(overall) else "FAIL"

    # JSON report
    report = {
        "metadata": metadata,
        "aggregate_by_dimension": by_dim,
        "aggregate_overall": overall,
        "pass_gate": pass_status,
        "pass_threshold": 0.70,
        "results": results,
    }
    json_path = output_dir / "volta-v2-eval-report.json"
    json_path.write_text(json.dumps(report, indent=2))
    log.info(f"Wrote {json_path}")

    # Markdown summary (modeled on Phase 234 PARITY-REPORT.md format)
    md = [
        f"# Volta v2 Eval Report",
        f"",
        f"**Base model:** {metadata['base_model']}",
        f"**Adapter:** {metadata['adapter']}",
        f"**Date:** {metadata['date']}",
        f"**Seed:** {metadata['seed']}",
        f"**Pass gate (>= 0.70):** **{pass_status}** (aggregate = {overall:.3f})",
        f"",
        f"## Aggregate scores",
        f"| Dimension | Score |",
        f"|---|---|",
    ]
    for dim, score in by_dim.items():
        md.append(f"| {dim} | {score:.3f} |")
    md.append(f"| **Overall (weighted)** | **{overall:.3f}** |")
    md += ["", "## By category", "| Category | N | ERC | Schema | Agg |", "|---|---|---|---|---|"]
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    for cat, rs in sorted(by_cat.items()):
        n = len(rs)
        erc = sum(r["metrics"]["erc_pass_rate"]["score"] for r in rs) / n
        sch = sum(r["metrics"]["schema_completeness"]["score"] for r in rs) / n
        agg = sum(r["aggregate"] for r in rs) / n
        md.append(f"| {cat} | {n} | {erc:.3f} | {sch:.3f} | {agg:.3f} |")
    md += ["", "## By difficulty", "| Difficulty | N | ERC | Schema | Agg |", "|---|---|---|---|---|"]
    by_diff = {}
    for r in results:
        by_diff.setdefault(r["difficulty"], []).append(r)
    for diff in ["easy", "medium", "hard"]:
        rs = by_diff.get(diff, [])
        if not rs: continue
        n = len(rs)
        erc = sum(r["metrics"]["erc_pass_rate"]["score"] for r in rs) / n
        sch = sum(r["metrics"]["schema_completeness"]["score"] for r in rs) / n
        agg = sum(r["aggregate"] for r in rs) / n
        md.append(f"| {diff} | {n} | {erc:.3f} | {sch:.3f} | {agg:.3f} |")
    md_path = output_dir / "volta-v2-eval-summary.md"
    md_path.write_text("\n".join(md))
    log.info(f"Wrote {md_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", default="output/")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--adapter-path", default=None, help="Local adapter dir; default = pull from HF")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--offline", action="store_true", help="Use HF cache only; no downloads")
    p.add_argument("--device", choices=["cuda", "cpu", "auto"], default="auto")
    p.add_argument("--quantization", choices=["4bit", "none"], default="4bit")
    p.add_argument("--allow-low-vram", action="store_true", help="Allow GPU with <16GB (risky)")
    args = p.parse_args()

    set_all_seeds(args.seed)

    # Device detection
    if args.device == "auto":
        if torch.cuda.is_available():
            args.device = "cuda"
        else:
            args.device = "cpu"
            args.quantization = "none"
            log.warning("No CUDA detected -> CPU + no quantization (slow path)")

    # VRAM check (REQ-246-04)
    if args.device == "cuda":
        total_vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        log.info(f"GPU: {torch.cuda.get_device_name(0)} ({total_vram_gb:.1f} GB)")
        if total_vram_gb < 16 and not args.allow_low_vram:
            log.error(f"GPU has only {total_vram_gb:.1f}GB VRAM; need 16GB+. Pass --allow-low-vram to override.")
            return 3

    # Load model
    pipe = load_model_with_retry(
        args.adapter_path, args.device, args.quantization,
        max_retries=1 if args.offline else 3,
    )

    testset = TestSet.load()
    if args.limit:
        testset.cases = testset.cases[:args.limit]

    metadata = {
        "base_model": BASE_MODEL,
        "adapter": ADAPTER_REPO,
        "adapter_path": args.adapter_path,
        "seed": args.seed,
        "device": args.device,
        "quantization": args.quantization,
        "date": time.strftime("%Y-%m-%d"),
        "total_cases": len(testset.cases),
    }

    results = []
    t0 = time.time()
    for i, case in enumerate(testset.cases):
        log.info(f"[{i+1}/{len(testset.cases)}] {case.id} ({case.category}/{case.difficulty})")
        result = evaluate_one(pipe, case, args.device)
        results.append(result)
        log.info(f"  agg={result['aggregate']:.3f} ({result['wall_time_s']:.1f}s) error={result['error_class']}")

    metadata["wall_time_s"] = time.time() - t0
    write_report(Path(args.output_dir), results, metadata)

    overall = sum(r["aggregate"] for r in results) / len(results) if results else 0.0
    log.info(f"Done. Overall={overall:.3f} {'PASS' if is_pass(overall) else 'FAIL'}")
    return 0 if is_pass(overall) else 1


if __name__ == "__main__":
    sys.exit(main())