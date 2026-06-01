# The Council of Ricks Plan Review Report

## Stack Assessment

**Detected Project Stack:**
- **Project Type**: Python (kicad-agent)
- **Domain**: EDA / KiCad automation / AI tooling / demo showcase
- **Build System**: pip install -e . (Python)
- **Testing**: pytest (135+ test files, 1392+ tests)
- **CI/CD**: GitHub Actions (build.yml, ci.yml, publish.yml)
- **Key Dependencies**: Pydantic v2, kiutils, networkx, FastAPI (new in Phase 51)
- **CLI Framework**: argparse with `_SUBCOMMANDS` routing pattern
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
- **Total Issues**: 21
- **Critical (SLC)**: 3
- **High (Security/Architecture)**: 5
- **Medium (Functional)**: 9
- **Low (Style/Completeness)**: 4

---

## Historical Context and Pattern Wisdom (Rickfucius)
**Status**: PATTERNS FOUND

### Relevant Patterns Found

#### CLI Subcommand Pattern (follows established pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: The existing `_SUBCOMMANDS` set and `_handle_*` / `_build_*_parser` pattern in `cli.py` is well-established with 9 subcommands (collect, erc, drc, export, context, route, analyze, component-search, ai-stats). Plans 49-01 and 51-01 correctly follow this pattern with `_handle_demo` / `_build_demo_parser` and `_handle_playground` / `_build_playground_parser`.
- **Recommendation**: Follow pattern -- plans are consistent with the existing convention.

#### Template-Based Circuit Generation (follows existing pattern)
- **Category**: architecture
- **Pattern Compliance**: Follows
- **Explanation**: Plan 49-02's `DemoTemplate` wrapping `GenerationIntent` follows the existing `generation/intent.py` and `generation/pipeline.py` pattern where `generate_design()` takes a `GenerationIntent` and produces a complete project. Templates are deterministic and programmatic, consistent with the project's reproducibility philosophy.
- **Recommendation**: Follow pattern.

#### ERC Pipeline Integration (references existing pattern)
- **Category**: architecture
- **Pattern Compliance**: DEVIATES
- **Explanation**: The `_run_erc` / `_auto_fix` / re-ERC cycle in 49-01 mirrors the existing `erc_auto_fix.py` pattern in concept but the actual function call is wrong. The real signature is `erc_auto_fix(ir: SchematicIR, file_path: Path, max_iterations=3)` but the plan calls `erc_auto_fix(schematic_path, max_iterations=3)`. The required first argument (`ir: SchematicIR`) is missing entirely. This is not a minor deviation -- it will crash at runtime with a `TypeError`.
- **Recommendation**: FIX -- parse schematic to SchematicIR before calling erc_auto_fix.

#### Handler Return Type Pattern (plan violates existing pattern)
- **Category**: code
- **Pattern Compliance**: VIOLATES
- **Explanation**: The existing `handle_operation()` in `handler.py` returns `Union[OperationResult, OperationError]` -- a Pydantic model object, not a string. The existing `cli.py` uses `format_result(result)` to convert to display text, or `result.to_text()`. Plan 51-01's `/api/execute` endpoint calls `handle_operation()` and then does `json.loads(result_str)` which will crash because the return value is not a string.
- **Historical Evidence**: `cli.py` line 10 imports `format_result` for exactly this purpose. The function has always returned model objects.
- **Current Violations**: 51-01-PLAN.md Task 1, `execute_operation` endpoint.
- **Recommendation**: FIX -- use `format_result()` or `result.model_dump_json()` instead of `json.loads()`.

### Anti-Patterns Detected

#### erc_auto_fix Signature Mismatch (49-01-PLAN.md)
- **Category**: code
- **Problem**: Plan calls `erc_auto_fix(schematic_path, max_iterations=3)` with one argument. The actual signature is `erc_auto_fix(ir: SchematicIR, file_path: Path, max_iterations=3, mode="symptom", fix_classes=None)` -- requires SchematicIR as the first argument.
- **Historical Evidence**: The erc_auto_fix module was built in Phase 35 with this two-argument signature because it needs the parsed IR to dispatch repairs intelligently.
- **Current Violations**: 49-01-PLAN.md Task 2, `_auto_fix` method.
- **Recommendation**: Parse the schematic first: `ir = SchematicIR.from_file(schematic_path)` then `erc_auto_fix(ir, schematic_path, max_iterations=3)`.

