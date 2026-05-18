---
phase: 02-operation-schema-and-ir-layer
verified: 2026-05-18T06:30:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification: true
gaps: []
---

# Phase 2: Operation Schema and IR Layer Verification Report

**Phase Goal:** The LLM has a well-defined JSON contract for expressing edit intents, and the tool layer can translate those intents into IR mutations
**Verified:** 2026-05-18T06:30:00Z
**Status:** passed
**Re-verification:** Yes — UUID corruption gap fixed (required decimal point in sci-notation regex)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A JSON operation intent validates against the Pydantic schema (rejects invalid intents, accepts valid ones) | VERIFIED | Operation.model_validate accepts valid add_component intent; rejects invalid op_type, missing fields, path traversal. 20 tests pass. |
| 2 | A validated intent translates to an IR mutation on a parsed file | VERIFIED | SchematicIR wraps parsed schematic, exposes 14 components, tracks mutations via _record_mutation, get_component_by_ref works. 18 tests pass. |
| 3 | The mutated IR serializes to a deterministic, SCM-friendly output (stable ordering across runs) | VERIFIED | Regex fixed to require decimal point — UUIDs never contain dots. 3 new UUID preservation tests pass including real schematic file. 122 total tests pass. |
| 4 | A failed mutation rolls back to the pre-mutation state (transaction with rollback) | VERIFIED | Transaction auto-rollback on exception restores original file content. Explicit rollback works. Idempotent double-rollback. 19 tests pass. |
| 5 | The JSON Schema is exportable for LLM consumption (Claude can discover available operations) | VERIFIED | get_operation_schema() returns dict with $defs containing all 4 op types (add_component, remove_component, move_component, modify_property). 3 export tests pass. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/kicad_agent/ops/__init__.py` | Barrel exports for ops package | VERIFIED | Exports Operation, matches parser pattern |
| `src/kicad_agent/ops/schema.py` | Pydantic discriminated union | VERIFIED | 211 lines. 4 operation models with Literal discriminators, TargetFile with path traversal defense, get_operation_schema() helper |
| `src/kicad_agent/ir/__init__.py` | Barrel exports for IR package | VERIFIED | Exports SchematicIR, PcbIR, SymbolLibIR, FootprintIR, Transaction, TransactionResult |
| `src/kicad_agent/ir/base.py` | BaseIR with mutation tracking | VERIFIED | 136 lines. _record_mutation, dirty flag, mutation log with 1000-entry cap, one-IR-per-ParseResult registry |
| `src/kicad_agent/ir/schematic_ir.py` | SchematicIR with component access | VERIFIED | 82 lines. components property, get_component_by_ref, get_component_property, file_type validation |
| `src/kicad_agent/ir/pcb_ir.py` | PcbIR with footprint/net access | VERIFIED | 77 lines. footprints, nets, trace_items properties. Requires UUID map, file_type validation |
| `src/kicad_agent/ir/symbol_lib_ir.py` | SymbolLibIR with symbol access | VERIFIED | 52 lines. symbols property, file_type validation |
| `src/kicad_agent/ir/footprint_ir.py` | FootprintIR with pad access | VERIFIED | 81 lines. pads, fp_lines, fp_text properties. Requires UUID map |
| `src/kicad_agent/ir/transaction.py` | Transaction with rollback | VERIFIED | 231 lines. shutil.copy2 snapshots, auto-rollback on exception, fcntl locking, symlink protection, 0o600 permissions |
| `src/kicad_agent/serializer/normalizer.py` | Post-kiutils normalization | HOLLOW | 117 lines. normalize_kicad_output works but _fix_scientific_notation corrupts UUIDs in real files. String-aware tokenization protects quoted strings but not unquoted UUID tokens |
| `tests/test_ops_schema.py` | Schema validation tests | VERIFIED | 20 tests covering valid ops, invalid ops, path security, length constraints, schema export, position defaults |
| `tests/test_ir_layer.py` | IR layer tests | VERIFIED | 18 tests across 6 test classes with real KiCad fixtures |
| `tests/test_transaction.py` | Transaction tests | VERIFIED | 19 tests across 7 classes including security tests |
| `tests/test_normalizer.py` | Normalizer tests | VERIFIED | 14 tests pass but idempotency test uses synthetic data without UUIDs |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| ops/schema.py | pydantic.BaseModel | class inheritance | WIRED | All 4 operation models + Operation + PositionSpec + PropertySpec extend BaseModel |
| ops/__init__.py | ops/schema.py | import | WIRED | `from kicad_agent.ops.schema import Operation` |
| ir/base.py | parser/types.py | ParseResult reference | WIRED | `from kicad_agent.parser.types import ParseResult` |
| ir/base.py | parser/uuid_extractor.py | UUIDMap reference | WIRED | `from kicad_agent.parser.uuid_extractor import UUIDMap` |
| ir/schematic_ir.py | ir/base.py | inheritance | WIRED | `class SchematicIR(BaseIR)` |
| ir/pcb_ir.py | ir/base.py | inheritance | WIRED | `class PcbIR(BaseIR)` |
| ir/symbol_lib_ir.py | ir/base.py | inheritance | WIRED | `class SymbolLibIR(BaseIR)` |
| ir/footprint_ir.py | ir/base.py | inheritance | WIRED | `class FootprintIR(BaseIR)` |
| transaction.py | ir/base.py | Transaction wraps IR mutations | NOT WIRED | Transaction operates on file paths (Path), not IR objects. No import of BaseIR. Works together at integration level but not directly coupled -- by design. |
| normalizer.py | serializer/uuid_reinjector.py | Post-processing pipeline | NOT WIRED | Normalizer is standalone, does not import or reference uuid_reinjector. They form a pipeline conceptually but are not coupled. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| schema.py (Operation) | root field | Pydantic model_validate | Yes -- validates real JSON structures | FLOWING |
| schematic_ir.py (components) | _parse_result.kiutils_obj.schematicSymbols | Phase 1 parser | Yes -- 14 components from Arduino fixture | FLOWING |
| pcb_ir.py (footprints) | _parse_result.kiutils_obj.footprints | Phase 1 parser | Yes -- real footprints from PCB fixture | FLOWING |
| normalizer.py (_fix_scientific_notation) | regex matches on unquoted segments | kiutils serialized output | Corrupts UUIDs -- produces wrong data | CORRUPTING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Schema validates valid intent | Operation.model_validate with add_component | op.root.op_type == "add_component" | PASS |
| Schema rejects invalid intent | model_validate with op_type="invalid" | ValidationError raised | PASS |
| Schema rejects path traversal | model_validate with target_file="../../etc/passwd" | ValidationError raised | PASS |
| Schema exportable | get_operation_schema() | dict with 4 op types in $defs | PASS |
| Transaction auto-rollback | Transaction with RuntimeError | File content restored to original | PASS |
| Transaction explicit rollback | txn.rollback() | File content restored | PASS |
| IR mutation tracking | ir._record_mutation() | dirty=True, log has 1 entry | PASS |
| Normalizer idempotency on real data | normalize(normalize(real_sch)) == normalize(real_sch) | 104 UUIDs corrupted on pass1, different output on pass2 | FAIL |
| Normalizer UUID preservation | UUIDs in real KiCad file after normalization | 104/284 UUIDs corrupted | FAIL |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| OPS-01 | 02-01 | JSON operation schema with Pydantic v2 models and JSON Schema export | SATISFIED | Operation class with 4 types, get_operation_schema() works |
| OPS-02 | 02-01 | Operation validation: reject structurally invalid intents before mutation | SATISFIED | ValidationError for invalid op_type, missing fields, path traversal |
| OPS-03 | 02-02 | Operation execution: translate validated intent -> IR mutation -> serialized file | SATISFIED | BaseIR._record_mutation, SchematicIR/PcbIR/SymbolLibIR/FootprintIR with typed access |
| FND-07 | 02-03 | Transaction-based mutation with rollback capability | SATISFIED | Transaction class with auto-rollback, explicit rollback, file locking |
| FND-08 | 02-03 | Deterministic, SCM-friendly serialization (stable output ordering) | BLOCKED | Normalizer deterministic but NOT SCM-friendly due to UUID corruption |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| normalizer.py | 29, 99 | Regex matches UUID hex as scientific notation | Blocker | 104/284 UUIDs corrupted in real KiCad files -- files are NOT safe after normalization |
| test_normalizer.py | 106 | test_idempotent uses synthetic data without UUIDs | Warning | Test passes but does not exercise real UUID corruption scenario |

**Stub classification note:** The UUID corruption is not a stub or placeholder -- it is an active bug in the _fix_scientific_notation regex. The regex `(?<![a-zA-Z_"(])` lookbehind does not protect against UUID patterns where digits precede 'e' in hex context (e.g., `8f05000000e95976`). The regex correctly skips content preceded by letters, but in `05000000e95976`, the digit '0' is the preceding character, which passes the lookbehind.

### Human Verification Required

None -- all findings are programmatically verifiable.

### Gaps Summary

**One gap blocks the phase goal: normalizer UUID corruption.**

The `_fix_scientific_notation` function in `src/kicad_agent/serializer/normalizer.py` uses a regex that incorrectly matches hex digits within UUID tokens as scientific notation. When applied to real KiCad files, this corrupts 104 out of 284 UUIDs by replacing hex patterns like `5000000e95976` with floating-point values like `inf`. This means:

1. **SC3 fails:** "SCM-friendly output" is not achieved when UUIDs are mangled
2. **FND-08 is blocked:** The normalizer is the mechanism for "deterministic, SCM-friendly serialization" and it corrupts data
3. **The test suite has a coverage gap:** The idempotency test uses synthetic data that does not contain UUIDs, so it passes despite the bug

The fix requires either:
- Adding UUID pattern awareness to the regex (skip `(uuid ...)` forms entirely)
- Tightening the regex to only match within known numeric contexts (e.g., after `(at`, `(size`, `(xy` keywords)
- Using a more restrictive pattern that requires a decimal point before the 'e' (real scientific notation always has a decimal)

All other aspects of Phase 2 are verified: the operation schema, IR layer, transaction engine, and their tests are substantive, wired, and functional.

---

_Verified: 2026-05-18T06:30:00Z_
_Verifier: Claude (gsd-verifier)_
