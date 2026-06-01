# The Council of Ricks Plan Review Report

## Stack Assessment

**Detected Project Stack:**
- **Project Type**: Python (kicad-agent)
- **Domain**: EDA / KiCad automation / AI tooling / demo showcase
- **Build System**: pip install -e . (Python)
- **Testing**: pytest (135+ test files, 1392+ tests)
- **CI/CD**: GitHub Actions (build.yml, ci.yml, publish.yml)
- **Key Dependencies**: Pydantic v2, kiutils, networkx, FastAPI (new in Phase 51)
- **CLI Framework**: argparse with _SUBCOMMANDS routing pattern
- **SVG Processing**: xml.etree.ElementTree (stdlib, no external deps)

**Council Wave Composition:**
- **Wave Alpha (Core):** Rick Sanchez (Code Quality), Rick C-137 (Security), Slick Rick (SLC), Evil Morty (Synthesis)
- **Wave Beta (Wisdom):** Rick Prime (Design), Rickfucius (Historian)
- **Wave Gamma (Domain):** KiCad Rick (PCB/EDA specialist), Sentinel Rick (Agentic AI Security -- playground upload boundary)
- **Wave Delta (Pipeline):** GSD Plan Checker (plan review specialist)
- **Wave Epsilon (Fresh Eyes):** Spectral Rick (frequency domain perspective on signal flow visualization), Go Bubble Tea Rick (terminal UI patterns for CLI design consistency)
- **Total reviewers this session:** 10/84

---

## Executive Summary
- **Total Issues**: 19
- **Critical (SLC)**: 2
- **High (Security/Architecture)**: 5
- **Medium (Functional)**: 8
- **Low (Style/Completeness)**: 4

---

## Historical Context and Pattern Wisdom (Rickfucius)
**Status**: PATTERNS FOUND

### Relevant Patterns Found

#### CLI Subcommand Pattern (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: The existing `_SUBCOMMANDS` set and `_handle_*` / `_build_*_parser` pattern in `cli.py` is well-established with 9 subcommands (collect, erc, drc, export, context, route, analyze, component-search, ai-stats). Plans 49-01 and 51-01 correctly follow this pattern with `_handle_demo` / `_build_demo_parser` and `_handle_playground` / `_build_playground_parser`.
- **Recommendation**: Follow pattern -- plans are consistent.

#### Template-Based Circuit Generation (follows existing pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Plan 49-02's `DemoTemplate` wrapping `GenerationIntent` follows the existing `generation/intent.py` and `generation/pipeline.py` pattern where `generate_design()` takes a `GenerationIntent` and produces a complete project. Templates are deterministic and programmatic.
- **Recommendation**: Follow pattern.

#### ERC Pipeline Integration (follows existing pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: The `_run_erc` / `_auto_fix` / re-ERC cycle in 49-01 mirrors the existing `erc_auto_fix.py` pattern. The function signature `erc_auto_fix(ir, file_path, max_iterations=3)` is correctly referenced and the lazy import pattern handles the case where it is unavailable.
- **Recommendation**: Follow pattern.

### Anti-Patterns Detected

#### erc_auto_fix Signature Mismatch (49-01-PLAN.md)
- **Category**: code
- **Problem**: Plan 49-01 calls `erc_auto_fix(schematic_path, max_iterations=3)` with just a path argument. The actual function signature is `erc_auto_fix(ir: SchematicIR, file_path: Path, max_iterations: int = 3, mode: str = "symptom", fix_classes: list[str] | None = None)` -- it requires an `ir` (SchematicIR) as the first argument, not a path. This will crash at runtime.
- **Historical Evidence**: The erc_auto_fix module was built in Phase 35 (remaining ops gaps) with this two-argument signature for good reason -- it needs the parsed IR to dispatch repairs.
- **Current Violations**: 49-01-PLAN.md Task 2, line in `_auto_fix` method.
- **Recommendation**: Fix the call to parse the schematic first, then pass the IR. Example: `ir = SchematicIR.from_file(schematic_path)` then `erc_auto_fix(ir, schematic_path, max_iterations=3)`.

