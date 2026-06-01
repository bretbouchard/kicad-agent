# The Council of Ricks Plan Review Report

## Stack Assessment

**Detected Project Stack:**
- **Project Type**: Python (kicad-agent)
- **Domain**: EDA / KiCad automation / AI tooling / multi-format EDA
- **Build System**: pip install -e . (Python), npm/vsce (VS Code extension)
- **Testing**: pytest (135+ test files), vitest (VS Code extension)
- **CI/CD**: GitHub Actions (build.yml, ci.yml, publish.yml)
- **Key Dependencies**: Pydantic v2, kiutils, networkx, olefile (Altium), xml.etree (Eagle)

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (PCB/EDA specialist), Component Rick (supply chain/dataset quality)
- **Wave Delta (Pipeline):** GSD Plan Checker (plan review specialist)
- **Wave Epsilon (Fresh Eyes):** Spectral Rick (frequency domain perspective on circuit analysis), Connector Rick (interfacing between formats)
- **Total reviewers this session:** 10/84

---

## Executive Summary
- **Total Issues**: 27
- **Critical (SLC)**: 4
- **High (Architecture/Security)**: 8
- **Medium (Functional)**: 10
- **Low (Style/Completeness)**: 5

**Recommendation: REJECT -- fix all issues before execution.**

---

## Findings Table

| # | Phase | Severity | Category | Finding |
|---|-------|----------|----------|---------|
| F-01 | 55-02 | CRITICAL | SLC | `abstract_to_schematic_ir()` is `raise NotImplementedError` -- the reverse conversion path is a stub |
| F-02 | 55-02 | CRITICAL | SLC | `_extract_nets()` returns `[]` stub, `_extract_sheets()` returns `[]` stub, `_extract_pins()` returns `[]` stub |
| F-03 | 57-02 | CRITICAL | SLC | `AltiumMigration.migrate()` contains `# TODO: Use KiCadAdapter.abstract_to_schematic_ir() when implemented` -- the entire migration output is a JSON dump, not a .kicad_sch file |
| F-04 | 52-01 | HIGH | Security | `_eval_predicate()` uses `eval()` with restricted builtins -- mitigated but eval is a code smell; a safer lambda/function approach exists |
| F-05 | 53-01 | HIGH | Security | Downloads from GitHub/Hackaday with no URL validation, no content hash verification, no integrity checks |
| F-06 | 57-01 | HIGH | Security | OLE compound document parsing (olefile) is a high-risk binary attack surface -- malformed .SchDoc files could exploit parser |
| F-07 | 54-01 | HIGH | Security | MCP stdio transport -- no authentication, any local process can connect to the edit server |
| F-08 | 55-01 | HIGH | Architecture | `AbstractNet.pin_refs` uses `list[tuple[str, str]]` -- Pydantic cannot serialize `tuple` in JSON round-trip (becomes list) |
| F-09 | 55-01 | MEDIUM | Architecture | `properties: dict[str, str]` on AbstractComponent is KiCad-biased -- EasyEDA uses it for LCSC parts, Altium for LibReference, but no schema for what properties mean |
| F-10 | 55-01 | MEDIUM | Architecture | No `AbstractPort` or `AbstractBus` model -- Eagle uses bus definitions, KiCad uses bus entries, neither is representable |
| F-11 | 55-02 | MEDIUM | Architecture | LOSS_ACCOUNTING is defined but no automated test verifies that the claimed preserved fields actually survive round-trip |
| F-12 | 52-01 | MEDIUM | Schema | `valid_range_predicates` stored as `list[str]` (serialized eval strings) -- cannot be inspected, debugged, or type-checked at development time |
| F-13 | 53-01 | MEDIUM | Schema | `complexity_score` algorithm is not specified -- how is 0.0-10.0 computed from component/net/sheet counts? |
| F-14 | 54-01 | MEDIUM | Functional | No error handling for MCP server not running -- extension should detect and report, not crash |
| F-15 | 56-02 | MEDIUM | Functional | `_KICAD_TO_LCSC` reverse index uses `dict[tuple[str, str], str]` -- but multiple LCSC parts map to same KiCad symbol+footprint (e.g., 10 different resistor values all map to `Device:R` + `R_0805_2012Metric`), so reverse lookup is lossy |
| F-16 | 57-01 | MEDIUM | Functional | No `.SchDoc` fixture file -- plans reference `tests/fixtures/altium/minimal.SchDoc` but generating a valid OLE binary fixture requires tooling not specified |
| F-17 | 58-02 | MEDIUM | Functional | OpenWater format is described as "proof of concept" but OpenWater's actual file format is never specified -- what does OpenWaterParser actually parse? |
| F-18 | 52-02 | LOW | Completeness | `parameter_coverage` in `QualityMetrics` is hardcoded to `0.0` with comment "Computed via parameter analysis (expensive)" -- metric is defined but never computed |
| F-19 | 56-01 | LOW | Completeness | EasyEdaWriter uses `int()` for coordinate conversion -- sub-mm precision is lost (EasyEDA uses 10x-scaled integers internally) |
| F-20 | 53-01 | LOW | Completeness | GPL-2.0 and GPL-3.0 are listed under `_NON_COMMERCIAL_LICENSES` but GPL does permit commercial use (with copyleft obligations) -- license classification is incorrect |
| F-21 | 54-01 | LOW | Completeness | No `package.json` `engines` field specifying minimum VS Code version |
| F-22 | 52-01 | LOW | Style | `CircuitTemplate.valid_range_predicates: list[str]` type annotation says `list[str]` but description says "callable validity checks" -- misleading doc |
| F-23 | 55-01 | LOW | Style | No `__repr__` or `__str__` on AbstractCircuit models for debugging |
| F-24 | 57-02 | CRITICAL | Dependency | Phase 57-02 depends on `abstract_to_schematic_ir()` which is NotImplementedError in 55-02 -- circular dependency chain blocks migration tool |
| F-25 | 56-02 | MEDIUM | Architecture | `LcscComponentMapper` uses a static dict of 50 parts -- real LCSC catalog has 100k+ parts; the static approach does not scale and is not extensible |
| F-26 | 54-01 | HIGH | Security | File watcher auto-runs ERC on save -- if a malicious `.kicad_sch` file is opened, ERC execution happens automatically |
| F-27 | 58-01 | MEDIUM | Functional | Eagle gate-based symbols mapped to AbstractComponent "with all gates merged" -- but AbstractComponent has no gate concept, so gate-to-pin mapping information is lost |

