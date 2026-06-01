# The Council of Ricks Plan Review Report

## Stack Assessment

**Detected Project Stack:**
- **Project Type**: Python (kicad-agent) + TypeScript (VS Code extension)
- **Domain**: EDA / KiCad automation / multi-format conversion / AI training
- **Build System**: pip install -e . (Python), npm/vitest (TypeScript)
- **Testing**: pytest (Python), vitest (TypeScript)
- **Key Dependencies**: Pydantic v2, kiutils, networkx, olefile (Altium), xml.etree (Eagle)
- **New Packages Required**: olefile (Altium OLE), vsce (VS Code packaging)

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (EDA specialist), Component Rick (dataset/BOM quality), Embedded Firmware Rick (binary format safety)
- **Wave Delta (Pipeline):** GSD Plan Checker (plan review specialist)
- **Wave Epsilon (Fresh Eyes):** Spectral Rick (frequency domain on circuit generation), Go Bubble Tea Rick (terminal UI patterns for CLI design)
- **Total reviewers this session:** 10/84

---

## Executive Summary
- **Total Issues**: 21
- **Critical (SLC)**: 4
- **High (Architecture/Security)**: 7
- **Medium (Functional)**: 7
- **Low (Style/Completeness)**: 3

---

## Historical Context and Pattern Wisdom (Rickfucius)
**Status**: PATTERNS FOUND

### Relevant Patterns Found

#### Template-Based Generation (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Phase 52's `CircuitTemplate` with parameterized generation mirrors the existing `generator.py` pattern: `_generate_chunk()` in ProcessPoolExecutor, dict serialization for pickling avoidance, SHA256 dedup. This is a proven pattern in this codebase with `MazeDataset` and `RealBoardDataset`.
- **Recommendation**: Follow pattern -- reuse the chunk/worker/dedup architecture.

#### Pydantic Model with Validation (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Phase 55's `AbstractCircuit` uses Pydantic BaseModel with field validators, matching the established `Operation` schema pattern in `ops/schema.py`. The `BaseIR` pattern from `ir/base.py` validates file types at construction time -- Phase 55's `CircuitValidator` extends this pattern to cross-model invariants.
- **Recommendation**: Follow pattern -- Pydantic v2 is the right choice here.

#### Format Adapter Pattern (follows LTSpice precedent)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: The `asc_parser.py` + `symbol_mapper.py` pair in `ltspice/` proved cross-format viability. Phases 56-58 formalize this into a general `FormatAdapter` pattern. The architecture is sound: parse -> AbstractCircuit -> write.
- **Recommendation**: Follow pattern -- the LTSpice integration validated this approach.

### Anti-Patterns Detected

#### NotImplementedError Stubs (re-introduction of previously banned pattern)
- **Category**: code
- **Problem**: Phase 24 Council audit explicitly removed `NotImplementedError` stubs as SLC violations. The previous Council review (Phase 41) flagged this exact pattern. Now Phase 55-02 re-introduces `NotImplementedError` in `abstract_to_schematic_ir()`, and multiple format parsers use `return []` stubs for `_derive_nets()` and `_extract_pins()`.
- **Historical Evidence**: Phase 41 Council review said: "NotImplementedError pattern must be resolved before execution. Historical precedent from Phase 24 is clear." Phase 55-02 line 305: `raise NotImplementedError("abstract_to_schematic_ir: Phase 2 implementation")`. Phase 55-02 lines 357, 363, 378: `return []  # Stub -- full implementation follows TDD`.
- **Recommendation**: This is a CRITICAL SLC violation. Either implement `abstract_to_schematic_ir()` in Phase 55-02 or do not create the method until it can be fully implemented. Empty `return []` stubs in production code violate the project's own hard-won standards.