#### SVG XSS Vector Unaddressed (50-01-PLAN.md)
- **Category**: security
- **Problem**: SVG files can embed `<script>` tags and `onclick` handlers. Plan 50-01 uses `xml.etree.ElementTree` to parse and modify SVGs but never sanitizes the output. When the annotated SVG is served in Phase 51's playground (inline SVG preview in browser), any JavaScript embedded in the original KiCad SVG would execute. Plan 51-01's `/api/preview/{session_id}` endpoint returns raw SVG via `FileResponse` with `media_type="image/svg+xml"`, which browsers render including JavaScript.
- **Historical Evidence**: OWASP lists SVG as an XSS vector. Phase 24 Council audit specifically flagged security hardening.
- **Current Violations**: 50-01-PLAN.md (no sanitization), 51-01-PLAN.md (serves unsanitized SVG).
- **Recommendation**: Add SVG sanitization to `svg_utils.py` that strips `<script>`, `onclick`, `onerror`, and other event handlers before writing annotated output. In playground, serve SVG as `Content-Disposition: inline` with CSP headers, or convert to `<img src>` tag (which neutralizes scripts) instead of inline SVG.

**Rickfucius Decision**: FIX VIOLATIONS -- erc_auto_fix signature mismatch will cause runtime crash; SVG XSS is a real attack vector in the playground context.

---

## SLC Validation (Slick Rick)
**Status**: PASS (with 2 critical findings requiring plan revision)

### SLC Anti-Patterns Detected
- **Workarounds**: 0 found
- **Stub Methods**: 0 found (Phase 24 remediation respected)
- **TODO/FIXME without tickets**: 0 found
- **Incomplete Implementations**: 2 found (see below)

### SLC Criteria Assessment

- [x] **Simple**: Obvious purpose, minimal learning
  - [Intuitive interface? yes] `kicad-agent demo` is self-explanatory. `kicad-agent playground` is standard web-tool naming.
  - [Self-explanatory features? yes] `--template`, `--list`, `--output-dir` flags follow argparse conventions.
  - [Minimal docs needed? yes] `--list` provides inline documentation. No manual needed.

- [x] **Lovable**: Delightful to use, builds trust
  - [Polished design? yes] SVG annotations with numbered red circles and legend are professional quality. Visual diff with green/red highlighting is intuitive.
  - [Smooth interactions? yes] One-command demo from template to SVG in under 60 seconds. WebSocket for real-time feedback in playground.
  - [Graceful errors? yes] kicad-cli unavailability is handled gracefully (ERC returns None, SVG render returns empty list).
  - [Celebrated successes? yes] DemoReport JSON with duration, violation delta, and SVG paths provides satisfying output.

- [ ] **Complete**: Full user journey, no gaps
  - [All APIs implemented? partial] erc_auto_fix call signature is wrong -- will crash at runtime (see CRITICAL findings).
  - [Edge cases handled? partial] VisualDiffer handles identical SVGs but the comment in VisualDiffResult.docstring says "wait, reversed" on line 178 of 50-02, suggesting the schema definition was written mid-thought and not cleaned up.
  - [No broken flows? partial] Demo pipeline flow is complete. Playground upload/execute/ERC/DRC flow is complete. But temp directory cleanup in playground is not specified.

### Critical SLC Violations

#### SLC-1: erc_auto_fix signature mismatch -- runtime crash (49-01-PLAN.md Task 2)
- **Severity**: CRITICAL
- **Description**: `_auto_fix` calls `erc_auto_fix(schematic_path, max_iterations=3)` but the actual function requires `(ir: SchematicIR, file_path: Path, ...)` as first two arguments. This will raise `TypeError` at runtime and abort the demo pipeline at Stage 4.
- **Fix**: Parse the schematic to get an IR before calling erc_auto_fix. Update the `_auto_fix` method to: (1) parse the schematic into a SchematicIR, (2) call `erc_auto_fix(ir, schematic_path, max_iterations=3)`.