#### SVG XSS Vector Unaddressed (50-01-PLAN.md, 51-01-PLAN.md)
- **Category**: security
- **Problem**: SVG files can embed `<script>` tags and `onclick` handlers. Plan 50-01 uses `xml.etree.ElementTree` to parse and modify SVGs but never sanitizes the output. When the annotated SVG is served in Phase 51's playground (inline SVG via `innerHTML` in browser), any JavaScript embedded in the original KiCad SVG would execute.
- **Historical Evidence**: OWASP lists SVG as an XSS vector. Inline SVG rendering via `innerHTML` is the most dangerous pattern because it executes scripts.
- **Current Violations**: 50-01-PLAN.md (no sanitization), 51-01-PLAN.md (innerHTML with raw SVG text at line 965).
- **Recommendation**: Add SVG sanitization to `svg_utils.py`. In playground frontend, use `<img src>` instead of `innerHTML` for SVG preview (img-tag SVG does not execute scripts).

**Rickfucius Decision**: FIX VIOLATIONS -- erc_auto_fix signature mismatch will cause runtime crash; handle_operation return type mismatch will cause runtime crash; SVG XSS is a real attack vector in the playground context.

---

## SLC Validation (Slick Rick)
**Status**: CONDITIONAL PASS -- 3 critical findings requiring plan revision before execution

### SLC Anti-Patterns Detected
- **Workarounds**: 0 found
- **Stub Methods**: 0 found (Phase 24 remediation respected)
- **TODO/FIXME without tickets**: 0 found
- **Incomplete Implementations**: 3 found (see below)

### SLC Criteria Assessment

- [x] **Simple**: Obvious purpose, minimal learning
  - [Intuitive interface? yes] `kicad-agent demo` is self-explanatory. `kicad-agent playground` is standard web-tool naming.
  - [Self-explanatory features? yes] `--template`, `--list`, `--output-dir` flags follow argparse conventions.
  - [Minimal docs needed? yes] `--list` provides inline documentation. No manual needed.

- [x] **Lovable**: Delightful to use, builds trust
  - [Polished design? yes] SVG annotations with numbered red circles and legend are professional quality. Visual diff with green/red highlighting is intuitive. Dark-themed playground UI looks polished.
  - [Smooth interactions? yes] One-command demo from template to SVG in under 60 seconds. WebSocket for real-time feedback in playground. Drag-and-drop file upload.
  - [Graceful errors? yes] kicad-cli unavailability is handled gracefully (ERC returns None, SVG render returns empty list). Demo pipeline catches all exceptions.
  - [Celebrated successes? yes] DemoReport JSON with duration, violation delta, and SVG paths provides satisfying output. Markdown report with embedded SVGs.

- [ ] **Complete**: Full user journey, no gaps
  - [All APIs implemented? no] erc_auto_fix call signature is wrong (CRITICAL). handle_operation return type is wrong (CRITICAL).
  - [Edge cases handled? partial] VisualDiffer handles identical SVGs but the docstring has an unfinished note. Temp directory cleanup in playground is not specified.
  - [No broken flows? partial] Demo pipeline flow is complete. Playground upload/execute/ERC/DRC flow is complete. But the execute endpoint will crash due to type mismatch.

### Critical SLC Violations

#### SLC-1: erc_auto_fix signature mismatch -- runtime crash (49-01-PLAN.md Task 2)
- **Severity**: CRITICAL
- **Description**: `_auto_fix` calls `erc_auto_fix(schematic_path, max_iterations=3)` but the actual function requires `(ir: SchematicIR, file_path: Path, ...)` as first two arguments. This will raise `TypeError` at runtime and abort the demo pipeline at Stage 4.
- **Fix**: Parse the schematic to get an IR before calling erc_auto_fix. Update the `_auto_fix` method to: (1) parse the schematic into a SchematicIR using `SchematicIR.from_file(schematic_path)`, (2) call `erc_auto_fix(ir, schematic_path, max_iterations=3)`.

#### SLC-2: handle_operation return type mismatch -- runtime crash (51-01-PLAN.md Task 1)
- **Severity**: CRITICAL
- **Description**: The `/api/execute` endpoint calls `handle_operation(op_json, project_dir=project_dir)` and assigns the result to `result_str`, then calls `json.loads(result_str)`. But `handle_operation()` returns `Union[OperationResult, OperationError]` (Pydantic model objects), not a string. `json.loads()` requires a string argument. This will raise `TypeError` (or `AttributeError`) at runtime, causing every operation execution to fail.
- **Fix**: Replace `result_str = handle_operation(...)` / `json.loads(result_str)` with either: (a) `result = handle_operation(...)` then `result.model_dump()`, or (b) `result = handle_operation(...)` then `json.loads(format_result(result))` if the display text is needed. For the API, option (a) is correct -- return the structured result dict.

#### SLC-3: Playground temp directory never cleaned up (51-01-PLAN.md)
- **Severity**: HIGH
- **Description**: Upload files are stored with UUID names in a temp directory created via `tempfile.mkdtemp()`, but no cleanup mechanism is specified. `mkdtemp()` does NOT auto-delete -- only `TemporaryDirectory()` does. If a user runs `kicad-agent playground` for extended sessions, uploaded files accumulate indefinitely. If the server crashes, orphaned files persist.
- **Fix**: Use `tempfile.TemporaryDirectory()` with an `atexit` handler, or switch to `TemporaryDirectory()` as a context manager that auto-cleans on shutdown. Add a startup message noting the temp directory location.