#### Circular Dependency Chain Through Abstract AST
- **Category**: architecture
- **Problem**: Phase 55-02's `abstract_to_schematic_ir()` is not implemented, but Phases 57-02 and 58-02 depend on it for migration tools. The `AltiumMigration.migrate()` method has a TODO comment acknowledging this gap (57-02 line 227): `# TODO: Use KiCadAdapter.abstract_to_schematic_ir() when implemented`. This creates a dependency chain where 57-02 and 58-02 cannot deliver their core value without 55-02 being complete.
- **Recommendation**: Phase 55-02 MUST implement `abstract_to_schematic_ir()` before any format migration tools (57-02, 58-02) can execute. If the KiCad write-back is too complex for 55-02, then the migration tools should be deferred to a later phase, not shipped half-functional.

**Rickfucius Decision**: FIX VIOLATION -- NotImplementedError and stub methods must be resolved. Historical precedent from Phase 24 and Phase 41 is clear. The abstract AST is the keystone -- if it ships incomplete, everything built on it (phases 56-58) inherits the incompleteness.

---

## SLC Validation (Slick Rick)
**Status**: FAIL

### SLC Anti-Patterns Detected
- **Workarounds**: 0 found
- **Stub Methods**: 8 found (NotImplementedError + return [] stubs)
- **TODO/FIXME without tickets**: 2 found
- **Incomplete Implementations**: 4 found (see below)

### SLC Criteria Assessment

- [x] **Simple**: Obvious purpose, minimal learning
  - [Intuitive interface? yes] Format adapters follow a clean parse/write pattern. CLI is standard argparse.
  - [Self-explanatory features? yes] Phase names, model names, and method names are all descriptive.
  - [Minimal docs needed? yes] CLI usage documented inline, architecture diagrams in overview plans.

- [ ] **Lovable**: Delightful to use, builds trust
  - [Polished design? partial] The Format Registry (58-02) provides a unified CLI, but the Altium migration tool (57-02) writes JSON instead of .kicad_sch when the reverse adapter is unavailable.
  - [Graceful errors? partial] Error handling is mentioned but not consistently tested across all format parsers.
  - [Celebrated successes? no] No summary statistics or visualization of conversion results.

- [ ] **Complete**: Full user journey, no gaps
  - [All APIs implemented? no] `KiCadAdapter.abstract_to_schematic_ir()` raises NotImplementedError. Multiple `_derive_nets()` methods return empty lists.
  - [Edge cases handled? no] Missing: empty circuit handling in EasyEdaParser, corrupt OLE files in AltiumParser, XML bomb protection in EagleParser.
  - [No broken flows? no] Altium migration tool (57-02) cannot produce .kicad_sch output -- it writes .abstract.json instead.

### Critical SLC Violations

#### SLC-1: NotImplementedError in KiCadAdapter.abstract_to_schematic_ir() (55-02-PLAN.md:305)
- **Severity**: CRITICAL
- **Description**: The reverse conversion (Abstract AST -> KiCad) is the entire point of Phase 55-02. Without it, the round-trip cannot be proven, and all downstream migration tools (57-02, 58-02) are broken. The plan says tests for it "may remain NotImplementedError initially, with tests for it marked xfail or skipped."
- **Fix**: Implement `abstract_to_schematic_ir()` fully in Phase 55-02. This is the core deliverable of that plan -- it cannot be a stub. The LOSS_ACCOUNTING already documents what is preserved and what is lost, so the implementation scope is well-defined.

#### SLC-2: Empty return [] stubs in KiCadAdapter (55-02-PLAN.md:357,363,378)
- **Severity**: CRITICAL
- **Description**: `_extract_nets()` returns `[]  # Stub -- full implementation follows TDD`. `_extract_sheets()` returns `[]`. `_extract_pins()` returns `[]`. These produce an AbstractCircuit with zero nets, zero sheets, and zero pins. Every downstream consumer gets garbage data.
- **Fix**: All three methods must be fully implemented in Phase 55-02. The net extraction (wire connectivity graph + labels) is the most complex part -- this is exactly why the phase exists.