---

## Detailed Findings by Phase

---

### Phase 52: Synthetic Circuit Generation (52-01, 52-02)

**KiCad Rick Assessment**: Template-based generation is sound engineering. The approach mirrors the existing maze generation pattern in `training/dataset.py`. The CircuitTemplate schema is well-structured with ComponentRange validation and net connectivity rules. The 10 template categories (amplifier, filter, buffer, oscillator, etc.) provide reasonable diversity.

#### F-04 (HIGH): eval() in _eval_predicate
- **Location**: `52-01-PLAN.md`, line 283
- **Issue**: `_eval_predicate` uses `eval(predicate_str, {"__builtins__": {}}, params)` for validity predicates. While builtins are restricted, eval is inherently dangerous and a code smell. A safer alternative is to define predicates as lambdas or use a restricted expression evaluator.
- **Mitigation in plan**: The plan acknowledges this in threat model T-52-03 and notes predicates are developer-defined only. Acceptable for now but must be tracked.
- **Recommendation**: Replace eval with a safe expression parser (e.g., `ast.literal_eval` extended with comparison operators, or pre-compiled lambda functions). If eval must stay, add a runtime guard that validates predicate strings against an allowlist of operators (`<`, `>`, `<=`, `>=`, `and`, `or`, `not`, arithmetic).

#### F-12 (MEDIUM): Predicate serialization as strings
- **Location**: `52-01-PLAN.md`, CircuitTemplate schema
- **Issue**: `valid_range_predicates: list[str]` stores predicates as strings. These cannot be type-checked, linted, or debugged in an IDE. A typo in a predicate string fails silently at runtime.
- **Recommendation**: Define predicates as `Callable[[dict[str, float]], bool]` at runtime with a separate serialization layer for JSON storage. The string representation can be derived from the callable via `__name__` or a registry.