**SLC Decision**: CONDITIONAL PASS -- fix the 3 critical/high items before execution proceeds. All other findings are fixable during execution.

---

## Security Review (Rick C-137)
**Status**: FAIL -- SVG XSS and session management issues must be addressed

### Vulnerabilities Found

#### SEC-1: SVG XSS via unsanitized kicad-cli output (50-01, 51-01)
- **Severity**: HIGH
- **Category**: xss
- **Description**: KiCad-generated SVGs are not sanitized before serving to browsers. SVG is an XML format that supports `<script>` tags, event handlers (`onclick`, `onerror`, `onload`), and `<foreignObject>` with embedded HTML/JS. Plan 51-01's playground frontend loads SVG via `fetch()` and injects it with `innerHTML` (line 965 of the plan: `document.getElementById('svg-preview').innerHTML = svgText`). This is the most dangerous XSS pattern -- inline SVG via `innerHTML` executes all embedded JavaScript. The `FileResponse` with `media_type="image/svg+xml"` at least allows browsers to apply same-origin policy, but `innerHTML` bypasses that protection entirely.
- **Location**: `src/kicad_agent/spatial/svg_utils.py` (to be created), `src/kicad_agent/playground/static/app.js` (to be created)
- **Exploit Scenario**: A malicious .kicad_sch file uploaded to the playground could contain component names or labels that, when rendered to SVG by kicad-cli, produce executable JavaScript. When the playground frontend fetches and injects the SVG via `innerHTML`, the script executes in the user's browser context with access to the WebSocket connection and any session data.
- **Fix Recommendation**: (1) Add `sanitize_svg(root: ET.Element) -> None` to `svg_utils.py` that strips all elements with tag containing `script`, removes all attributes starting with `on` from all elements, and removes `<foreignObject>` elements. (2) In the playground frontend, replace `innerHTML = svgText` with creating an `<img>` element: `img.src = URL.createObjectURL(blob)` -- img-tag SVG does not execute scripts. (3) Alternatively, use an `<iframe sandbox>` for SVG preview.
- **Confidence**: 0.95

#### SEC-2: WebSocket lacks origin validation (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: csrf
- **Description**: The WebSocket handler in `ws.py` calls `await websocket.accept()` without checking the `Origin` header. Any website can open a WebSocket connection to `ws://localhost:8000/ws` and execute operations. Combined with the `/api/execute` endpoint, this allows cross-origin operation execution from any tab the user has open.
- **Location**: `src/kicad_agent/playground/ws.py` (to be created)
- **Fix Recommendation**: Add origin validation in the WebSocket accept: check that `websocket.headers.get("origin", "")` is either empty or matches `localhost`/`127.0.0.1`. Reject connections from other origins with a 403.
- **Confidence**: 0.85

#### SEC-3: Playground session state is in-memory only with no cap (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: denial_of_service
- **Description**: `request.app.state.sessions` is a plain dict that grows unboundedly. Each upload adds an entry with file path and metadata. No maximum session count is specified. An attacker (or even a normal user in a long session) could upload thousands of files to exhaust memory.
- **Location**: `src/kicad_agent/playground/api.py` (to be created)
- **Fix Recommendation**: Cap `sessions` dict at a reasonable limit (e.g., 100 sessions). Evict oldest when limit is reached. Add `MAX_SESSIONS = 100` constant.
- **Confidence**: 0.80

#### SEC-4: Path traversal check uses fragile string matching (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: path_traversal
- **Description**: The filename validation checks `".." in filename` as a string match. This approach can be bypassed with URL-encoded sequences (`%2e%2e`), Unicode normalization tricks, or null bytes. Additionally, the check happens after `file.filename or ""` which means multipart header manipulation could pass unexpected values.
- **Location**: `src/kicad_agent/playground/api.py` `_validate_filename()` (to be created)
- **Fix Recommendation**: Use `pathlib.PurePosixPath(filename).name` to extract just the filename (stripping any path components), then validate the result. This is robust against all path traversal variants because `.name` returns only the final component.
- **Confidence**: 0.82

#### SEC-5: ALLOWED_EXTENSIONS inconsistency (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: security_inconsistency
- **Description**: The `ALLOWED_EXTENSIONS` set in the plan code includes `.kicad_sym` and `.kicad_mod` (symbol and footprint library files), but the must_haves truths say "File upload accepts .kicad_sch and .kicad_pcb only, rejects other extensions". The `/api/preview` endpoint only handles `.kicad_sch` files, so uploaded `.kicad_sym` and `.kicad_mod` files would be accepted but never previewable. This is a security inconsistency -- the whitelist is broader than the spec.
- **Location**: 51-01-PLAN.md Task 1, `ALLOWED_EXTENSIONS` constant vs must_haves truths
- **Fix Recommendation**: Align `ALLOWED_EXTENSIONS` with the must_haves spec: `{".kicad_sch", ".kicad_pcb"}`. If symbol/footprint preview is needed later, add it then.
- **Confidence**: 0.90