#### SLC-2: Playground temp directory never cleaned up (51-01-PLAN.md)
- **Severity**: HIGH
- **Description**: Upload files are stored with UUID names in a temp directory, but no cleanup mechanism is specified. No `atexit` handler, no background task, no TTL-based cleanup. If a user runs `kicad-agent playground` for an extended session, uploaded files accumulate indefinitely. More critically, if the server crashes, orphaned files persist.
- **Fix**: Add either: (a) a startup message noting temp directory location, (b) an `atexit` handler that cleans up on graceful shutdown, (c) a TTL-based cleanup that removes files older than N minutes, or (d) a `--cleanup` flag. Option (b) with `tempfile.TemporaryDirectory()` is simplest and most reliable.

**SLC Decision**: CONDITIONAL PASS -- fix erc_auto_fix signature and add temp cleanup before execution proceeds.

---

## Security Review (Rick C-137)
**Status**: FAIL -- SVG XSS and session management issues must be addressed

### Vulnerabilities Found

#### SEC-1: SVG XSS via unsanitized kicad-cli output (50-01, 51-01)
- **Severity**: HIGH
- **Category**: xss
- **Description**: KiCad-generated SVGs are not sanitized before serving to browsers. SVG is an XML format that supports `<script>` tags, event handlers (`onclick`, `onerror`, `onload`), and `<foreignObject>` with embedded HTML/JS. When Phase 51's playground serves these SVGs inline (or via `FileResponse`), any embedded JavaScript executes in the user's browser.
- **Location**: `src/kicad_agent/spatial/svg_utils.py` (to be created), `src/kicad_agent/playground/api.py` (to be created)
- **Exploit Scenario**: A malicious .kicad_sch file uploaded to the playground could contain component names that, when rendered to SVG by kicad-cli, produce executable JavaScript in the SVG output. When the playground's `/api/preview/{session_id}` serves this SVG, the script executes.
- **Fix Recommendation**: (1) Add `sanitize_svg(root: ET.Element) -> None` to `svg_utils.py` that strips all elements with tag `script`, removes all attributes starting with `on` from all elements, and removes `<foreignObject>` elements. (2) In playground's preview endpoint, run sanitization before serving. (3) Alternatively, serve SVG as `<img src="/api/preview/{sid}">` in the frontend (img-tag SVG does not execute scripts).
- **Confidence**: 0.95

#### SEC-2: WebSocket lacks origin validation (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: csrf
- **Description**: The WebSocket handler in `ws.py` calls `await websocket.accept()` without checking the `Origin` header. Any website can open a WebSocket connection to `ws://localhost:8000/ws` and execute operations. Combined with the `/api/execute` endpoint, this allows cross-origin operation execution.
- **Location**: `src/kicad_agent/playground/ws.py` (to be created)
- **Fix Recommendation**: Add origin validation in the WebSocket accept: check that `websocket.headers.get("origin", "")` is either empty or matches `localhost`/`127.0.0.1`. Reject connections from other origins.
- **Confidence**: 0.85

#### SEC-3: Playground session state is in-memory only (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: denial_of_service
- **Description**: `request.app.state.sessions` is a plain dict that grows unboundedly. Each upload adds an entry. No maximum session count is specified. An attacker could upload thousands of files to exhaust memory.
- **Location**: `src/kicad_agent/playground/api.py` (to be created)
- **Fix Recommendation**: Cap `sessions` dict at a reasonable limit (e.g., 100 sessions). Evict oldest when limit is reached. Add `MAX_SESSIONS = 100` constant.
- **Confidence**: 0.80