#### F-18 (LOW): parameter_coverage hardcoded to 0.0
- **Location**: `52-02-PLAN.md`, QualityMetrics class
- **Issue**: `parameter_coverage: float` is always returned as `0.0` with a comment "Computed via parameter analysis (expensive)". The metric is declared in the schema but never implemented.
- **Recommendation**: Either implement the metric or remove the field and add a TODO with a bead ticket. A stub field that always returns 0.0 is misleading.

---

### Phase 53: Real-World Corpus Expansion (53-01)

**KiCad Rick Assessment**: The CorpusCurator pipeline is well-designed. Quality gates (parse check, min components, identifiable function) are appropriate. SPDX license tracking with commercial-use flags is a responsible approach to data provenance.

#### F-05 (HIGH): No download integrity verification
- **Location**: `53-01-PLAN.md`, CorpusCurator pipeline
- **Issue**: The plan downloads projects from GitHub/Hackaday URLs with no:
  - URL validation (scheme, domain allowlist)
  - Content hash verification (SHA256 of downloaded archive)
  - Size limits (a malicious repo could be arbitrarily large)
  - Symlink/zip-slip protection during extraction
- **Threat model**: T-53-01 through T-53-04 are listed but none address download integrity.
- **Recommendation**: Add to must_haves truths: "Downloaded archives are validated by SHA256 hash against GitHub release checksums" and "Extraction path is bounded to a temp directory with no symlink following". Add a `max_download_size_mb` config (default 100MB).

#### F-13 (MEDIUM): Unspecified complexity_score algorithm
- **Location**: `53-01-PLAN.md`, CuratedProject schema
- **Issue**: `complexity_score: float` is documented as "0.0-10.0 based on component count, sheet count, net count" but the formula is never specified. Two implementations could produce wildly different scores.
- **Recommendation**: Define the formula explicitly, e.g., `min(10.0, log10(component_count) + 0.5 * sheet_count + 0.1 * log10(net_count))`, or reference a documented scoring method.

#### F-20 (LOW): GPL license misclassification
- **Location**: `53-01-PLAN.md`, `_NON_COMMERCIAL_LICENSES`
- **Issue**: GPL-2.0 and GPL-3.0 are listed under `_NON_COMMERCIAL_LICENSES` with the comment "Strong copyleft (commercial use OK but restrictive)". This is self-contradictory. GPL permits commercial use with copyleft obligations. The variable name `_NON_COMMERCIAL_LICENSES` is misleading.
- **Recommendation**: Rename to `_COPLEFT_LICENSES` or `_RESTRICTIVE_LICENSES`. Move GPL licenses to a separate `_COPYLEFT_LICENSES` category. Add a `commercial_use_compatible` field that is `True` for GPL (commercial use is compatible) but also tracks copyleft obligations separately.

---

### Phase 54: VS Code Extension (54-01)

**Component Rick Assessment**: The VS Code extension is a thin TypeScript client reusing the existing MCP edit server. The architecture is sound -- all intelligence stays in the Python MCP server, the extension is just a UI. This is the correct layering.

#### F-07 (HIGH): MCP stdio transport has no authentication
- **Location**: `54-01-PLAN.md`, mcpClient.ts
- **Issue**: The MCP server uses stdio transport, meaning any local process can spawn it. The VS Code extension spawns the MCP server as a child process. There is no authentication between the extension and the server. A malicious local process could also spawn the MCP server and issue arbitrary operations on KiCad files.
- **Mitigation**: This is an inherent limitation of stdio transport. The MCP server only has access to what the spawning process has access to.
- **Recommendation**: Document this in the extension README as a known limitation. Add a config option `kicad-agent.server.allowedCommands` that restricts which MCP operations the extension can invoke. Consider adding a server-side allowlist for commands that modify files (vs. read-only commands like ERC).

#### F-26 (HIGH): Auto-ERC on save executes on untrusted files
- **Location**: `54-01-PLAN.md`, fileWatcher.ts
- **Issue**: The file watcher auto-runs ERC when a `.kicad_sch` file is saved. If a user opens a malicious `.kicad_sch` from an untrusted source, ERC will execute automatically. While kicad-cli ERC is read-only, the MCP server it connects to has write capabilities.
- **Recommendation**: Add a workspace trust check -- auto-ERC only runs in trusted workspaces. VS Code has a built-in workspace trust API (`vscode.workspace.isTrusted`). For untrusted workspaces, require manual command invocation.

