# Council of Ricks: All Hands Deep-Dive Audit

**Project:** kicad-agent
**Date:** 2026-05-28
**Mode:** All Hands (6 specialists)
**Verdict:** CONDITIONAL PASS -- 5 Critical, 12 High, 23 Medium, 16 Low

---

## Executive Summary

kicad-agent is a 44K-line Python project implementing structural editing of KiCad EDA files with an LLM-driven operation pipeline, SFT/GRPO training, and MCP integration. The core architecture (parser, IR, operations, handler, serializer) is sound, and transactional integrity is robust. The project has 2737 tests across 106 files.

However, the Council identified **56 findings** across 6 review dimensions. The most urgent issues are:

1. **3 SLC violations** -- stubs and phantom operations that advertise capability but fail at runtime
2. **1 critical path traversal bypass** in the CLI route subcommand
3. **Prompt-to-schema mismatches** that will cause LLM agents to generate invalid operations
4. **Training pipeline integrity gaps** -- circular evaluation, dead KL divergence, no real data validation

---

## CRITICAL (5) -- Must Fix Before Any Production Use

### C-1. Path Traversal Bypass in CLI `route` Subcommand
**File:** `cli.py:389` | **CVSS:** 9.1

The `_handle_route` function passes an absolute user-supplied path as `target_file`, bypassing the `TargetFile` validator's rejection of absolute paths. `Path("/project") / "/etc/passwd"` resolves to `/etc/passwd` on POSIX, allowing arbitrary file read/write.

**Fix:** Add project directory confinement check in `OperationExecutor.execute()` verifying `file_path.resolve().is_relative_to(self._base_dir.resolve())`.

### C-2. `add_bus` / `remove_bus` Raise NotImplementedError
**File:** `ops/executor.py:230,235` | **Category:** SLC Stub

Full Pydantic schemas, documented in prompt.md and README, but handlers immediately crash. LLM agents following documentation will construct valid JSON that passes validation then fails at execution.

**Fix:** Either implement or remove from schema + prompt.md + README.

### C-3. `validate_footprint` Always Returns True
**File:** `ops/executor.py:182,375` | **Category:** SLC Stub

Unconditionally returns `{"valid": True}` without checking any library. LLM agents trusting this to verify footprint existence before assignment will produce corrupted files.

**Fix:** Implement actual library lookup or remove the operation.

### C-4. S-expression Injection via Unsanitized `lib_id`
**File:** `ir/pcb_ir.py:626-633` | **Category:** Injection

`_inject_lib_id` interpolates `lib_id` into S-expressions via f-string without escaping. While Pydantic validates at input, internal callers bypassing Pydantic could inject arbitrary S-expression content. Same pattern in `_inject_pad_net` (line 729) and `_inject_layer` (line 666).

**Fix:** Use `_escape_sexpr_value` (already exists at line 673) for all interpolated values.

### C-5. `place_no_connects_from_erc` Documented But Missing from Schema
**File:** `skills/prompt.md:1332-1356` | **Category:** Phantom Operation

Documented with examples in prompt.md, referenced in README, but has no Pydantic model in schema.py and no executor handler. Any LLM following the prompt will generate operations that fail validation.

**Fix:** Add to schema or remove from documentation.

---

## HIGH (12) -- Fix Before Next Release

### H-1. No Hierarchical Sheet Operations
**File:** `ops/schema.py` (absent)

No `add_sheet`, `add_sheet_pin`, or sheet navigation operations. Real KiCad projects use hierarchical schematics -- the agent cannot construct or modify hierarchical designs.

### H-2. MCP Server Only Exposes Component Search, Not Operations
**File:** `mcp/server.py`

4 tools for JLCPCB search, but zero of the 51 editing operations are exposed as MCP tools. External AI agents can search components but cannot perform any structural editing.

### H-3. Exception Messages Leak to MCP Clients
**File:** `mcp/server.py:254`

Raw exception strings returned to callers leak file paths, module names, and config details. Use correlation IDs instead.