#### SLC-3: Altium migration tool writes JSON instead of .kicad_sch (57-02-PLAN.md:227-241)
- **Severity**: CRITICAL
- **Description**: `AltiumMigration.migrate()` has a TODO comment: `# TODO: Use KiCadAdapter.abstract_to_schematic_ir() when implemented`. Instead, it writes `circuit.model_dump_json()` to a `.abstract.json` file. The user asked for `.kicad_sch` output but gets an intermediate JSON file. This is not a migration tool -- it is a parser with a misleading name.
- **Fix**: Either (a) implement `abstract_to_schematic_ir()` in Phase 55-02 so the migration tool works, or (b) rename this to `AltiumParser` and document that KiCad output requires Phase 55-02 to be complete. Do not ship a "migration tool" that does not migrate.

#### SLC-4: TODO without ticket in Altium net derivation (57-01-PLAN.md:712)
- **Severity**: HIGH
- **Description**: `# 5. TODO: Match component pins to wire endpoints for pin_refs` -- This is the core net derivation logic. Without it, AltiumParser produces circuits with zero nets, making it useless for migration.
- **Fix**: Implement pin-to-wire matching in Phase 57-01 or document this as a known limitation with a tracked issue.

**SLC Decision**: REJECT -- NotImplementedError and empty return stubs in Phase 55-02 (the keystone) break all downstream phases.

---

## Security Review (Rick C-137)
**Status**: PASS (with recommendations)

### Vulnerabilities Found

#### Altium Binary Parsing: Missing File Size Limit (57-01-PLAN.md:589-620)
- **Severity**: HIGH
- **Category**: denial_of_service
- **Description**: The `_read_records()` method reads the entire FileHeader stream into memory (`data = stream.read()`) then iterates through binary records. While the threat model mentions "max file size limit", no actual limit is enforced in the implementation code. A malicious .SchDoc with a multi-gigabyte FileHeader stream would consume all available memory.
- **Location**: `altium_parser.py:_read_records()`
- **Exploit Scenario**: Crafted .SchDoc with FileHeader stream > 2GB. The `stream.read()` call loads all of it into RAM.
- **Fix Recommendation**: Add `MAX_SCHDOC_SIZE = 100 * 1024 * 1024  # 100MB` constant. Check stream size before reading. Also add a `MAX_RECORDS = 100000` counter in the parsing loop.
- **Confidence**: 0.95