#### F-14 (MEDIUM): No MCP server detection
- **Location**: `54-01-PLAN.md`, mcpClient.ts
- **Issue**: If the MCP edit server is not installed or not found on PATH, the extension should gracefully report the error, not crash or silently fail.
- **Recommendation**: Add must_have truth: "Extension checks for MCP server binary on PATH during activation and shows an error notification if not found, with a link to installation instructions."

#### F-21 (LOW): Missing engines field in package.json
- **Location**: `54-01-PLAN.md`, package.json
- **Issue**: No minimum VS Code version specified in the `engines` field. This could lead to incompatibilities.
- **Recommendation**: Add `"engines": { "vscode": "^1.85.0" }` (or whichever version introduced the required APIs).

---

### Phase 55: Abstract AST (55-01, 55-02)

**KiCad Rick Assessment**: The Abstract AST is the keystone of the entire multi-format expansion. The Pydantic model design is clean, validation is thorough, and the architecture diagram correctly shows format adapters as isolated modules. However, the KiCad adapter (55-02) has critical SLC violations that cascade into every dependent phase.

#### F-01 (CRITICAL): abstract_to_schematic_ir() is NotImplementedError
- **Location**: `55-02-PLAN.md`, line 305
- **Code**: `raise NotImplementedError("abstract_to_schematic_ir: Phase 2 implementation")`
- **Impact**: This is the REVERSE conversion path -- AbstractCircuit back to KiCad. Without it:
  - Phase 57-02 (Altium-to-KiCad migration) cannot produce .kicad_sch output
  - Phase 58-02 (Format Registry cross-format conversion) cannot do any-to-KiCad
  - Round-trip testing is impossible
- **Recommendation**: The plan says "may remain NotImplementedError initially" with tests "marked xfail or skipped". This violates SLC. Either implement the full bidirectional adapter in 55-02, or split 55-02 into two plans: 55-02 (read path only) and 55-03 (write path). The write path MUST be complete before 57-02 and 58-02 can execute.

#### F-02 (CRITICAL): Three stub functions returning empty lists
- **Location**: `55-02-PLAN.md`, lines 357, 363, 378
- **Code**:
  - `_extract_nets(sch) -> list[AbstractNet]` returns `[]` with comment "Stub -- full implementation follows TDD"
  - `_extract_sheets(sch) -> list[AbstractSheet]` returns `[]`
  - `_extract_pins(sym, lib_symbols) -> list[AbstractPin]` returns `[]`
- **Impact**: Without pin extraction, components have no pins. Without net extraction, the circuit has no connectivity. Without sheet extraction, hierarchical designs are lost. These are the three most important conversion functions.
- **Recommendation**: Remove all three stubs. Implement via TDD in the plan's own tasks. The plan already specifies TDD tests for these functions (Tests 4, 5, 6, 7 in Task 1) -- the implementation section must not contain stubs.

#### F-08 (HIGH): tuple serialization breaks JSON round-trip
- **Location**: `55-01-PLAN.md`, AbstractNet model
- **Code**: `pin_refs: list[tuple[str, str]] = Field(min_length=1)`
- **Issue**: Python `tuple` serializes to JSON array (which becomes Python `list` on deserialization). A round-trip through `model_dump_json()` then `model_validate_json()` converts `tuple` to `list`. Pydantic v2 handles this transparently for `list[tuple[str, str]]` (it coerces lists of lists back to tuples), but the behavior is fragile and non-obvious.
- **Recommendation**: Either use `list[list[str]]` (simpler, no coercion needed) or add an explicit `@field_serializer` / `@field_validator` pair that documents the round-trip behavior. Test the round-trip explicitly (which the plan does in Test 12, so this is partially covered).

#### F-09 (MEDIUM): properties dict is type-less and format-dependent
- **Location**: `55-01-PLAN.md`, AbstractComponent
- **Code**: `properties: dict[str, str] = Field(default_factory=dict)`
- **Issue**: This is the "escape hatch" where format-specific data gets stuffed. EasyEDA puts `lcsc_part` here, Altium puts `LibReference` here, but there is no schema or contract. Two adapters could use the same key for different meanings.
- **Recommendation**: Define a `FormatMetadata` model with optional typed fields: `lcsc_part: str | None`, `altium_lib_reference: str | None`, `eagle_deviceset: str | None`. Use the `properties` dict only for truly arbitrary data. This prevents key collisions and makes format-specific data discoverable.