### H-4. No Prompt Injection Sanitization on LLM User Input
**File:** `llm/intent_parser.py:44`

User natural language passed directly to LLM without sanitization. `ContextBuilder.sanitize()` exists but is only applied to KiCad file content, not user descriptions.

### H-5. Unvalidated String Fields in S-expression Output
**File:** `ops/schema.py` (multiple)

`new_value` (ModifyPropertyOp), `name` (AddLabelOp, AddPowerOp), `value` (AddComponentOp), `condition` (AddDesignRuleOp) accept arbitrary strings flowing into S-expressions. No character validation for `(`, `)`, `"`, `\n`.

### H-6. Prompt-to-Schema Field Name Mismatches
**File:** `skills/prompt.md:1291` vs `schema.py:1101`

- `snap_to_grid`: prompt says `grid_size`, schema says `grid_mm`
- Multiple operations: prompt documents `erc_report_path` field that doesn't exist in schema

LLMs following prompt.md will generate operations with wrong field names.

### H-7. Bus Operations Have No Tests
**File:** `tests/` (absent)

`add_bus`/`remove_bus` raise NotImplementedError with zero tests verifying the exception path.

### H-8. Net-Short Detection Loop Body Is Dead Code
**File:** `ops/repair.py:202-208`

Wire propagation loop body is `pass`. Function only detects labels at identical positions, missing the most common short-circuit case (labels connected by wires).

### H-9. SKILL.md Claims "19 Operations" -- Actual Count Is 47
**File:** `skills/SKILL.md:31`

Three conflicting operation counts: SKILL.md says 19, README says 46, prompt.md lists 48. None agree.

### H-10. Two Divergent GRPO Implementations, Neither Wired to Pipeline
**Files:** `grpo.py`, `grpo_trainer.py`, `pipeline.py`

Three training orchestration modules with different semantics. `pipeline.py` does pure supervised training. Neither GRPO implementation is called by the main pipeline. Dead KL divergence code in both.

### H-11. Best-of-N Degenerates Silently When Reward Model Unavailable
**File:** `inference/best_of_n.py:52-59`

Returns `chains[0]` with 0.5 composite score when reward model is None. Misleading quality metric.

### H-12. No End-to-End Integration Test for Core Pipeline
**File:** `tests/` (absent)

No test validates: LLM intent -> Operation JSON -> Executor -> IR mutation -> Serialize -> File output. This is the product's core value proposition.

---

## MEDIUM (23) -- Plan to Address

| # | Finding | File | Area |
|---|---------|------|------|
| M-1 | Cross-file infrastructure built but never wired to operations | `crossfile/atomic.py` | Architecture |
| M-2 | No undo/redo stack | `ir/transaction.py` | Architecture |
| M-3 | No remove operations for wires, labels, junctions | `ops/schema.py` | Operations |
| M-4 | No footprint creation operation (only create_symbol) | `ops/schema.py` | Operations |
| M-5 | Auto-router is single-layer only, no via placement | `routing/pathfinder.py` | Routing |
| M-6 | No connectivity/netlist query operation | `analysis/connectivity.py` | Operations |
| M-7 | No batch operation mode (one file I/O per operation) | `handler.py`, `executor.py` | Performance |
| M-8 | IR re-parsed from scratch on every operation | `executor.py:597` | Performance |
| M-9 | `schema.py` at 1381 lines exceeds 800-line limit | `ops/schema.py` | Code Quality |
| M-10 | 79 broad `except Exception` catches throughout codebase | Multiple | Error Handling |
| M-11 | `_SAFE_ID_PATTERN` duplicated across 4 files | 4 files | Code Quality |
| M-12 | `_fix_sheet_instances` is a no-op function | `format_convert.py:312` | Dead Code |
| M-13 | `n_complete` parameter in `best_of_n_select` is dead code | `best_of_n.py:34` | Dead Code |
| M-14 | Circular reward model evaluation (trained+evaluated on same synthetic data) | `pipeline.py:174-182` | Training |
| M-15 | PPO clip applied to advantages, not probability ratios | `grpo_trainer.py:79` | Training |
| M-16 | Reward model validation loss never computed | `reward_model.py:361-446` | Training |
| M-17 | `torch.float16` on MPS may produce NaNs during training | `sft/trainer.py:189` | Training |
| M-18 | GRPO RNG reset each step reduces exploration diversity | `grpo.py:258` | Training |
| M-19 | Template selection always returns "spatial_reasoning" | `templates.py:43-56` | Training |
| M-20 | 3 unused task templates in templates.py | `templates.py` | Dead Code |
| M-21 | Core schematic ops (add_wire, add_label, add_power) have no executor tests | `tests/` | Testing |
| M-22 | Serializer modules have no direct unit tests | `tests/` | Testing |
| M-23 | README training section not reproducible | `README.md:397-410` | Documentation |

