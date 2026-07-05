"""Filter SchGen-converted SKIDL examples to only keep executable ones.

Runs each converted example through the Python interpreter and keeps only
those that execute successfully. This ensures the training data teaches
the model to generate code that actually runs.

Usage:
    python3 filter_executable.py \
        --in  converted/schgen_skidl_sft_filtered.jsonl \
        --out converted/schgen_skidl_sft_executable.jsonl \
        --workers 8 \
        --timeout 10
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def test_executable(code: str, timeout: int) -> tuple[bool, str]:
    """Test if SKIDL code is executable. Returns (success, error_category)."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=timeout,
        )
        Path(tmp_path).unlink(missing_ok=True)
        if result.returncode == 0:
            return True, "ok"
        # Categorize the error
        stderr = result.stderr
        if "NoneType" in stderr:
            return False, "pin_access_none"
        elif "Unable to find part" in stderr:
            return False, "part_not_found"
        elif "KeyError" in stderr:
            return False, "pin_keyerror"
        elif "ImportError" in stderr:
            return False, "import_error"
        else:
            return False, "other"
    except subprocess.TimeoutExpired:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return False, "timeout"
    except Exception as e:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return False, f"error:{type(e).__name__}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--rejects", default="", help="Optional: write rejected examples here")
    args = ap.parse_args()

    inp = Path(args.inp)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    rejects_path = Path(args.rejects) if args.rejects else None

    with inp.open() as f:
        all_examples = [json.loads(line) for line in f]

    # Filter to non-empty examples first
    candidates = [ex for ex in all_examples if ex.get("stats", {}).get("n_components", 0) > 0]
    print(f"Loaded {len(all_examples)} examples ({len(candidates)} non-empty)",
          file=sys.stderr)

    def test_one(ex):
        code = next(m["content"] for m in ex["messages"] if m["role"] == "assistant")
        ok, cat = test_executable(code, args.timeout)
        return ok, cat, ex

    kept = 0
    rejected_by_cat: dict[str, int] = {}
    rejected_examples: list = []

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(test_one, ex) for ex in candidates]
        results = []
        for i, future in enumerate(as_completed(futures), 1):
            ok, cat, ex = future.result()
            results.append((ok, cat, ex))
            if i % 500 == 0:
                rate = i / (time.time() - t0)
                eta = (len(candidates) - i) / rate
                print(f"  [{i}/{len(candidates)}] kept={kept} "
                      f"({rate:.1f}/s, ETA {eta:.0f}s)", file=sys.stderr)

    # Sort back to original order
    results.sort(key=lambda r: candidates.index(r[2]))

    with out.open("w") as fo:
        for ok, cat, ex in results:
            if ok:
                fo.write(json.dumps(ex) + "\n")
                kept += 1
            else:
                rejected_by_cat[cat] = rejected_by_cat.get(cat, 0) + 1
                if rejects_path:
                    ex["_reject_reason"] = cat
                    rejected_examples.append(ex)

    elapsed = time.time() - t0
    total = len(results)
    print(f"\nDone in {elapsed:.0f}s ({elapsed/60:.1f} min)", file=sys.stderr)
    print(f"  Input:     {total}", file=sys.stderr)
    print(f"  Kept:      {kept} ({kept/total*100:.1f}%)", file=sys.stderr)
    print(f"  Rejected:  {total - kept} ({(total-kept)/total*100:.1f}%)", file=sys.stderr)
    print(f"\nRejection breakdown:", file=sys.stderr)
    for cat, count in sorted(rejected_by_cat.items(), key=lambda x: -x[1]):
        print(f"  {cat:25s} {count:5d} ({count/total*100:.1f}%)", file=sys.stderr)

    if rejects_path and rejected_examples:
        with rejects_path.open("w") as fr:
            for ex in rejected_examples:
                fr.write(json.dumps(ex) + "\n")
        print(f"\nRejects written to {rejects_path}", file=sys.stderr)

    print(f"\nOutput: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