#### SEC-4: Path traversal check is incomplete (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: path_traversal
- **Description**: The filename validation checks for `".." in filename` but this string-match approach can be bypassed with URL-encoded sequences or Unicode normalization tricks. Also, the check does not account for `Path(filename).suffix` extracting the suffix before validation -- if filename is `"foo.kicad_sch/../../../etc/passwd"`, the suffix extraction could behave unexpectedly.
- **Location**: `src/kicad_agent/playground/api.py` `_validate_filename()` (to be created)
- **Fix Recommendation**: Use `Path(filename).name` to extract just the filename (stripping any path components), then validate. Replace the `".." in filename` check with `Path(filename).resolve().is_absolute()` or simply use `PurePosixPath(filename).name` to guarantee no path separators.
- **Confidence**: 0.82

#### SEC-5: No rate limiting on upload endpoint (51-01-PLAN.md)
- **Severity**: LOW
- **Category**: denial_of_service
- **Description**: The `/api/upload` endpoint has a 10MB file size limit but no rate limit. An attacker can upload 10MB files as fast as the server accepts them, filling the temp directory and exhausting disk space.
- **Fix Recommendation**: Add a simple per-IP rate limiter (e.g., max 10 uploads per minute) or use FastAPI's middleware for rate limiting.
- **Confidence**: 0.75 (below 0.8 threshold -- informational)

**Security Summary**:
- High Severity: 1 (SVG XSS)
- Medium Severity: 3 (WebSocket origin, session DoS, path traversal)
- Low Severity: 1 (upload rate limiting)
- False Positives Filtered: 0

**Security Decision**: REJECT -- SVG XSS at 0.95 confidence is a real vulnerability that must be mitigated before the playground serves SVG to browsers.

---

## Code Quality Review (Rick Sanchez)
**Status**: FAIL

### Issues Found

#### CODE-1: erc_auto_fix signature mismatch -- will crash at runtime (49-01-PLAN.md Task 2)
- **Severity**: CRITICAL
- **Category**: bug
- **Description**: The plan's `_auto_fix` method calls `erc_auto_fix(schematic_path, max_iterations=3)`. The actual function signature is `erc_auto_fix(ir: SchematicIR, file_path: Path, max_iterations: int = 3)`. Missing the required `ir` parameter. This is a runtime TypeError.
- **Location**: 49-01-PLAN.md, `_auto_fix` method implementation
- **Engineering Principle**: Verify function signatures against actual source before writing call sites.
- **Fix Recommendation**: Parse the schematic first: `ir = SchematicIR.from_file(schematic_path)` then `erc_auto_fix(ir, schematic_path, max_iterations=3)`.

#### CODE-2: VisualDiffResult docstring contains unfinished note (50-02-PLAN.md)
- **Severity**: MEDIUM
- **Category**: code_quality
- **Description**: The `VisualDiffResult` docstring says `removed_count: Number of elements in 'after' but not in 'before' (wait, reversed).` -- the "(wait, reversed)" is clearly an authoring artifact left in the plan. The actual implementation correctly describes it as elements in 'before' not in 'after', but the docstring as written is confusing and will propagate into the codebase if copied literally.
- **Location**: 50-02-PLAN.md, `VisualDiffResult` class docstring
- **Engineering Principle**: Clean specifications produce clean code.
- **Fix Recommendation**: Remove "(wait, reversed)" and write the correct description: `removed_count: Number of elements in 'before' but not in 'after'.`

#### CODE-3: _parse_erc_count heuristic is fragile (49-01-PLAN.md Task 2)
- **Severity**: MEDIUM
- **Category**: robustness
- **Description**: The `_parse_erc_count` method counts non-empty lines that do not start with "ERC ", "Running", or "Info". This heuristic will miscount on different kicad-cli versions or locales. The existing `erc_parser.py` module already has `parse_erc()` that returns structured `ErcViolation` objects with proper parsing -- the plan should use that instead of reimplementing a fragile parser.
- **Location**: 49-01-PLAN.md, `_parse_erc_count` method
- **Engineering Principle**: Reuse existing parsers instead of writing ad-hoc heuristics.
- **Fix Recommendation**: Replace `_run_erc` and `_parse_erc_count` with a call to `parse_erc(schematic_path)` from `erc_parser.py`. Return `len(violations)` for the count. This gives structured data that can also feed into SVG annotation later.