#### SEC-6: No rate limiting on upload endpoint (51-01-PLAN.md)
- **Severity**: LOW
- **Category**: denial_of_service
- **Description**: The `/api/upload` endpoint has a 10MB file size limit but no rate limit. An attacker can upload 10MB files as fast as the server accepts them, filling the temp directory and exhausting disk space.
- **Fix Recommendation**: Add a simple per-IP rate limiter (e.g., max 10 uploads per minute) or use FastAPI middleware.
- **Confidence**: 0.75 (below 0.8 threshold -- informational)

**Security Summary**:
- High Severity: 1 (SVG XSS)
- Medium Severity: 4 (WebSocket origin, session DoS, path traversal, extension inconsistency)
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
- **Description**: The plan's `_auto_fix` method calls `erc_auto_fix(schematic_path, max_iterations=3)`. Verified against actual source: the function signature is `erc_auto_fix(ir: SchematicIR, file_path: Path, max_iterations: int = 3, mode: str = "symptom", fix_classes: list[str] | None = None)`. Missing the required `ir` parameter. This is a guaranteed `TypeError` at runtime.
- **Location**: 49-01-PLAN.md, `_auto_fix` method implementation
- **Engineering Principle**: Verify function signatures against actual source before writing call sites. The plan includes interface blocks but the implementation code contradicts them.
- **Fix Recommendation**: Parse the schematic first: `ir = SchematicIR.from_file(schematic_path)` then `erc_auto_fix(ir, schematic_path, max_iterations=3)`.

#### CODE-2: handle_operation return type mismatch -- will crash at runtime (51-01-PLAN.md Task 1)
- **Severity**: CRITICAL
- **Category**: bug
- **Description**: The plan's `execute_operation` endpoint does `result_str = handle_operation(op_json, project_dir=project_dir)` then `json.loads(result_str)`. Verified against actual source: `handle_operation()` returns `Union[OperationResult, OperationError]` (Pydantic model objects), not a string. The existing `cli.py` uses `format_result(result)` to get display text. Calling `json.loads()` on a Pydantic model object will raise `TypeError`.
- **Location**: 51-01-PLAN.md Task 1, `execute_operation` endpoint
- **Engineering Principle**: Match return types to actual function signatures. The plan lists the handler interface but the implementation code ignores it.
- **Fix Recommendation**: Use `result = handle_operation(...)` then `result.model_dump()` for JSON serialization. Or use `format_result(result)` for text output.

#### CODE-3: VisualDiffResult docstring contains unfinished note (50-02-PLAN.md)
- **Severity**: MEDIUM
- **Category**: code_quality
- **Description**: The `VisualDiffResult` docstring says `removed_count: Number of elements in 'after' but not in 'before' (wait, reversed).` -- the "(wait, reversed)" is clearly an authoring artifact left in the plan. If this docstring is copied into the codebase during execution, it will confuse future readers and may suggest the field semantics are uncertain.
- **Location**: 50-02-PLAN.md, `VisualDiffResult` class docstring
- **Engineering Principle**: Clean specifications produce clean code. Authoring artifacts in plans propagate into code.
- **Fix Recommendation**: Remove "(wait, reversed)" and write the correct description: `removed_count: Number of elements in 'before' but not in 'after'.`

#### CODE-4: _parse_erc_count heuristic is fragile (49-01-PLAN.md Task 2)
- **Severity**: MEDIUM
- **Category**: robustness
- **Description**: The `_parse_erc_count` method counts non-empty lines that do not start with "ERC ", "Running", or "Info". This heuristic will miscount on different kicad-cli versions or locales. The existing `erc_parser.py` module already has `parse_erc()` that returns structured `ErcViolation` objects with proper parsing. The plan should use that instead of reimplementing a fragile parser.
- **Location**: 49-01-PLAN.md, `_parse_erc_count` method
- **Engineering Principle**: Reuse existing parsers instead of writing ad-hoc heuristics. `erc_parser.py` was built for exactly this purpose.
- **Fix Recommendation**: Replace `_run_erc` and `_parse_erc_count` with a call to `parse_erc(schematic_path)` from `erc_parser.py`. Return `len(violations)` for the count. This also gives structured `ErcViolation` data that can feed directly into Phase 50's SVG annotation.

