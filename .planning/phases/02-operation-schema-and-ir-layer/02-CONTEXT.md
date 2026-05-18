---
phase: 2
title: Operation Schema and IR Layer
created: 2026-05-18
decisions: 14
---

# Phase 2 Context — Operation Schema and IR Layer

Decisions captured via discuss-phase. Downstream agents (researcher, planner, executor) MUST treat these as locked — do not re-ask.

---

## Area 1: Operation Schema Design

### D-01: One Pydantic model per operation type
Each operation is a distinct Pydantic model class (e.g., `AddComponent`, `RemoveNet`, `MoveSymbol`). Not a generic dict with a `type` field.

**Rationale:** Strong typing, auto-validation, JSON Schema export per type. LLM gets precise contracts.

### D-02: Atomic operations
One mutation per operation. No compound operations. If a user wants "move symbol and update net," that's two separate operations applied sequentially.

**Rationale:** Simpler validation, rollback, and error reporting. LLM constructs multi-step plans as operation arrays.

### D-03: Single file per operation
Each operation targets one file via a `target_file` field. Cross-file operations are split into multiple single-file operations.

**Rationale:** Aligns with atomic operations. Simplifies transaction scope and rollback.

### D-04: Export full JSON Schema via Pydantic v2
Use Pydantic v2's `model_json_schema()` to export complete JSON Schema for all operation types. LLM consumes this as a tool contract.

**Rationale:** LLM gets exact field names, types, required/optional, and descriptions. No guesswork.

---

## Area 2: IR Layer Architecture

### D-05: Thin wrapper over kiutils objects
The IR (Intermediate Representation) holds a reference to the kiutils parsed object — not a deep copy. Mutations apply directly to the kiutils object through IR methods.

**Rationale:** Avoids duplication. kiutils objects are the source of truth for structure. IR adds mutation tracking on top.

### D-06: Mutation tracking with rollback data
Each IR instance tracks: which fields were mutated, original values (for rollback), a reference to the UUID map (PCB/footprint), and a `dirty` flag.

**Rationale:** Enables transaction rollback without re-parsing. Original values stored at mutation time.

### D-07: File-type IR classes
Separate IR classes per file type: `SchematicIR`, `PcbIR`, `SymbolLibIR`, `FootprintIR`. Each exposes file-type-specific mutation methods.

**Rationale:** Different file types have different valid mutations. Type safety at the IR level prevents invalid operations.

---

## Area 3: Transaction and Rollback

### D-08: File-level snapshots
Before any mutation, snapshot the entire file content (raw bytes). On rollback, restore from snapshot.

**Rationale:** KiCad files are typically <10MB. Full copy is fast and guarantees correct rollback. No partial state corruption.

### D-09: Auto-rollback on failure
Rollback triggers automatically on: validation failure, unhandled exception, or manual `rollback()` call. No manual cleanup needed.

**Rationale:** Prevents half-mutated files. The transaction is all-or-nothing.

### D-10: Full file copy for snapshots
Use `shutil.copy2` or raw byte copy for snapshots. Not delta-based.

**Rationale:** Simplicity and correctness. KiCad files are small enough that full copy is negligible.

---

## Area 4: Deterministic Serialization

### D-11: KiCad-native property ordering
After kiutils serialization, apply an ordering pass that matches KiCad's canonical property order exactly. Ensures unchanged properties appear in the same position.

**Rationale:** Eliminates ordering-related diff noise. Git shows only real changes.

### D-12: Match KiCad native whitespace
Use KiCad's actual indentation (spaces, 4-char indent). Not tabs, not compact.

**Rationale:** Byte-identical to KiCad output for unchanged content.

### D-13: Post-process normalizer
After kiutils `to_file()`, run a normalizer that fixes: quoting differences, escape sequences, token formatting. All normalized to match KiCad's native output.

**Rationale:** kiutils has known formatting quirks. Post-processing is the simplest path to byte-identical output.

### D-14: Full KiCad-native byte-identical output
The serialization goal is byte-identical output to KiCad's native format for unchanged files. Not just round-trip stable — actually matching KiCad.

**Rationale:** Zero diff noise in git. The ultimate SCM-friendly guarantee. Harder to achieve but the right standard.

---

## Implementation Constraints

- **Python 3.11+** with Pydantic v2
- **kiutils 1.4.8** for parsing (known UUID limitation, handled by uuid_extractor)
- **No additional parser dependencies** — build on Phase 1 foundation
- **Tests must cover**: schema validation, IR mutation tracking, rollback correctness, serialization determinism
- **Round-trip tests from Phase 1 must continue to pass**
