# Pitfalls — v7.0 Vendor-Neutral Manufacturing Layer

## Pitfall 1: Stale DRC Profile Values

**Risk:** The PCBWay `.kicad_dru` file is from 2023-10 (nearly 3 years old). The annular ring value (0.25mm) is more conservative than PCBWay's current advertised capability (0.15mm). Users may get false DRC failures on designs that PCBWay would actually accept.

**Prevention:**
- In Phase 2, cross-check each profile against the vendor's current published capabilities page
- Update the PCBWay annular ring to 0.15mm (verified current capability)
- Add a "last verified" date comment at the top of each `.kicad_dru` file
- Consider a `drc_profile_validate` op that flags rules older than 12 months

**Phase to address:** Phase 2 (Vendor DRC Profiles)

## Pitfall 2: title_block Parsing Fragility

**Risk:** `title_block` is currently in `_UNSUPPORTED_ELEMENTS` in `pcb_native_parser.py`. Adding it requires careful S-expression parsing — the `(title_block ...)` element has nested fields `(title "...")`, `(date "...")`, `(rev "...")`, `(company "...")`, and numbered comments `(comment 1 "...")`. Getting the quote/comment escaping wrong could corrupt the PCB file on write-back.

**Prevention:**
- Follow the existing `NativeStackup` parsing pattern exactly (it handles similar nested structures)
- Write-back must use the same raw S-expression preservation strategy (the parser preserves unsupported elements as raw text — verify title_block round-trips correctly before enabling typed access)
- Test with fixtures that have comments, empty fields, and special characters in title/company
- KiCad 10 may use unquoted UUIDs (Rule 1 bug pattern seen in Phase 102) — verify title_block field quoting

**Phase to address:** Phase 1 (Board Metadata Foundation)

## Pitfall 3: Vendor Lock-in via Hard-coded Formatting

**Risk:** The existing `export_jlcpcb_bom()` and `enrich_with_lcsc()` are hard-coded to JLCPCB. If Phase 4 (Handoff) calls these directly, we've baked in vendor lock-in — the exact thing this milestone is designed to avoid.

**Prevention:**
- Phase 4 must use a profile-driven formatter, not call `export_jlcpcb_bom()` directly
- The `ManufacturerProfile` extension should include output format spec (BOM columns, naming convention, zip structure)
- Refactor `export_jlcpcb_bom` into `export_bom(profile=...)` with JLCPCB as one profile, not a separate function
- Default to a generic format when no vendor profile is specified

**Phase to address:** Phase 4 (Handoff Package)

## Pitfall 4: Build Directory Pollution / Git Noise

**Risk:** Build artifacts (Gerbers, zips, renders) are binary files that should NOT be committed to git. If the `builds/` directory is inside the project root, every build creates untracked noise.

**Prevention:**
- Add `builds/` to `.gitignore` in Phase 3
- Consider making the build output directory configurable (default: `builds/` in project root, but overridable to a temp dir or external location)
- The manifest and readme CAN be committed if desired (they're text) — make this opt-in, not default

**Phase to address:** Phase 3 (Versioned Build System)

## Pitfall 5: Manifest Incompleteness (False Confidence)

**Risk:** A build manifest that claims to be "complete" but is missing required artifacts (e.g., no netlist, no impedance spec) gives false confidence that the handoff package is manufacturable.

**Prevention:**
- Reuse the existing `ManufacturingReadinessGate` (5 checks) as a hard gate — if it fails, no build is created
- The manifest must validate required artifact names: `{gerbers, drill, bom, cpl}` minimum (already enforced by `validate_manifest()`)
- Add vendor-specific requirements: PCBA builds require BOM + P&P; bare-board builds don't
- DRC and ERC must be clean before build creation (not just exported)

**Phase to address:** Phase 3 (Builds) + Phase 4 (Handoff)

## Pitfall 6: Profile Licensing / Attribution

**Risk:** The PCBWay DRC file has NO license. The AISLER files have NO license. Using them without attribution could create issues. The Cimos aggregator (MIT) and labtroll (no license) have different terms.

**Prevention:**
- The Cimos aggregator (MIT) is the cleanest source — prefer it for JLCPCB + PCBWay
- Add attribution comments in each profile file noting the source repo + license status
- The `.kicad_dru` files are data (rules/constraints), not code — but still include source attribution
- Document in the module docstring that profiles are vendor-published reference rules

**Phase to address:** Phase 2 (Vendor DRC Profiles)

## Pitfall 7: Large File Handling in Zips

**Risk:** STEP files and high-res renders can be large (10-100MB). Zipping them into a handoff package could be slow or create oversized bundles.

**Prevention:**
- Use streaming zip creation (write files directly to zip, not via memory)
- Make STEP and render inclusion optional (bare-board orders don't need STEP)
- Profile-driven: the vendor profile specifies which artifacts are required vs optional

**Phase to address:** Phase 4 (Handoff Package)

## Pitfall 8: API Adapter Scope Creep (Phase 6)

**Risk:** Phase 6 (Vendor API Adapters) is marked DEFERRED but could expand massively. PCBWay's Partner API has quote + order + shipping + status. MacroFab's API has quote + order + inventory. JLCPCB has quote + order + parts. Building all three fully is a milestone unto itself.

**Prevention:**
- P6 is explicitly DEFERRED in the roadmap — it should be a separate follow-on milestone, not crammed into v7.0
- The `ManufacturerClient` ABC should be defined in P5 (the interface), but adapters are stubbed/deferred
- If P6 is attempted, scope it to QUOTE ONLY first (no order placement) — quoting is read-only and safe; ordering has financial consequences

**Phase to address:** Phase 6 (DEFERRED — likely separate milestone)

## Integration Pitfalls (When Adding to Existing System)

### IP-1: Registry Count Assertion

The test `tests/test_registry.py:26` asserts `len(OPERATION_REGISTRY) == 142`. Every new op added in v7.0 requires updating this count. Forgetting causes a test failure.

**Prevention:** Update the count in the same commit that adds ops.

### IP-2: Schema Union Drift

`validate_registry_completeness()` cross-checks registry op_types against the schema union's variants. If you add to the registry but forget the schema union (or vice versa), this fails.

**Prevention:** Add schema + registry + handler in one atomic change per op group.

### IP-3: Handler Registry Merge

New handlers in `ops/handlers/manufacturing.py` must be merged in `handlers/__init__.py`. Forgetting this means the handler never executes (silent no-op).

**Prevention:** Follow the `_BOM_HANDLERS` merge pattern exactly; test that the handler is actually invoked.

### IP-4: CROSS_FILE_OP_TYPES for Multi-file Ops

`build_create` and `build_handoff_export` are multi-file ops (they touch multiple source files + create artifacts). They must be added to `CROSS_FILE_OP_TYPES` in `execution.py:112` to get the `ir_map` dispatch path.

**Prevention:** Check `ops/execution.py` dispatch routing for each new op.