#### CODE-5: DemoReport must_haves truths missing fields (49-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: consistency
- **Description**: The must_haves truths section lists DemoReport fields as `template_used, stages_completed, erc_before, erc_after, svg_paths, duration_seconds, success` but the actual implementation code includes `errors: list[str]` and `project_dir: str | None`. The truths section does not mention these fields, meaning the verification step would not check for them.
- **Location**: 49-01-PLAN.md, must_haves truths
- **Fix Recommendation**: Update must_haves truths to include `errors` and `project_dir` fields.

#### CODE-6: VisualDiffer signature collision risk (50-02-PLAN.md)
- **Severity**: MEDIUM
- **Category**: robustness
- **Description**: `_collect_signatures` uses `(tag, x, y)` as signature key. If two elements have the same tag and position (e.g., overlapping text labels), only the first is kept (`if sig not in signatures`). This means identical-position elements are silently deduplicated, producing incorrect diff counts.
- **Location**: 50-02-PLAN.md, `_collect_signatures` method
- **Engineering Principle**: Handle all edge cases in comparison logic.
- **Fix Recommendation**: Append a counter to duplicate signatures: `sig = f"{tag}:{x},{y}#{count}"` or use a list of tuples instead of a dict.

#### CODE-7: Phase 51 playground does not declare FastAPI dependency (51-01-PLAN.md)
- **Severity**: MEDIUM
- **Category**: completeness
- **Description**: The playground plan imports `from fastapi import ...`, `from fastapi.testclient import TestClient`, and `uvicorn` but does not specify adding these to the project's dependencies (pyproject.toml). These are not currently in the project's dependencies. The plan will fail at import time without them.
- **Location**: 51-01-PLAN.md, all tasks
- **Engineering Principle**: Declare all dependencies explicitly. Zero-surprise installs.
- **Fix Recommendation**: Add a task or step to add `fastapi` and `uvicorn` as optional dependencies in pyproject.toml: `[project.optional-dependencies]` with `playground = ["fastapi>=0.100", "uvicorn>=0.20", "python-multipart>=0.0.6"]`.

#### CODE-8: CLI routing dispatch needs explicit update for "demo" and "playground" (49-01, 51-01)
- **Severity**: HIGH
- **Category**: completeness
- **Description**: Both plans correctly specify adding to `_SUBCOMMANDS` set and creating `_handle_demo` / `_handle_playground` functions. However, the existing `main()` function uses an explicit `if/elif` chain (lines 577-599 of cli.py) to route subcommands. Neither plan shows adding `elif subcmd == "demo":` and `elif subcmd == "playground":` to `main()`. Plan 49-01 Task 3 says "Update the main dispatch in main() to route 'demo' to _handle_demo" but does not show the actual elif clause. Plan 51-01 Task 4 does not mention the dispatch update at all.
- **Location**: 49-01-PLAN.md Task 3, 51-01-PLAN.md Task 4
- **Engineering Principle**: Complete the integration path. Missing dispatch = broken subcommand.
- **Fix Recommendation**: Both plans must explicitly show adding `elif subcmd == "demo": _handle_demo(subcmd_argv)` and `elif subcmd == "playground": _handle_playground(subcmd_argv)` to the `main()` function dispatch chain.

**Code Summary**:
- Critical: 2 (erc_auto_fix signature, handle_operation return type)
- High: 1 (CLI dispatch routing)
- Medium: 5 (docstring, ERC parser reuse, DemoReport fields, signature collision, FastAPI dependency)
- Low: 0

**Code Decision**: REJECT -- two critical runtime crashes and missing CLI dispatch must be fixed.

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
- **Fix Recommendation**: Either (a) expand the viewBox height to accommodate the legend, or (b) position the legend inside the existing viewport at the bottom-right corner with a semi-transparent background overlay. Option (a) is more reliable across viewers.

#### DES-2: Playground frontend uses innerHTML for SVG -- XSS risk and design concern (51-01-PLAN.md)
- **Severity**: HIGH (security crossover)
- **Category**: security_design
- **Description**: The frontend loads SVG via `fetch('/api/preview/{sessionId}')` and injects it with `innerHTML = svgText`. This is both a security issue (XSS) and a design issue -- it couples the rendering to the DOM's raw HTML parser. Using an `<img>` tag or `<iframe sandbox>` would be cleaner, safer, and more portable.
- **Location**: 51-01-PLAN.md, `loadPreview` method in app.js
- **Fix Recommendation**: Replace `innerHTML = svgText` with `<img src="/api/preview/${sessionId}">` element creation. Img-tag SVG does not execute scripts and handles rendering natively.

#### DES-3: Playground static files should include favicon (51-01-PLAN.md)
- **Severity**: LOW
- **Category**: polish
- **Description**: The static file list includes `index.html`, `app.js`, `style.css` but no favicon. Browser console will show 404 for `/favicon.ico`. For a "quality 10" demo, this matters.
- **Fix Recommendation**: Add a simple SVG favicon to the static directory and reference it in `index.html`: `<link rel="icon" type="image/svg+xml" href="favicon.svg">`.