#### Altium Record Type Confusion: RECORD_WIRE and RECORD_NETLABEL Share Code 34 (57-01-PLAN.md:499-506)
- **Severity**: HIGH
- **Category**: tampering
- **Description**: `RECORD_WIRE = 34` and `RECORD_NETLABEL = 34` are the same value. The plan attempts to handle this with `_NETLABEL_ALT = 35` and `_WIRE_ALT = 35`, but the `_classify_record()` method will classify ALL type-34 records as one type due to the if/elif chain. Record type collision means either wires or net labels will be silently dropped.
- **Location**: `altium_parser.py:_classify_record()`
- **Exploit Scenario**: Legitimate .SchDoc files lose net label information because type-34 is claimed by the wrong handler.
- **Fix Recommendation**: Research the actual Altium record type codes from community documentation (e.g., KiCad's own Altium importer). Use the RECORD parameter inside the parsed data to disambiguate, not just the binary header type code.
- **Confidence**: 0.9

#### EasyEDA JSON: Missing Shape Array Size Limit (56-01-PLAN.md:623)
- **Severity**: MEDIUM
- **Category**: denial_of_service
- **Description**: The threat model correctly identifies "Huge shape array" as T-56-01-02 and says "Add max_shapes limit (10000)". However, the implementation code does not enforce this limit.
- **Location**: `easyeda_types.py:EasyEdaSchematic.from_json()`
- **Fix Recommendation**: Add `MAX_SHAPES = 10000` constant and enforce it after parsing.
- **Confidence**: 0.9

#### Eagle XML: No XML Bomb Protection (58-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: denial_of_service
- **Description**: Eagle XML is parsed with `xml.etree.ElementTree.parse()`. Python's `xml.etree.ElementTree` does not protect against entity expansion attacks by default.
- **Location**: `eagle_parser.py`
- **Fix Recommendation**: Use `defusedxml.ElementTree` or manually disable entity expansion.
- **Confidence**: 0.85

**Security Summary**:
- High Severity: 2 (file size limit, record type collision)
- Medium Severity: 2 (JSON shape limit, XML bomb)
- Low Severity: 0

**Security Decision**: PASS with conditions -- file size limits and record type disambiguation must be addressed in implementation.

---

## Code Quality Review (Rick Sanchez)
**Status**: FAIL

### Issues Found

#### CQ-1: Reverse LCSC Mapping Creates One-to-Many Ambiguity (56-02-PLAN.md:217-219)
- **Severity**: HIGH
- **Category**: bug
- **Description**: `_KICAD_TO_LCSC = {v: k for k, v in _LCSC_TO_KICAD.items()}` creates a reverse mapping. But multiple LCSC parts map to the same `(symbol, footprint)` pair -- 10 different resistors all map to `("Device:R", "Resistor_SMD:R_0805_2012Metric")`. The dict comprehension silently drops all but the last entry. The reverse mapping is fundamentally broken for same-package components with different values.
- **Location**: `lcsc_mapper.py:_KICAD_TO_LCSC`
- **Fix**: The reverse mapping must be `(symbol, footprint, value) -> lcsc_part` to be unambiguous, or return a `list[str]` of matching parts.

#### CQ-2: AbstractNet.pin_refs Type Annotation Mismatch with Pydantic (55-01-PLAN.md:317)
- **Severity**: HIGH
- **Category**: bug
- **Description**: `pin_refs: list[tuple[str, str]]` declared in the model, but Pydantic v2 serializes tuples as JSON arrays, and on re-deserialization they come back as `list[str]`. The JSON round-trip test will fail for any circuit with nets because `pin_refs` will deserialize as `list[list[str]]` instead of `list[tuple[str, str]]`.
- **Location**: `models.py:AbstractNet.pin_refs`
- **Fix**: Either (a) use a custom Pydantic validator for tuple deserialization, (b) model pin_refs as `list[PinRef]` where `PinRef` is a BaseModel with `ref` and `pin_number` fields, or (c) add a `model_validator` that converts lists back to tuples.

#### CQ-3: VS Code Extension File Watcher May Trigger Infinite ERC Loop (54-01-PLAN.md)
- **Severity**: HIGH
- **Category**: bug
- **Description**: The file watcher auto-runs ERC on `.kicad_sch` save. But the ERC result display may trigger file modifications (e.g., updating ERC exclusion markers), causing another save event and another ERC run.
- **Location**: `fileWatcher.ts`
- **Fix**: Add debounce (minimum 2 seconds) and a `isRunning` flag that prevents re-entrant ERC execution.

#### CQ-4: QualityMetrics.parameter_coverage hardcoded to 0.0 (52-02-PLAN.md:545)
- **Severity**: MEDIUM
- **Category**: stub
- **Description**: `parameter_coverage=0.0,  # Computed via parameter analysis (expensive)`. Listed as a success criterion but hardcoded to zero.
- **Fix**: Implement it or remove it from the metric and success criteria.

#### CQ-5: MassGenerationResult.total_failed Double-Counts Duplicates (52-02-PLAN.md:413)
- **Severity**: MEDIUM
- **Category**: bug
- **Description**: `total_failed=len(all_dicts) - n_total` counts both duplicates AND generation failures. But duplicates are already tracked as `total_duplicates`.
- **Fix**: `total_failed` should count only circuits that failed generation, not duplicates.

#### CQ-6: Altium _parse_params Swallows All Exceptions (57-01-PLAN.md:631)
- **Severity**: MEDIUM
- **Category**: anti-pattern
- **Description**: `except Exception: pass` silently swallows ALL errors, making debugging parsing failures impossible.
- **Fix**: Catch only expected exceptions: `except (UnicodeDecodeError, ValueError): pass`. Log at debug level.

#### CQ-7: EasyEdaWriter Truncates Coordinates to Integers (56-01-PLAN.md:541-542)
- **Severity**: LOW
- **Category**: data_loss
- **Description**: `str(int(x))` truncates component positions to integer coordinates, causing silent data loss in round-trip.
- **Fix**: Use `str(round(x, 2))` or match EasyEDA's native precision.

**Code Summary**:
- High: 3 (reverse mapping bug, Pydantic tuple, file watcher loop)
- Medium: 3 (parameter stub, failed count, bare except)
- Low: 1 (coordinate truncation)

**Code Decision**: REJECT -- reverse mapping bug, Pydantic tuple issue, and file watcher loop must be fixed in plans.

---

## Design Review (Rick Prime)
**Status**: PASS (with recommendations)
**Review Mode**: Systematic (80%) / Avant-Garde (20%)

### Issues Found

#### D-1: Format Registry Uses String Format Names Instead of Enum (58-02-PLAN.md)
- **Severity**: HIGH
- **Category**: consistency
- **Description**: `detect_format()` returns strings. `FormatRegistry` uses `str` keys. The overview plan specifies `FormatType` as an enum but the implementation uses strings. Typos like "eagel" would silently fail.
- **Fix**: Use `FormatType(str, Enum)` consistently across all format code.

#### D-2: Abstract AST PinType Missing Common Types for Non-KiCad Formats (55-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: completeness
- **Description**: PinType has 8 values, but Altium has 11 electrical types. The KiCad adapter already maps some approximately (`open_collector -> OUTPUT`). The information loss should be documented.
- **Fix**: Either add `OPEN_COLLECTOR`, `OPEN_EMITTER`, `HIZ` to PinType, or document the mapping as lossy in LOSS_ACCOUNTING.

#### D-3: VS Code Extension Missing Language Contribution (54-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: platform_convention
- **Description**: The plan uses `activationEvents: ["onLanguage:kicad"]` but does not define a `contributes.languages` section mapping `.kicad_sch` and `.kicad_pcb` to the `kicad` language ID.
- **Fix**: Add language contribution to `package.json`.

**Design Summary**:
- High: 1 (string vs enum)
- Medium: 2 (pin type coverage, language activation)
- Low: 0

**Design Decision**: PASS with conditions -- FormatType must be an enum, not a string.

---

## Format-Specific Domain Reviews (KiCad Rick)

### Phase 55: Abstract AST (Keystone Assessment)

**Criticality**: This is the FOUNDATION for phases 56-58. If Phase 55 ships incomplete, everything built on it inherits the incompleteness.

**Architecture Assessment**: SOUND. The `AbstractCircuit` model with `components`, `nets`, `sheets`, and `metadata` captures essential circuit semantics. The adapter pattern avoids N-squared format conversion.

**Key Concern**: The `abstract_to_schematic_ir()` method is listed as Phase 55-02's deliverable but implemented as `raise NotImplementedError`. This means:
- Phase 55-02 cannot prove round-trip
- Phase 57-02 (Altium migration) cannot produce .kicad_sch output
- Phase 58-02 (format registry convert) cannot convert to KiCad

**Verdict**: Phase 55-02 MUST implement `abstract_to_schematic_ir()`. Without it, the entire multi-format expansion is read-only with no path to KiCad output.

### Phase 56: EasyEDA

**Format Understanding**: GOOD. The tilde-delimited shape array is correctly documented. LCSC part number preservation through `component.properties["lcsc_part"]` is the right approach.

**Concern**: The `_derive_nets()` method returns `[]`. Net derivation from wire connectivity + labels is the hardest part of any schematic parser.

### Phase 57: Altium

**Format Understanding**: PARTIAL. The binary record structure is documented but record type codes have a collision (type 34 for both wires and net labels). This needs community-source verification.

**Safety Concern**: Binary parsing without a file size limit is a DoS vector.

### Phase 58: Eagle + Format Registry

**Format Understanding**: GOOD. Eagle XML is well-documented by Autodesk. Gate-based symbol model correctly identified as needing special handling.

**Registry Design**: GOOD. Lazy imports, capability matrix, auto-detection.

---

## All Issues (Prioritized)

| # | Phase | Severity | ID | Description | Location |
|---|-------|----------|----|-------------|----------|
| 1 | 55 | CRITICAL | SLC-1 | NotImplementedError in abstract_to_schematic_ir() | 55-02-PLAN.md:305 |
| 2 | 55 | CRITICAL | SLC-2 | Empty return [] stubs in extraction methods | 55-02-PLAN.md:357,363,378 |
| 3 | 57 | CRITICAL | SLC-3 | Altium migration writes JSON not .kicad_sch | 57-02-PLAN.md:227-241 |
| 4 | 57 | HIGH | SLC-4 | TODO in Altium net derivation | 57-01-PLAN.md:712 |
| 5 | 57 | HIGH | SEC-1 | Altium binary: missing file size limit | 57-01-PLAN.md:589 |
| 6 | 57 | HIGH | SEC-2 | Altium record type collision (type 34) | 57-01-PLAN.md:499 |
| 7 | 56 | MEDIUM | SEC-3 | EasyEDA JSON: missing shape array limit | 56-01-PLAN.md:623 |
| 8 | 58 | MEDIUM | SEC-4 | Eagle XML: no XML bomb protection | 58-01-PLAN.md |
| 9 | 56 | HIGH | CQ-1 | Reverse LCSC mapping drops entries | 56-02-PLAN.md:217 |
| 10 | 55 | HIGH | CQ-2 | AbstractNet.pin_refs tuple breaks JSON round-trip | 55-01-PLAN.md:317 |
| 11 | 54 | HIGH | CQ-3 | File watcher infinite ERC loop | 54-01-PLAN.md |
| 12 | 52 | MEDIUM | CQ-4 | parameter_coverage hardcoded 0.0 | 52-02-PLAN.md:545 |
| 13 | 52 | MEDIUM | CQ-5 | total_failed double-counts duplicates | 52-02-PLAN.md:413 |
| 14 | 57 | MEDIUM | CQ-6 | _parse_params swallows all exceptions | 57-01-PLAN.md:631 |
| 15 | 56 | LOW | CQ-7 | EasyEdaWriter truncates coordinates | 56-01-PLAN.md:541 |
| 16 | 58 | HIGH | D-1 | Format Registry uses strings not enum | 58-02-PLAN.md |
| 17 | 55 | MEDIUM | D-2 | PinType missing common Altium/Eagle types | 55-01-PLAN.md |
| 18 | 54 | MEDIUM | D-3 | VS Code missing language contribution | 54-01-PLAN.md |
| 19 | 53 | MEDIUM | CQ-8 | No SPDX license validation | 53-01-PLAN.md |
| 20 | 58 | MEDIUM | SLC-5 | OpenWaterParser returns empty stub | 58-02-PLAN.md:791 |
| 21 | 54 | MEDIUM | SEC-5 | VS Code MCP: missing input validation | 54-01-PLAN.md |

---

## Final Council Decision

**Evil Morty's Ruling**: **REJECT**

### Decision Summary
- **SLC Validation**: FAIL (4 violations, 3 CRITICAL)
- **Security Review**: PASS with conditions
- **Code Quality**: FAIL (3 HIGH bugs)
- **Design Review**: PASS with conditions
- **KiCad Rick (Domain)**: FAIL (keystone phase incomplete)
- **Historical Context**: FAIL (re-introduction of banned NotImplementedError pattern)

### Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): REJECT (reverse mapping bug, Pydantic tuple, file watcher loop)
- Rick C-137 (Security): PASS with conditions (file size limits must be enforced)
- Slick Rick (SLC): REJECT (NotImplementedError in keystone phase, stub methods)

**Wave Beta (Wisdom):**
- Rick Prime (Design): PASS with conditions (enum vs string, pin types)
- Rickfucius (Historian): REJECT (re-introduction of banned NotImplementedError pattern)

**Wave Gamma (Domain):**
- KiCad Rick (EDA): REJECT (Phase 55-02 cannot prove round-trip, all downstream broken)
- Component Rick (BOM): REJECT (reverse LCSC mapping is broken)

**Wave Delta (Pipeline):**
- GSD Plan Checker: REJECT (dependency chain broken: 57-02 depends on unimplemented 55-02 method)

**Wave Epsilon (Fresh Eyes):**
- Spectral Rick: NOTE (training pipeline integration solid for Phase 52)
- Go Bubble Tea Rick: NOTE (CLI design in 58-02 is clean)

**Final:**
- **Evil Morty**: REJECT

---

## Required Fixes Before Re-Planning

### Must Fix (blocks all execution)

1. **Phase 55-02: Implement `abstract_to_schematic_ir()` fully.** This is the keystone. Without it, phases 56-58 cannot deliver migration or cross-format conversion. Remove the `NotImplementedError` and implement the reverse conversion using kiutils constructors.

2. **Phase 55-02: Implement `_extract_nets()`, `_extract_sheets()`, `_extract_pins()`.** Remove all `return []` stubs. If these are too complex for one phase, split Phase 55-02 into two plans: (a) extraction, (b) reverse conversion.

3. **Phase 57-02: Fix Altium migration tool.** It must produce `.kicad_sch` output (requires Phase 55-02 fix #1) or be renamed as a parser-only tool.

4. **Phase 56-02: Fix reverse LCSC mapping.** Use `(symbol, footprint, value)` as the key, or return a list of matches.

5. **Phase 55-01: Fix AbstractNet.pin_refs JSON round-trip.** Use a `PinRef` BaseModel or add a custom validator for tuple deserialization.

### Should Fix (improves quality)

6. **Phase 57-01: Add MAX_SCHDOC_SIZE and MAX_RECORDS constants** to Altium binary parser.
7. **Phase 57-01: Research and fix Altium record type codes.** Type 34 collision is a correctness issue.
8. **Phase 54-01: Add debounce and isRunning flag** to file watcher.
9. **Phase 58-02: Use FormatType enum consistently** instead of strings.
10. **Phase 58-01: Use defusedxml** for Eagle XML parsing.
11. **Phase 53-01: Add SPDX license validation** to CuratedProject schema.

### Nice to Fix (polish)

12. **Phase 56-01: Preserve floating-point coordinates** in EasyEdaWriter.
13. **Phase 52-02: Implement parameter_coverage** or remove from metrics.
14. **Phase 58-02: Replace OpenWaterParser stub** with a test-only mock adapter.
15. **Phase 54-01: Add language contribution** to package.json.

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. The Abstract AST is the keystone of multi-format expansion. If the keystone is incomplete, the arch collapses. Implement the reverse adapter. Fill in the stubs. Then we talk."

**Review Completed**: 2026-05-31
**Review Duration**: Full wave review, 7 phases, 19 plans
**Review Scope**: Phases 52 (Synthetic Generation), 53 (Real-World Corpus), 54 (VS Code Extension), 55 (Abstract AST), 56 (EasyEDA Support), 57 (Altium Support), 58 (Eagle + OpenWater)