#### F-10 (MEDIUM): No bus/port representation
- **Location**: `55-01-PLAN.md`
- **Issue**: Eagle has explicit bus definitions (grouped signals). KiCad has bus entries. Neither is representable in the current Abstract AST. Bus information would be lost in Eagle round-trip.
- **Recommendation**: Add `AbstractBus` model: `name: str, signal_names: list[str], ports: list[str]`. Add `buses: list[AbstractBus] = []` to AbstractSheet. This is optional (adapters that don't support buses can leave it empty) but the schema must exist for lossless Eagle conversion.

#### F-11 (MEDIUM): LOSS_ACCOUNTING not test-verified
- **Location**: `55-02-PLAN.md`, LOSS_ACCOUNTING dict
- **Issue**: The dict claims `component_ref: True`, `net_connectivity: True`, etc. but no automated test verifies these claims. The dict could become stale as the adapter evolves.
- **Recommendation**: Add a `test_loss_accounting_accuracy` test that parses a known fixture, round-trips it, and asserts that every field claimed as `True` in `ROUNDTRIP_PRESERVED` actually survives. This is the only way to keep LOSS_ACCOUNTING honest.

---

### Phase 56: EasyEDA Support (56-01, 56-02)

**KiCad Rick Assessment**: EasyEDA is the correct first target for multi-format. The JSON format is well-documented, the tilde-delimited shape array parsing is straightforward, and LCSC/JLCPCB integration is commercially valuable. The parser and writer are well-structured.

#### F-15 (MEDIUM): Lossy reverse mapping for LCSC parts
- **Location**: `56-02-PLAN.md`, `_KICAD_TO_LCSC`
- **Code**: `_KICAD_TO_LCSC: dict[tuple[str, str], str] = {v: k for k, v in _LCSC_TO_KICAD.items()}`
- **Issue**: Multiple LCSC parts map to the same KiCad symbol+footprint (e.g., C25804, C25803, C25805 are all `Device:R` + `R_0805_2012Metric`). The reverse dict construction `{v: k for k, v in ...}` keeps only the LAST entry for each key. `kicad_to_lcsc("Device:R", "Resistor_SMD:R_0805_2012Metric")` returns a single LCSC part number that may not match the original component's value.
- **Recommendation**: Change `kicad_to_lcsc` to return `list[str]` (all matching LCSC parts) instead of `Optional[str]`. Or add value-based matching: `kicad_to_lcsc(symbol, footprint, value="10k")` that filters by component value.

#### F-25 (MEDIUM): Static 50-part mapping does not scale
- **Location**: `56-02-PLAN.md`, `_LCSC_TO_KICAD`
- **Issue**: A static dict of 50 parts covers basic passives but cannot handle the real diversity of LCSC's 100k+ catalog. Users with non-trivial designs will find most components unmapped.
- **Recommendation**: Add a `LcscMappingProvider` protocol with two implementations: `StaticLcscMapping` (the current 50-part dict) and `ApiLcscMapping` (queries LCSC API at runtime). The static version serves as a fast cache; the API version handles unknowns. This also addresses F-15 by querying the API with value constraints.

#### F-19 (LOW): Coordinate precision loss in EasyEdaWriter
- **Location**: `56-01-PLAN.md`, EasyEdaWriter._component_to_lib()
- **Code**: `str(int(x))`, `str(int(y))`
- **Issue**: EasyEDA internally uses 10x-scaled integers (1 unit = 0.1mm). Converting float mm coordinates to int loses sub-mm precision.
- **Recommendation**: Use `str(int(x * 10))` or define a coordinate scaling constant. Document the EasyEDA coordinate system in easyeda_types.py.

---

### Phase 57: Altium Support (57-01, 57-02)

**KiCad Rick Assessment**: Altium support is ambitious but realistic for read-only. The OLE compound document approach via olefile is correct. The feasibility assessment in 57-02 is honest about writing being infeasible. However, the migration tool depends on the unimplemented write path.

#### F-03 (CRITICAL): AltiumMigration outputs JSON, not .kicad_sch
- **Location**: `57-02-PLAN.md`, AltiumMigration.migrate(), line 227
- **Code**: `# TODO: Use KiCadAdapter.abstract_to_schematic_ir() when implemented`
- **Impact**: The migration tool's stated purpose is "Converts Altium .SchDoc files to KiCad .kicad_sch files" but it actually outputs `.abstract.json`. This is not what users expect from `altium2kicad`.
- **Root cause**: Depends on `KiCadAdapter.abstract_to_schematic_ir()` which is `raise NotImplementedError` in 55-02 (F-01).
- **Recommendation**: Phase 57-02 MUST NOT be marked complete until `abstract_to_schematic_ir()` is implemented. Either:
  1. Implement the write path in 55-02 (preferred), or
  2. Add a 55-03 plan for the write path, and make 57-02 depend on 55-03, or
  3. Accept that 57-02 outputs only JSON and rename the tool to `altium2abstract` with a documented limitation.

#### F-06 (HIGH): OLE binary parsing attack surface
- **Location**: `57-01-PLAN.md`, AltiumParser
- **Issue**: olefile parses OLE compound documents (Microsoft Structured Storage). This is a well-known attack surface for:
  - ZIP/OLE bombs (deeply nested or compressed streams)
  - Path traversal in OLE stream names
  - Integer overflow in stream size headers
- **Mitigation in plan**: Threat T-57-01-02 mentions "malformed .SchDoc files fail gracefully" but no specific validation is specified.
- **Recommendation**: Add to must_haves truths: "AltiumParser validates OLE stream size before reading (max 50MB per stream)", "olefile.open() is wrapped in try/except with specific error messages", "Stream names are validated against expected Altium stream names (FileHeader, Additional, etc.)". Add a `max_file_size_mb` config.

#### F-16 (MEDIUM): No .SchDoc fixture generation specified
- **Location**: `57-01-PLAN.md`, tests/fixtures/altium/minimal.SchDoc
- **Issue**: The plan references a minimal .SchDoc fixture file but does not specify how to create it. OLE compound documents are binary -- they cannot be hand-written like JSON or XML fixtures.
- **Recommendation**: Add a task or note: "Generate minimal.SchDoc using a Python script that uses olefile to create a minimal OLE container with the required FileHeader stream containing a single Component record." Alternatively, find a minimal .SchDoc from a public source and include it with attribution.

---

### Phase 58: Eagle + OpenWater (58-01, 58-02)

**KiCad Rick Assessment**: Eagle XML format is well-documented and the parser approach using `xml.etree.ElementTree` is correct (standard library, no extra deps). The Format Registry is the right capstone architecture. OpenWater as a proof-of-concept is reasonable.

#### F-24 (CRITICAL): Dependency chain blocks Format Registry
- **Location**: `58-02-PLAN.md` depends on 58-01, 55-02, 56-01
- **Issue**: The Format Registry's `convert` CLI (`kicad-agent convert --from eagle --to kicad`) requires `KiCadAdapter.abstract_to_schematic_ir()` which is NotImplementedError. The entire cross-format conversion pipeline is blocked by F-01.
- **Recommendation**: Same as F-01/F-03 -- the write path must be implemented before the Format Registry can deliver its core value proposition.

#### F-17 (MEDIUM): OpenWater format unspecified
- **Location**: `58-02-PLAN.md`, OpenWater parser
- **Issue**: The plan says "If OpenWater format is accessible: minimal parser that registers with FormatRegistry" but never specifies what OpenWater's file format is, what file extensions it uses, or what its internal structure looks like.
- **Recommendation**: Either:
  1. Research OpenWater's actual format and specify it in the plan, or
  2. Replace OpenWater with a known format (e.g., gEDA gschem, OrCAD, DipTrace), or
  3. Use a synthetic format for the proof-of-concept (e.g., "SimpleJSON" -- a trivial JSON circuit format defined in the plan itself).

#### F-27 (MEDIUM): Eagle gate information lost
- **Location**: `58-01-PLAN.md`, gate handling
- **Issue**: Eagle uses gate-based symbols (e.g., NE5532 has gate "A" and gate "B" for the two op-amps, plus a power gate). The plan says "all gates merged" into a single AbstractComponent, but this loses which pins belong to which gate. If writing back to Eagle, the gate structure cannot be reconstructed.
- **Recommendation**: Add an optional `gate: str | None = None` field to `AbstractPin`. Eagle parser sets it to the gate identifier. Other adapters leave it as None. This preserves gate structure without forcing non-Eagle formats to understand gates.

---

## SLC Validation (Slick Rick)
**Status**: FAIL

### SLC Anti-Patterns Detected
- **NotImplementedError stubs**: 1 found (F-01: `abstract_to_schematic_ir`)
- **Empty return stubs**: 3 found (F-02: `_extract_nets`, `_extract_sheets`, `_extract_pins`)
- **TODO without ticket**: 1 found (F-03: `# TODO: Use KiCadAdapter.abstract_to_schematic_ir()`)
- **Hardcoded placeholder values**: 1 found (F-18: `parameter_coverage = 0.0`)
- **Incomplete implementations**: 2 found (F-03: migration tool outputs JSON not .kicad_sch; F-24: Format Registry cannot convert)

### SLC Criteria Assessment
- [ ] **Simple**: YES -- clear module boundaries, well-defined interfaces
- [ ] **Lovable**: PARTIAL -- the multi-format vision is compelling but stubs undermine trust
- [x] **Complete**: NO -- four critical SLC violations block the complete user journey

**SLC Decision**: REJECT

---

## Security Review (Rick C-137)
**Status**: FAIL (3 HIGH findings)

### Vulnerabilities Found

#### F-04: eval() in predicate evaluation (MEDIUM-HIGH)
- **Location**: `52-01-PLAN.md:283`
- **Category**: Code Injection (CWE-94)
- **Confidence**: 0.9
- **Exploit Scenario**: A developer-defined predicate string contains malicious code. With `__builtins__` restricted, the attack surface is limited to arithmetic on parameter values. However, `eval` can still access `__class__`, `__subclasses__`, etc. through Python object traversal.
- **Fix**: Replace with `ast.literal_eval` extended with comparison operators, or pre-compile predicates as code objects.

#### F-05: Download integrity gap (HIGH)
- **Location**: `53-01-PLAN.md`
- **Category**: Missing Authentication (CWE-346)
- **Confidence**: 0.85
- **Exploit Scenario**: Man-in-the-middle substitutes a malicious archive for a GitHub download. No hash check means the malicious content enters the training corpus.
- **Fix**: Validate download against GitHub's commit SHA. Add `max_download_size_mb` limit.

#### F-06: OLE binary parsing (HIGH)
- **Location**: `57-01-PLAN.md`
- **Category**: Improper Input Validation (CWE-20)
- **Confidence**: 0.80
- **Exploit Scenario**: Malformed .SchDoc with crafted OLE headers causes memory exhaustion or buffer overflow in olefile.
- **Fix**: Add stream size limits, wrap olefile calls in try/except, validate stream names.

#### F-07: MCP stdio no auth (HIGH)
- **Location**: `54-01-PLAN.md`
- **Category**: Missing Authentication (CWE-306)
- **Confidence**: 0.75
- **Exploit Scenario**: Any local process spawns the MCP edit server and issues destructive commands on KiCad files.
- **Fix**: Document as known limitation. Add command allowlist for the VS Code extension context.

---

## Code Quality Review (Rick Sanchez)
**Status**: FAIL (stub methods)

### Issues Found

The plans are generally well-structured with good TDD coverage. The main code quality issues are the stub implementations in 55-02 (F-01, F-02) which violate the "no stub methods" principle. The code shown in plan implementations is clean Python with proper type annotations, Pydantic validation, and error handling.

Key quality observations:
- TDD is properly specified (RED/GREEN/REFACTOR) in all 19 plans
- Interface contracts are documented with code snippets from existing modules
- Threat models are included for every plan
- Verification commands are specified for every task

---

## Historical Context and Pattern Wisdom (Rickfucius)
**Status**: PATTERNS FOUND

### Relevant Patterns

#### Template-Based Generation (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Phase 52 uses deterministic template-based generation, mirroring the existing `training/dataset.py` and `training/generator.py` patterns. Consistent with the project's reproducibility philosophy.

#### Format Adapter Pattern (follows LTspice precedent)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Phases 56-58 follow the pattern established by `ltspice/asc_parser.py` and `ltspice/symbol_mapper.py` -- format-specific parser that converts to internal representation. The Abstract AST formalizes this into a reusable pattern.

#### Stub Anti-Pattern (VIOLATED)
- **Category**: anti-pattern
- **Pattern Compliance**: Violates
- **Explanation**: Phase 55-02 contains `raise NotImplementedError` and `return []` stubs. The project's SLC policy forbids stub methods. Previous Council reviews (wave 41) also flagged this pattern and required full implementation.

#### ProcessPoolExecutor Pattern (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Phase 52-02 reuses the `_generate_chunk` subprocess pattern from `training/generator.py` with dict serialization to avoid pickling issues. This is the correct approach for CPU-bound parallel generation.

---

## Final Council Decision

**Evil Morty's Ruling**: **REJECT**

### Decision Summary
- **SLC Validation**: FAIL (4 critical SLC violations)
- **Security Review**: FAIL (3 HIGH, 1 MEDIUM-HIGH)
- **Code Quality**: FAIL (stub methods in keystone phase)
- **Design Review**: PASS with recommendations
- **Historical Context**: PATTERNS FOUND (1 violation)

### All Issues to Fix Before Execution (ordered by dependency)

**Critical path (blocks everything):**
1. F-01: Implement `abstract_to_schematic_ir()` in 55-02 (remove NotImplementedError)
2. F-02: Implement `_extract_nets()`, `_extract_sheets()`, `_extract_pins()` in 55-02 (remove empty returns)
3. F-24: After F-01 is fixed, verify 57-02 and 58-02 dependency chain is unblocked

**Security fixes (blocks merge):**
4. F-05: Add download integrity checks to 53-01
5. F-06: Add OLE stream validation and size limits to 57-01
6. F-07: Document MCP stdio limitation in 54-01 README
7. F-04: Replace or restrict eval() in 52-01

**Architecture fixes (blocks correctness):**
8. F-08: Resolve tuple serialization in AbstractNet.pin_refs
9. F-03: Fix AltiumMigration to output .kicad_sch (blocked by F-01)
10. F-15: Fix lossy reverse mapping in LcscComponentMapper
11. F-27: Add gate field to AbstractPin for Eagle compatibility

**Functional completeness:**
12. F-09: Define FormatMetadata model for AbstractComponent properties
13. F-10: Add AbstractBus model for Eagle/KiCad bus support
14. F-11: Add LOSS_ACCOUNTING verification test
15. F-12: Replace string predicates with callable pattern
16. F-13: Specify complexity_score formula in 53-01
17. F-14: Add MCP server detection to VS Code extension
18. F-16: Specify .SchDoc fixture generation method
19. F-17: Specify OpenWater format or replace with known format
20. F-25: Add LcscMappingProvider protocol for extensibility

**Low priority:**
21. F-18: Implement parameter_coverage or remove the field
22. F-19: Fix EasyEdaWriter coordinate scaling
23. F-20: Fix GPL license classification
24. F-21: Add engines field to VS Code extension package.json
25. F-22: Fix CircuitTemplate predicate type annotation
26. F-23: Add __repr__ to Abstract AST models
27. F-26: Add workspace trust check for auto-ERC

### Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): REJECT -- stub methods in keystone phase
- Rick C-137 (Security): REJECT -- 3 HIGH security findings
- Slick Rick (SLC): REJECT -- 4 critical SLC violations

**Wave Beta (Wisdom):**
- Rick Prime (Design): REJECT (with recommendations) -- good architecture, stubs undermine it
- Rickfucius (Historian): REJECT -- stub anti-pattern violates established project norms

**Wave Gamma (Domain):**
- KiCad Rick (EDA): REJECT -- the Abstract AST is the right design, but the reference adapter must be complete
- Component Rick (Supply Chain): REJECT -- LCSC mapping is too limited and lossy

**Wave Epsilon (Fresh Eyes):**
- Spectral Rick (Frequency): ABSTAIN -- no frequency-domain concerns in these plans
- Connector Rick (Interfacing): REJECT -- format interconnections are blocked by the stub write path

**Final:**
- **Evil Morty**: REJECT

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. Every agent reviews. Every finding is fixed. Fresh eyes catch blind spots. Domain experts catch details. Evil Morty makes the final call. No appeals."

**Review Completed**: 2026-05-31
**Review Duration**: Wave 4 of 6 (Phases 52-58)
**Total Phases Reviewed**: 7 (14 plans)