**Design Summary**:
- High: 1 (innerHTML SVG rendering)
- Medium: 1 (legend positioning)
- Low: 1 (favicon)

**Design Decision**: APPROVE with recommendations -- legend positioning and innerHTML replacement should happen during execution.

---

## Security Review -- Agent Boundaries (Sentinel Rick)
**Status**: PASS (with mandatory requirements)

### Blast Radius Assessment

The playground introduces a web server boundary that exposes kicad-agent operations to network requests. Key observations:

#### Boundary Analysis

| Boundary | Risk | Mitigation |
|----------|------|------------|
| File upload -> filesystem | Path traversal | UUID-based naming mitigates. Must add `PurePosixPath.name` extraction. |
| Upload -> kicad-cli execution | Command injection | kicad-cli called with explicit args (not shell=True). Safe. |
| WebSocket -> handle_operation | Unbounded execution | Operations inherit existing timeouts. Acceptable. |
| Sessions dict -> memory | Unbounded growth | Must cap at MAX_SESSIONS. |
| SVG output -> browser | XSS | Must sanitize SVG or use img-tag rendering. |
| handle_operation return -> API | Type confusion | Must fix return type handling. |

#### Positive Security Patterns

1. **Extension whitelist**: Plan includes `ALLOWED_EXTENSIONS` -- correctly restrictive (needs alignment with spec).
2. **UUID-based file storage**: Uploads stored as UUID names, not user-supplied filenames.
3. **kicad-cli timeout**: 120s timeout on all subprocess calls, matching existing pattern.
4. **Operation validation**: `/api/execute` calls `validate_operation()` before `handle_operation()`.
5. **Localhost-only**: Default host is 127.0.0.1. No CORS headers configured. Good.

**Agent Security Decision**: APPROVE with SVG sanitization, session cap, and origin validation requirements.

---

## KiCad Domain Review (KiCad Rick)
**Status**: PASS

### Domain-Specific Observations

#### KICAD-1: Template GenerationIntent components need real KiCad lib_ids (49-02-PLAN.md)
- **Severity**: LOW
- **Category**: domain_accuracy
- **Description**: The plan lists template component counts (e.g., "RC Low-Pass Filter -- 3 components, 2 nets") but does not specify the actual `library_id` values for each component. The `GenerationIntent` requires valid `library_id` strings (e.g., `Device:R`, `Device:C`, `Amplifier_Operational:LM358`). If these are wrong, `generate_design()` will fail at the symbol resolution stage.
- **Fix Recommendation**: Ensure each template's `ComponentSpec` list uses valid KiCad library identifiers from the official KiCad libraries (Device, Amplifier_Operational, etc.).

#### KICAD-2: SVG coordinate system for annotation (50-01-PLAN.md)
- **Severity**: LOW
- **Category**: domain_accuracy
- **Description**: KiCad SVGs use mm coordinates in the viewBox. The plan correctly identifies this and uses `svg_to_mm()` for conversion. KiCad's Y-axis direction (origin at top-left, Y increases downward) matches SVG's coordinate system, so no Y-flip is needed. The plan handles this correctly.
- **Recommendation**: No action needed -- plan is correct.

**KiCad Decision**: APPROVE -- templates need real lib_ids during execution, not a plan-level blocker.

---

## No React/Build Step Verification

**Status**: PASS

Plan 51-01 explicitly states:
- must_haves truths: "Static HTML/JS frontend with no build step -- vanilla JS, no React"
- Files: `static/index.html`, `static/app.js`, `static/style.css`
- No package.json, no webpack, no vite, no node_modules

The frontend is three static files served by FastAPI's `StaticFiles` mount. Confirmed no build step.

---

## TDD Coverage Assessment

**Status**: PASS (with note)

All 8 plans specify TDD workflow (RED-GREEN-REFACTOR) with test files:
- 49-01: `tests/test_demo.py` -- TestDemoReportSchema, TestDemoPipeline, TestDemoCLI
- 49-02: `tests/test_demo_templates.py` -- TestTemplateVariety, TestTemplateDocs
- 50-01: `tests/test_svg_annotation.py` -- TestSvgUtils, TestAnnotationStyle, TestSvgAnnotator
- 50-02: `tests/test_visual_diff.py` -- TestVisualDiffResult, TestVisualDiffer, TestReportGenerator
- 51-01: `tests/test_playground.py` -- TestPlaygroundAPI, TestPlaygroundWebSocket, TestPlaygroundCLI, TestStaticFiles

All plans mention mocking kicad-cli for CI environments where it is unavailable. This is correct -- the tests must not depend on kicad-cli being installed.

**Note**: Plan 51-01 uses `fastapi.testclient.TestClient` for sync tests in Task 1 but imports `httpx.AsyncClient` for async tests. The plan should consistently use one approach. `TestClient` is simpler and does not require `httpx` as a dependency. Recommend standardizing on `TestClient` throughout.