#### CODE-4: DemoReport missing errors field in must_haves truths (49-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: consistency
- **Description**: The must_haves truths section lists `DemoReport` fields as `template_used, stages_completed, erc_before, erc_after, svg_paths, duration_seconds, success` but the actual implementation includes `errors: list[str]` and `project_dir: str | None`. The truths section does not mention these fields, meaning the verification step would not check for them.
- **Location**: 49-01-PLAN.md, must_haves truths
- **Fix Recommendation**: Update must_haves truths to include `errors` and `project_dir` fields.

#### CODE-5: VisualDiffer signature collision risk (50-02-PLAN.md)
- **Severity**: MEDIUM
- **Category**: robustness
- **Description**: `_collect_signatures` uses `(tag, x, y)` as signature key. If two elements have the same tag and position (e.g., overlapping text labels), only the first is kept (`if sig not in signatures`). This means identical-position elements are silently deduplicated, producing incorrect diff counts.
- **Location**: 50-02-PLAN.md, `_collect_signatures` method
- **Engineering Principle**: Handle all edge cases in comparison logic.
- **Fix Recommendation**: Append a counter to duplicate signatures: `sig = f"{tag}:{x},{y}#{count}"` or use a list of tuples instead of a dict.

#### CODE-6: Phase 51 playground does not declare FastAPI dependency (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: completeness
- **Description**: The playground plan imports `from fastapi import ...` and `from fastapi.testclient import TestClient` but does not specify adding `fastapi` and `uvicorn` to the project's dependencies (pyproject.toml or setup.cfg). These are not currently in the project's dependencies. The plan will fail at import time without them.
- **Location**: 51-01-PLAN.md, all tasks
- **Engineering Principle**: Declare all dependencies explicitly.
- **Fix Recommendation**: Add a task or step to install FastAPI and uvicorn as optional dependencies: `pip install fastapi uvicorn` and add them to `[project.optional-dependencies]` in pyproject.toml as `playground = ["fastapi>=0.100", "uvicorn>=0.20"]`.

#### CODE-7: CLI routing dispatch needs update for "demo" and "playground" (49-01, 51-01)
- **Severity**: HIGH
- **Category**: completeness
- **Description**: Both plans correctly specify adding to `_SUBCOMMANDS` set and creating `_handle_demo` / `_handle_playground` functions. However, neither plan shows updating the `main()` dispatch `elif` chain in `cli.py` (lines 582-599). The existing code uses explicit `if/elif` for each subcommand. Without adding `elif subcmd == "demo":` and `elif subcmd == "playground":` to `main()`, the routing will not work.
- **Location**: 49-01-PLAN.md Task 3, 51-01-PLAN.md Task 4
- **Engineering Principle**: Complete the integration path.
- **Fix Recommendation**: Both plans must explicitly show adding the `elif` clauses to `main()` dispatch. The existing pattern is clear: `elif subcmd == "demo": _handle_demo(subcmd_argv)`.

**Code Summary**:
- Critical: 1 (erc_auto_fix signature)
- High: 1 (CLI dispatch routing)
- Medium: 5 (docstring, ERC parser reuse, DemoReport fields, signature collision, FastAPI dependency)
- Low: 0

**Code Decision**: REJECT -- erc_auto_fix signature mismatch and missing CLI dispatch updates must be fixed.

---

## Design Review (Rick Prime)
**Status**: PASS (with recommendations)
**Review Mode**: Systematic (80%) -- these are backend/CLI tools, not consumer-facing UI

### Issues Found