---

## LOW (16) -- Consider Fixing

| # | Finding | File |
|---|---------|------|
| L-1 | TOCTOU race in create file operations | `create_file.py:91-112` |
| L-2 | GitHub token stored as `self._token` | `crawler/github_discovery.py:126` |
| L-3 | Dependencies not pinned, no lockfile | `pyproject.toml` |
| L-4 | `assert best is not None` in production code | `best_of_n.py:79` |
| L-5 | Function-level `import re` in validators (called every validation) | `schema.py:47` |
| L-6 | `import dataclasses` repeated 4 times in executor.py | `executor.py:278-324` |
| L-7 | `except (ValueError, Exception)` redundant catch | `pipeline.py:122` |
| L-8 | 66 files use `Any` from typing | Multiple |
| L-9 | handler.py docstring says "does NOT execute mutations" -- it does | `handler.py:8-10` |
| L-10 | No version detection on file open | Parser modules |
| L-11 | Normalizer may drift from KiCad format | `serializer/normalizer.py` |
| L-12 | LLM client hardcoded to Anthropic, no provider abstraction | `llm/client.py` |
| L-13 | Copper zone has no polygon outline specification | `AddCopperZoneOp` |
| L-14 | Custom error types lost in generic handler catch | `handler.py:129-171` |
| L-15 | MCP rate limiter is global, not per-session | `mcp/server.py` |
| L-16 | `evaluation.py:run_ablation` is a stub | `training/evaluation.py:206-221` |

---

## Security Checklist

- [x] No hardcoded secrets in source code
- [x] API keys read from environment variables only
- [x] No `shell=True` subprocess calls
- [x] No `eval()`/`exec()` on user input
- [x] Transaction-based rollback with file locking
- [x] Pydantic validation on all LLM outputs
- [x] Rate limiting on external APIs
- [x] Input validation on MCP tool parameters
- [ ] **Path confinement check missing in executor** (C-1)
- [ ] **Exception messages leak to MCP clients** (H-3)
- [ ] **No sanitization on LLM user input** (H-4)
- [ ] **Unvalidated strings in S-expression output** (H-5)
- [ ] **Dependencies not pinned** (L-3)

---

## SLC Verdict

**3 operations are SLC violations:**
1. `add_bus` / `remove_bus` -- stubs that crash at runtime
2. `validate_footprint` -- always returns True, never validates
3. `place_no_connects_from_erc` -- phantom, exists in docs only

**Recommendation:** Fix C-1 through C-5 before any external-facing release. The prompt-to-schema mismatches (H-6) are high-priority because they directly break LLM agent workflows.

---

## Reviewers

| Specialist | Area | Findings |
|-----------|------|----------|
| Architecture Rick | Module structure, operation completeness, data flow | 20 findings |
| Code Quality Rick | Dead code, duplication, type safety, naming | 15 findings |
| Security Rick | Path traversal, injection, secrets, MCP | 13 findings |
| Testing Rick | Coverage gaps, integration, edge cases | 17 findings |
| Documentation/SLC Rick | Prompt-schema mismatches, stubs, doc gaps | 15 findings |
| Training Pipeline Rick | GRPO math, reward model, data integrity | 11 findings |

*Total: 56 unique findings (deduplicated across specialists)*