---

## Dependency Chain Verification

| Dependency | Declared | Status | Risk |
|------------|----------|--------|------|
| 49-01 depends on 38-01 | YES | Phase 38 has SUMMARY (complete) | LOW -- routing engine exists |
| 49-02 depends on 49-01 | YES | Correct -- templates need pipeline | NONE |
| 50-01 depends on 49-01 | YES | Correct -- annotation needs SVG output | NONE |
| 50-02 depends on 50-01 | YES | Correct -- diff needs annotation engine | NONE |
| 51-01 depends on 50-01 | YES | Correct -- playground needs SVG preview | NONE |
| 49-01 depends on Phase 10 (generate_design) | YES | Shipped -- exists in codebase | NONE |
| 49-01 depends on Phase 3 (ERC/DRC) | YES | Shipped -- exists in codebase | NONE |
| 49-01 depends on Phase 35 (erc_auto_fix) | YES | Shipped -- exists in codebase | NONE |
| 51-01 depends on Phase 30 (MCP server) | YES | Listed in 51-PLAN.md | LOW -- see note below |

**Note**: Phase 51-PLAN.md lists Phase 30 (MCP Operations Server) as a dependency, but Phase 30 is not yet started. However, plan 51-01 only uses `handle_operation()` and `validate_operation()` from the handler module (which exists) and `get_operation_schema()` from the ops/schema module (which exists). The MCP dependency is listed for "operation schema exposure" but is not actually required. This dependency can be relaxed or marked as soft.

---

## Findings Summary Table

| ID | Severity | Plan | Description | Must Fix Before Execution |
|----|----------|------|-------------|---------------------------|
| SLC-1 | CRITICAL | 49-01 | erc_auto_fix signature mismatch -- missing `ir` parameter | YES |
| SLC-2 | CRITICAL | 51-01 | handle_operation return type mismatch -- `json.loads()` on Pydantic model | YES |
| CODE-1 | CRITICAL | 49-01 | erc_auto_fix signature mismatch (same as SLC-1) | YES |
| CODE-2 | CRITICAL | 51-01 | handle_operation return type (same as SLC-2) | YES |
| SEC-1 | HIGH | 50-01, 51-01 | SVG XSS -- unsanitized SVG served via innerHTML | YES |
| CODE-8 | HIGH | 49-01, 51-01 | CLI main() dispatch not updated for new subcommands | YES |
| DES-2 | HIGH | 51-01 | innerHTML for SVG rendering (security crossover with SEC-1) | YES |
| SLC-3 | HIGH | 51-01 | Playground temp directory never cleaned up | YES |
| SEC-2 | MEDIUM | 51-01 | WebSocket lacks origin validation | YES |
| SEC-3 | MEDIUM | 51-01 | Session state grows unboundedly | YES |
| SEC-4 | MEDIUM | 51-01 | Path traversal check uses string matching | YES |
| SEC-5 | MEDIUM | 51-01 | ALLOWED_EXTENSIONS includes .kicad_sym/.kicad_mod but spec says sch/pcb only | YES |
| CODE-3 | MEDIUM | 50-02 | VisualDiffResult docstring has "(wait, reversed)" artifact | NO (fix during execution) |
| CODE-4 | MEDIUM | 49-01 | _parse_erc_count should reuse erc_parser.parse_erc() | YES (better approach) |
| CODE-5 | MEDIUM | 49-01 | DemoReport must_haves missing `errors` and `project_dir` fields | NO (fix during execution) |
| CODE-6 | MEDIUM | 50-02 | VisualDiffer signature collision for overlapping elements | NO (fix during execution) |
| CODE-7 | MEDIUM | 51-01 | FastAPI/uvicorn not declared as dependencies | YES |
| DES-1 | MEDIUM | 50-01 | SVG legend positioned outside viewBox | NO (fix during execution) |
| SEC-6 | LOW | 51-01 | No rate limiting on upload endpoint | NO |
| DES-3 | LOW | 51-01 | Missing favicon for playground | NO |
| KICAD-1 | LOW | 49-02 | Templates need real KiCad library_id values | NO |

---

## Council Consensus

**Wave Alpha (Core):**
- Rick Sanchez (Code): REJECT -- two critical runtime crashes (erc_auto_fix, handle_operation), missing CLI dispatch
- Rick C-137 (Security): REJECT -- SVG XSS at 0.95 confidence, session management gaps
- Slick Rick (SLC): CONDITIONAL PASS -- fix 3 critical/high items before execution

**Wave Beta (Wisdom):**
- Rick Prime (Design): APPROVE with recommendations -- legend positioning and innerHTML replacement during execution
- Rickfucius (Historian): FIX VIOLATIONS -- signature mismatch, return type mismatch, and XSS are all real runtime issues

