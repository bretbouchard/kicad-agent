---
phase: 246
reviewed: 2026-07-15
depth: standard
files_reviewed: 10
files_reviewed_list:
  - tests/eval/__init__.py
  - tests/eval/verify_hf_availability.py
  - tests/eval/testset.py
  - tests/eval/metrics.py
  - tests/eval/volta_v2_harness.py
  - tests/eval/test_volta_v2_harness.py
  - tests/eval/conftest.py
  - pytest.ini
  - .planning/phases/246-volta-v2-eval-harness/246-01-PLAN.md
  - .planning/phases/246-volta-v2-eval-harness/246-01-SUMMARY.md
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
resolved_in_commit: 12912f5
status: clean
---

# Phase 246: Code Review Report

**Reviewed:** 2026-07-15
**Depth:** standard
**Files Reviewed:** 10
**Status:** findings

## Summary

Review of Phase 246 Volta v2 eval harness reveals a critical security vulnerability in the sandbox implementation, plus timing and reliability issues. The code passes all 28 unit tests but contains a fundamental security flaw that allows arbitrary code execution through the `exec()` sandbox.

## Critical Issues

### CR-01: Insecure sandbox allows arbitrary code execution

**File:** `tests/eval/metrics.py:88-104`
**Issue:** The `erc_pass_rate()` function executes untrusted model prediction code in a "sandbox" namespace, but the namespace includes `__builtins__` which gives the code full access to Python's built-in functions including `__import__`, `open`, `eval`, `exec`, `print`, etc. This completely defeats the sandboxing purpose.

An attacker-controlled or malicious model output could execute arbitrary code:
```python
# Example malicious prediction that would execute:
__import__('os').system('rm -rf /')  # System command execution
open('/etc/passwd').read()            # File read access
__import__('subprocess').run(['malicious_command'])  # Subprocess execution
```

The function comment states "Execute in sandboxed namespace" but the implementation is not a sandbox—it's just a limited namespace with full builtins access.

**Fix:**
```python
# Remove __builtins__ and create a minimal safe builtins dict:
safe_builtins = {
    'True': True,
    'False': False,
    'None': None,
    'print': print,  # Only if needed for debugging
}
ns = {
    "Part": Part,
    "Net": Net,
    "generate_netlist": generate_netlist,
    "ERC": ERC,
    "KICAD": KICAD,
    "set_default_tool": set_default_tool,
    "__builtins__": safe_builtins,  # Minimal builtins only
}
```

Or use a proper sandbox library like `RestrictedPython` or operate the prediction in a subprocess with resource limits.

## Warnings

### WR-01: Timeout check is post-hoc, not enforced during execution

**File:** `tests/eval/volta_v2_harness.py:129-140`
**Issue:** The timeout check in `run_inference()` happens after `pipe()` completes:
```python
out = pipe(formatted, max_new_tokens=max_new_tokens, do_sample=False, return_full_text=False)
if time.time() - t0 > timeout:
    raise TimeoutError(f"Inference exceeded {timeout}s")
```
If the HuggingFace pipeline hangs indefinitely (network issue, GPU stall), the timeout will never trigger. The check needs to happen during execution, not after.

**Fix:** Use HuggingFace's `transformers` timeout parameter or run inference in a thread with timeout:
```python
import threading

def run_inference_with_timeout(pipe, prompt, timeout, max_new_tokens):
    result = [None]
    exception = [None]
    def target():
        try:
            result[0] = pipe(formatted, max_new_tokens=max_new_tokens, do_sample=False, return_full_text=False)
        except Exception as e:
            exception[0] = e
    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise TimeoutError(f"Inference exceeded {timeout}s")
    if exception[0]:
        raise exception[0]
    return result[0]
```

### WR-02: Size-based verification is fragile

**File:** `tests/eval/metrics.py:60-62`, `tests/eval/verify_hf_availability.py:60-62`
**Issue:** The adapter verification uses exact byte-size comparison:
```python
if actual_size != EXPECTED_SAFETENSORS_SIZE:
    print(f"  WARNING: Size mismatch!")
    return 2
```
Model files can be rebuilt, re-optimized, or differ due to compression tools between environments. A 524,649,216-byte file in one environment might be 524,649,220 bytes in another due to filesystem padding, different safetensors version, or build tool differences.

**Fix:** Use SHA256 hash verification instead of size:
```python
import hashlib

def verify_adapter_hash(adapter_dir: Path) -> bool:
    safetensors = adapter_dir / "adapter_model.safetensors"
    if not safetensors.exists():
        return False
    # Compute and compare SHA256 hash instead of size
    # Expected hash would be documented in REQ-246-03
    sha256_hash = hashlib.sha256(safetensors.read_bytes()).hexdigest()
    expected_hash = "expected-sha256-hash-here"
    return sha256_hash == expected_hash
```

## Info

### IN-01: Error taxonomy naming inconsistency

**File:** `tests/eval/metrics.py:46`
**Issue:** The error class `model_emit_non_skid` contains a typo—should be `model_emit_non_skidl` to match the tool name "SKIDL" used elsewhere in the codebase.

**Fix:**
```python
# Line 46: Change from
"model_emit_non_skid": "Model emitted text that wasn't Python"
# To
"model_emit_non_skidl": "Model emitted text that wasn't SKIDL Python"
```
Update references in `run_inference()` and all tests accordingly.

---

## Security Considerations (sandbox design)

The user context notes that `exec()` sandbox is intentional for eval harness purposes. However, the current implementation is **not a secure sandbox**. The inclusion of `__builtins__` gives executed code access to:

| Function | Risk |
|----------|------|
| `__import__` | Import any Python module, including `os`, `subprocess`, `socket` |
| `open` | Read/write arbitrary files |
| `eval`/`exec` | Nested code execution |
| `compile` | Compile and execute code strings |
| `globals`/`locals` | Inspect/modify namespace |
| `getattr`/`setattr` | Object introspection/manipulation |
| `breakpoint` | Debug console access |

For an evaluation harness that processes untrusted model output, this poses a real security risk, especially in shared or cloud environments.

---

_Reviewed: 2026-07-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_