#### DES-1: Annotated SVG legend positioned outside viewBox (50-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: visual_hierarchy
- **Description**: The legend is positioned at `y_start = svg_height + 5`, which is below the SVG viewBox. Many SVG viewers (including browsers) clip content outside the viewBox. The legend will be invisible in many viewing contexts.
- **Location**: 50-01-PLAN.md, `_build_legend` method
- **Design Principle**: All visible content must be within the viewport.
- **Fix Recommendation**: Either (a) expand the viewBox height to accommodate the legend, or (b) position the legend inside the existing viewport at the bottom-right corner with a semi-transparent background overlay.

#### DES-2: Playground static files should include favicon (51-01-PLAN.md)
- **Severity**: LOW
- **Category**: polish
- **Description**: The static file list includes `index.html`, `app.js`, `style.css` but no favicon. Browser console will show 404 for `/favicon.ico`. For a "quality 10" demo, this matters.
- **Fix Recommendation**: Add a simple SVG favicon to the static directory and reference it in `index.html`.

**Design Summary**:
- High: 0
- Medium: 1 (legend positioning)
- Low: 1 (favicon)

**Design Decision**: APPROVE with recommendations -- legend positioning should be fixed during execution.

---

## Security Review -- Agent Boundaries (Sentinel Rick)
**Status**: PASS (with recommendations)

### Blast Radius Assessment

The playground introduces a web server boundary that exposes kicad-agent operations to network requests. Key observations:

#### Boundary Analysis

| Boundary | Risk | Mitigation |
|----------|------|------------|
| File upload -> filesystem | Path traversal | UUID-based naming mitigates. Add `PurePosixPath.name` extraction. |
| Upload -> kicad-cli execution | Command injection | kicad-cli called with explicit args (not shell=True). Safe. |
| WebSocket -> handle_operation | Unbounded execution | Operations inherit existing timeouts. Acceptable. |
| Sessions dict -> memory | Unbounded growth | Cap at MAX_SESSIONS. |
| SVG output -> browser | XSS | Sanitize SVG or use img-tag rendering. |

#### Positive Security Patterns

1. **Extension whitelist**: `ALLOWED_EXTENSIONS = {".kicad_sch", ".kicad_pcb"}` -- correctly restrictive.
2. **UUID-based file storage**: Uploads stored as UUID names, not user-supplied filenames.
3. **kicad-cli timeout**: 120s timeout on all subprocess calls, matching existing pattern.
4. **Operation validation**: `/api/execute` calls `validate_operation()` before `handle_operation()`.
5. **Localhost-only**: Documentation specifies port 8000 localhost. No CORS headers configured. Good.

**Agent Security Decision**: APPROVE with SVG sanitization requirement.

---

## KiCad Domain Review (KiCad Rick)
**Status**: PASS

### Domain-Specific Observations

#### KICAD-1: Template GenerationIntent components need real KiCad lib_ids (49-02-PLAN.md)
- **Severity**: LOW
- **Category**: domain_accuracy
- **Description**: The plan lists template component counts (e.g., "RC Low-Pass Filter -- 3 components, 2 nets") but does not specify the actual `library_id` values for each component. The `GenerationIntent` requires valid `library_id` strings (e.g., `Device:R`, `Device:C`, `Amplifier_Operational:LM358`). If these are wrong, `generate_design()` will fail at the symbol resolution stage.
- **Fix Recommendation**: Ensure each template's `ComponentSpec` list uses valid KiCad library identifiers. The basic templates (R, C, op-amp) use standard `Device:` and `Amplifier_Operational:` library references.

#### KICAD-2: SVG coordinate system for annotation (50-01-PLAN.md)
- **Severity**: LOW
- **Category**: domain_accuracy
- **Description**: KiCad SVGs use mm coordinates in the viewBox. The plan correctly identifies this and uses `svg_to_mm()` for conversion. However, KiCad's Y-axis direction (origin at top-left, Y increases downward) matches SVG's coordinate system, so no Y-flip is needed. The plan handles this correctly by not adding a Y-flip.
- **Recommendation**: No action needed -- plan is correct.