**Wave Gamma (Domain):**
- KiCad Rick: APPROVE -- templates need real lib_ids but not a plan blocker
- Sentinel Rick: APPROVE with mandatory requirements (SVG sanitization, session cap, origin validation)

**Wave Delta (Pipeline):**
- GSD Plan Checker: Plans follow GSD format correctly. All have must_haves, tasks with TDD, threat models, verification, and success_criteria. Dependency chains are documented. Two interface accuracy issues found (erc_auto_fix signature, handle_operation return type).

**Wave Epsilon (Fresh Eyes):**
- Spectral Rick: Signal flow visualization through annotated schematics is a novel application of frequency-domain thinking to spatial reasoning. The numbered circle + legend pattern maps well to spectral peak annotation. Design is sound.
- Go Bubble Tea Rick: CLI pattern follows existing argparse conventions correctly. The `demo` subcommand with `--template`, `--list`, `--output-dir` is clean and follows the Elm Architecture principle of explicit state transitions. Suggestion: add `--json` flag to `demo` for explicit machine-readable output.

---

## Final Council Decision

**Evil Morty's Ruling**: CONDITIONAL APPROVE

The plans are well-structured, follow established patterns, and cover the full user journey. However, two critical interface mismatches and one high-severity XSS vulnerability must be fixed in the plans before execution begins. These are not theoretical issues -- they will cause runtime crashes or security exploits.

### Required Changes Before Execution (10 items)

1. **FIX 49-01 Task 2**: erc_auto_fix call signature -- add `SchematicIR` parameter. Parse schematic first with `SchematicIR.from_file(schematic_path)`, then pass IR to `erc_auto_fix(ir, schematic_path, max_iterations=3)`.

2. **FIX 49-01 Task 2**: Replace `_parse_erc_count` heuristic with `parse_erc()` from `erc_parser.py`. This gives structured `ErcViolation` data for downstream SVG annotation (Phase 50).

3. **FIX 49-01 Task 3**: Explicitly show adding `elif subcmd == "demo": _handle_demo(subcmd_argv)` to `main()` dispatch in `cli.py`.

4. **FIX 49-01**: Update must_haves truths to include `errors: list[str]` and `project_dir: str | None` DemoReport fields.

5. **FIX 50-01**: Add `sanitize_svg(root: ET.Element) -> None` to `svg_utils.py` that strips `<script>` elements, `on*` event attributes, and `<foreignObject>` elements. Call it in `write_svg()`.

6. **FIX 50-02**: Remove "(wait, reversed)" from VisualDiffResult docstring. Write correct description: "Number of elements in 'before' but not in 'after'."

7. **FIX 51-01 Task 1**: Fix `execute_operation` endpoint to handle `handle_operation` return type correctly: `result = handle_operation(...)` then `result.model_dump()` for JSON serialization, not `json.loads(result_str)`.

8. **FIX 51-01 Task 1**: Align `ALLOWED_EXTENSIONS` with must_haves spec: `{".kicad_sch", ".kicad_pcb"}` only.

9. **FIX 51-01 Task 4**: Explicitly show adding `elif subcmd == "playground": _handle_playground(subcmd_argv)` to `main()` dispatch. Declare `fastapi`, `uvicorn`, and `python-multipart` as optional dependencies in pyproject.toml.

10. **FIX 51-01**: Add temp directory cleanup (use `TemporaryDirectory()` or `atexit` handler). Add WebSocket origin validation. Cap sessions dict at `MAX_SESSIONS = 100`. Use `PurePosixPath.name` for filename extraction. Replace `innerHTML = svgText` with `<img src>` for SVG preview.

### Recommended Changes During Execution (6 items)

1. Position SVG legend within viewBox (not below it) -- expand viewBox height.
2. Handle VisualDiffer signature collision for overlapping elements -- append counter.
3. Add favicon.svg to playground static files.
4. Relax Phase 30 dependency for 51-01 (only handler/schema needed, not MCP server).
5. Add `--json` flag to `demo` subcommand (default is already JSON, but explicit is better).
6. Ensure template `library_id` values use valid KiCad library references from official libraries.

---

**Council Motto**: "84 specialists. 6 waves. Zero compromises. The demo must work the first time -- one command, zero surprises, no runtime crashes."

**Review Completed**: 2026-05-31
**Review Scope**: Phases 49-51 (8 plan files: 49-PLAN, 49-01-PLAN, 49-02-PLAN, 50-PLAN, 50-01-PLAN, 50-02-PLAN, 51-PLAN, 51-01-PLAN)
**Reference Files Verified**: cli.py (lines 38-604), handler.py, pipeline.py, renderer.py, erc_parser.py, erc_auto_fix.py, intent.py, schema.py
**Next Step**: Revise plans per Required Changes (10 items), then proceed to execution.