**KiCad Decision**: APPROVE -- templates need real lib_ids during execution, not a plan-level blocker.

---

## Findings Summary Table

| ID | Severity | Plan | Description | Must Fix Before Execution |
|----|----------|------|-------------|---------------------------|
| SLC-1 | CRITICAL | 49-01 | erc_auto_fix signature mismatch -- missing `ir` parameter | YES |
| SEC-1 | HIGH | 50-01, 51-01 | SVG XSS -- unsanitized SVG served to browser | YES |
| CODE-1 | CRITICAL | 49-01 | erc_auto_fix signature mismatch (same as SLC-1) | YES |
| CODE-7 | HIGH | 49-01, 51-01 | CLI main() dispatch not updated for new subcommands | YES |
| SLC-2 | HIGH | 51-01 | Playground temp directory never cleaned up | YES |
| SEC-2 | MEDIUM | 51-01 | WebSocket lacks origin validation | YES |
| SEC-3 | MEDIUM | 51-01 | Session state grows unboundedly | YES |
| SEC-4 | MEDIUM | 51-01 | Path traversal check uses string matching | YES |
| CODE-2 | MEDIUM | 50-02 | VisualDiffResult docstring has "(wait, reversed)" artifact | NO (fix during execution) |
| CODE-3 | MEDIUM | 49-01 | _parse_erc_count should reuse erc_parser.parse_erc() | YES (better approach) |
| CODE-4 | MEDIUM | 49-01 | DemoReport must_haves missing `errors` and `project_dir` fields | NO (fix during execution) |
| CODE-5 | MEDIUM | 50-02 | VisualDiffer signature collision for overlapping elements | NO (fix during execution) |
| CODE-6 | MEDIUM | 51-01 | FastAPI/uvicorn not declared as dependencies | YES |
| DES-1 | MEDIUM | 50-01 | SVG legend positioned outside viewBox | NO (fix during execution) |
| SEC-5 | LOW | 51-01 | No rate limiting on upload endpoint | NO |
| DES-2 | LOW | 51-01 | Missing favicon for playground | NO |
| KICAD-1 | LOW | 49-02 | Templates need real KiCad library_id values | NO |
| CODE-8 | LOW | 50-02 | VisualDiffResult schema is in plan only, not linked to 49-01 DemoReport | NO |

---

## Dependency Chain Verification

| Dependency | Declared | Status | Risk |
|------------|----------|--------|------|
| 49-01 depends on 38-01 | YES | Phase 38 is PLANNING, 38-01 has SUMMARY (complete) | LOW -- routing engine exists |
| 49-02 depends on 49-01 | YES | Correct -- templates need pipeline | NONE |
| 50-01 depends on 49-01 | YES | Correct -- annotation needs SVG output | NONE |
| 50-02 depends on 50-01 | YES | Correct -- diff needs annotation engine | NONE |
| 51-01 depends on 50-01 | YES | Correct -- playground needs SVG preview | NONE |
| 49-01 depends on Phase 10 (generate_design) | YES | Shipped v1.1 | NONE |
| 49-01 depends on Phase 3 (ERC/DRC) | YES | Shipped v1.0 | NONE |
| 49-01 depends on Phase 35 (erc_auto_fix) | YES | Shipped v2.2 | NONE |
| 51-01 depends on Phase 30 (MCP server) | YES | Listed in 51-PLAN.md | LOW -- Phase 30 not yet started |

**Note**: Phase 51-PLAN.md lists Phase 30 (MCP Operations Server) as a dependency, but Phase 30 is not yet started per ROADMAP.md. However, plan 51-01 only uses `handle_operation()` and `validate_operation()` from the handler module, not MCP tools. The MCP dependency is listed for "operation schema exposure" but the plan directly calls `get_operation_schema()` which already exists. This dependency can be relaxed or marked as soft.

---

## No React/Build Step Verification

**Status**: PASS

Plan 51-01 explicitly states:
- must_haves truths: "Static HTML/JS frontend with no build step -- vanilla JS, no React"
- Files: `static/index.html`, `static/app.js`, `static/style.css`
- No package.json, no webpack, no vite, no node_modules

The frontend is three static files served by FastAPI's `StaticFiles` mount. Confirmed no build step.

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): REJECT -- erc_auto_fix signature crash, missing CLI dispatch
- Rick C-137 (Security): REJECT -- SVG XSS at 0.95 confidence
- Slick Rick (SLC): CONDITIONAL PASS -- fix signature and temp cleanup

**Wave Beta (Wisdom):**
- Rick Prime (Design): APPROVE -- legend positioning fix during execution
- Rickfucius (Historian): FIX VIOLATIONS -- signature mismatch and XSS are real

**Wave Gamma (Domain):**
- KiCad Rick: APPROVE -- templates need real lib_ids but not a plan blocker
- Sentinel Rick: APPROVE with SVG sanitization requirement

**Wave Delta (Pipeline):**
- GSD Plan Checker: Plans follow GSD format correctly. All have must_haves, tasks with TDD, threat models, verification, and success_criteria. Dependency chains are documented and correct.

**Wave Epsilon (Fresh Eyes):**
- Spectral Rick: Signal flow visualization through annotated schematics is a novel application of frequency-domain thinking to spatial reasoning. The numbered circle + legend pattern maps well to spectral peak annotation. Design is sound.
- Go Bubble Tea Rick: CLI pattern follows existing argparse conventions correctly. The `demo` subcommand with `--template`, `--list`, `--output-dir` is clean. Suggestion: add `--json` flag to `demo` for machine-readable output (the default already prints JSON, so this is a no-op -- but explicit is better than implicit).

---

## Final Council Decision

**Evil Morty's Ruling**: CONDITIONAL APPROVE

### Required Changes Before Execution (8 items)

1. **FIX 49-01**: erc_auto_fix call signature -- add `SchematicIR` parameter. Parse schematic first, then pass IR to erc_auto_fix.
2. **FIX 49-01**: Add `elif subcmd == "demo": _handle_demo(subcmd_argv)` to `main()` dispatch in `cli.py`.
3. **FIX 49-01**: Replace `_parse_erc_count` heuristic with `parse_erc()` from `erc_parser.py`. Return structured `ErcViolation` list for richer downstream use (SVG annotation).
4. **FIX 49-01**: Update must_haves truths to include `errors` and `project_dir` DemoReport fields.
5. **FIX 50-01**: Add `sanitize_svg(root: ET.Element)` to `svg_utils.py` that strips `<script>`, `on*` event attributes, and `<foreignObject>`. Call it in `write_svg()` or in the playground's preview endpoint.
6. **FIX 50-02**: Remove "(wait, reversed)" from VisualDiffResult docstring. Write correct description.
7. **FIX 51-01**: Add `elif subcmd == "playground": _handle_playground(subcmd_argv)` to `main()` dispatch.
8. **FIX 51-01**: Declare `fastapi` and `uvicorn` as optional dependencies in pyproject.toml. Add temp directory cleanup via `tempfile.TemporaryDirectory()` or `atexit`. Add origin validation to WebSocket. Cap sessions dict at MAX_SESSIONS. Use `PurePosixPath.name` for filename extraction.

### Recommended Changes During Execution (6 items)

1. Position SVG legend within viewBox (not below it).
2. Handle VisualDiffer signature collision for overlapping elements.
3. Add favicon to playground static files.
4. Relax Phase 30 dependency for 51-01 (only handler/schema needed, not MCP server).
5. Add `--json` flag to `demo` subcommand (default is already JSON, but explicit is better).
6. Ensure template `library_id` values use valid KiCad library references.

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. The demo must work the first time -- one command, zero surprises."

**Review Completed**: 2026-05-31
**Review Scope**: Phases 49-51 (8 plan files)
**Next Step**: Revise plans per Required Changes, then proceed to execution.
