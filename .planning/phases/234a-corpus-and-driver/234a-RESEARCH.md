# Phase 234: 1000-Schematic Swift ERC Batch Test - Research

**Researched:** 2026-07-14
**Domain:** Swift vs Python ERC parity testing at scale
**Confidence:** HIGH

## Summary

Phase 234 validates the Swift `NativeERC.run()` engine against Python `native_erc` on 1000 real KiCad schematics, producing a parity report with FP/FN analysis. Phase 218 proved the Swift engine with 50/50 schematics at 100% pass. This phase scales to 1000 and produces a formal parity report.

Key discovery: The 28K schematic corpus is not pre-staged locally but can be discovered via GitHub curation using `CorpusCurator`. The 50 tested schematics from Phase 218 are in `tests/fixtures/` and `kicad_agent-0.1.0/tests/fixtures/`. Swift and Python engines have matching signatures but different return types (`NativeErcResult`).

## User Constraints (from CONTEXT.md)

### Locked Decisions

- 1000 schematics sampled from 28K KiCad corpus
- Stratified sample preferred (match Phase 218's pass/fail distribution)
- Python `native_erc` is the reference (Swift matches Python, not perfection)
- Parity report: per-check breakdown, per-schematic record, Top-N disagreement patterns
- Report format: Markdown summary + raw JSON, written to PARITY-REPORT.md
- Fix only root causes affecting >=5 schematics
- Cap fix loop at 2 iterations

### Claude's Discretion

- Exact sampling algorithm (stratified, random, or first-1000-after-seed)
- Report layout and tooling (Swift test harness vs Python driver vs both)
- How to organize the 1000 schematics in the local file system
- Tolerance for known edge cases

### Deferred Ideas (OUT OF SCOPE)

- DRC parity at 1000
- Multi-engine comparison (Apple Foundation Models, MLX)
- Netlist-level parity
- New ERC check types

## Technical Approach

### Architecture Overview

```
                    ┌─────────────────────────────────────────────────┐
                    │         1000-Schematic Parity Test              │
                    ├─────────────────────────────────────────────────┤
                    │  Input: 1000 .kicad_sch files (stratified sample) │
                    └─────────────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
         ┌──────────▼──────────┐  ┌───────────▼───────────┐
         │  Swift Engine       │  │  Python Reference       │
         │  NativeERC.run()    │  │  run_native_erc()       │
         │  (macOS app)        │  │  (Python daemon/stdin)  │
         └─────────────────────┘  └─────────────────────────┘
                    │                         │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    Comparison Layer     │
                    │  - Parse results        │
                    │  - Compare violation sets │
                    │  - Generate diff report │
                    └─────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    Parity Report        │
                    │  - PARITY-REPORT.md     │
                    │  - parity-results.json  │
                    └─────────────────────────┘
```

### Engine Signatures

**Swift (`macos-app/Sources/KiCadAgent/Validation/NativeERC.swift`):**
```swift
static func run(schematicURL: URL) -> NativeErcResult
```

Return type:
```swift
struct NativeErcResult: Sendable {
    let violations: [ERCViolation]
    let checksRun: [String]         // "schematic_parse", "pin_resolution", "topology_resolution"
    let checksSkipped: [String]
    var errorCount: Int { ... }
    var warningCount: Int { ... }
    var passed: Bool { errorCount == 0 }
}

struct ERCViolation: Sendable {
    let severity: ERCSeverity       // .error, .warning, .info
    let checkId: String             // "ERC_PIN_CONFLICT", "ERC_POWER_NOT_DRIVEN", etc.
    let description: String
    var ref: String = ""
    var pin: String = ""
    var net: String = ""
    var position: (Double, Double)?
}
```

**Python (`src/kicad_agent/validation/native_erc.py`):**
```python
def run_native_erc(schematic_path: Path) -> NativeErcResult
```

Return type:
```python
@dataclass(frozen=True)
class NativeErcResult:
    violations: tuple[ERCViolation, ...]
    checks_run: tuple[str, ...]
    checks_skipped: tuple[str, ...]

@dataclass(frozen=True)
class ERCViolation:
    severity: ERCSeverity          # ERROR, WARNING, INFO, EXCLUSION
    check_id: str                  # "ERC_PIN_CONFLICT", "ERC_POWER_NOT_DRIVEN", etc.
    description: str
    ref: str = ""
    pin: str = ""
    net: str = ""
    position: tuple[float, float] | None = None
```

### ERC Check Types (Both Engines)

1. **ERC_PIN_CONFLICT** - Pin-type conflict detection (11x11 compatibility matrix)
2. **ERC_POWER_NOT_DRIVEN** - Power net validation
3. **ERC_NC_CONNECTED** / **ERC_UNCONNECTED_PIN** - No-connect validation
4. **ERC_WIRE_DANGLING** - Dangling wire detection

### Corpus Location

**Local fixtures (already available):**
- `/Users/bretbouchard/apps/kicad-agent/tests/fixtures/` - Arduino_Mega, RaspberryPi-uHAT, etc.
- `/Users/bretbouchard/apps/kicad-agent/kicad_agent-0.1.0/tests/fixtures/` - legibility set (S1-6)

**Corpus acquisition strategy:**
The 28K corpus must be downloaded via GitHub curation. Use `CorpusCurator` from `src/kicad_agent/training/corpus_curator.py`:
```bash
python3 -c "
from kicad_agent.training.corpus_curator import CorpusCurator
from kicad_agent.training.project_index import ProjectIndex

curator = CorpusCurator()
projects = curator.curate_batch()  # Downloads ~50+ projects
# Each project has local_path in tempdir after download
"
```

**Practical approach for Phase 234:**
1. Use existing fixture schematics (already downloaded) as seed corpus
2. For larger corpus, download additional projects via CorpusCurator
3. Organize in `.planning/phases/234/corpus/` directory

### Test Harness Design Options

**Option A: Swift XCTest Driver** (Recommended for integration)
- Create `macos-app/Tests/KiCadAgentTests/BatchERCParityTests.swift`
- Use `XCTStaticText` for results, run via `swift test --no-parallel`
- Pros: Native integration, leverages existing Swift test infrastructure
- Cons: Requires macOS app build, harder to compare with Python results

**Option B: Python Comparison Driver** (Recommended for parity analysis)
- Create `scripts/batch_erc_parity.py`
- Invoke both engines via subprocess, compare JSON outputs
- Pros: Direct JSON comparison, easier to generate diff reports
- Cons: Separate from Swift test suite

**Recommended hybrid approach:**
- Python driver for orchestration and comparison (easier to work with JSON)
- Swift tests for validation that NativeERC.run() works correctly

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Swift ERC execution | Browser/Client (macOS app) | — | NativeERC.swift is Swift-only, no external dependencies |
| Python ERC execution | API/Daemon tier | Database | native_erc.py uses SchematicGraph parser |
| Corpus management | API/Daemon tier | Database | CorpusCurator downloads and indexes projects |
| Comparison/parity | API/Daemon tier | Browser | Python comparison engine, orchestrates both |
| Report generation | API/Daemon tier | Database | JSON diff + Markdown rendering |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.11.11 | Runtime | Required by daemon, test framework |
| Swift | 6.0 | macOS app | Native Apple framework |
| XCTest | 9.x | Swift testing | Apple's native test framework |
| pytest | 7.x | Python testing | Existing project test framework |
| KiCad | 7.x+ | File format | Ground truth for verification |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| KiCad-cli | -- | Ground truth ERC | Small validation subset (50 schematics) |
| SchematicGraph | -- | Parse .kicad_sch | Swift Symbol/TopologyBuilder uses this |
| ChromaDB | 1.5.9 | Vector storage | Not needed for this phase |

### Installation:
```bash
# Python
pip install pytest pydantic

# Swift (Xcode 16+)
xcodebuild -scheme KiCadAgentTests -destination 'platform=macOS'

# KiCad CLI (for small validation subset)
brew install kicad --with-cli
```

## Architecture Patterns

### Swift Engine Pattern
The Swift `NativeERC.run()` is a synchronous function that:
1. Parses schematic via `SchematicParser.parse()`
2. Resolves pins via `resolvePins()`
3. Builds topology via `TopologyBuilder.resolvePinNets()`
4. Runs 4 checks sequentially, returns aggregated violations

### Python Engine Pattern
The Python `run_native_erc()` is a function that:
1. Creates `SchematicGraph.from_file()`
2. Uses `TopologyBuilder._resolve_pin_nets()`
3. Runs checks with separate functions, returns dataclass

### Comparison Pattern
Both engines produce similar violation structures. The comparison:
1. Normalizes severity levels ("error"/"warning")
2. Matches violations by check_id, net, ref, description
3. Categorizes as FP (Swift finds, Python misses) or FN (Python finds, Swift misses)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schematic parsing | Custom parser | SchematicGraph/SchematicParser | Battle-tested, handles KiCad quirks |
| Topology resolution | Custom algorithm | TopologyBuilder | Phase 221 solved this complexity |
| Validation harness | Custom framework | XCTest + Python pytest | Project standard, less debugging |
| Report generation | Custom markdown | Swift JSONEncoder + Python dict | Simpler, less error-prone |

## Common Pitfalls

### Pitfall 1: Schematic file location confusion
**What goes wrong:** 28K corpus exists but files are in GitHub repos, not local filesystem
**Why it happens:** CorpusCurator downloads to temp directories; need to stage locally
**How to avoid:** Use existing fixtures from `tests/fixtures/`, extend with additional downloads

### Pitfall 2: Severity level mismatch
**What goes wrong:** Swift uses `.error/.warning` (enum), Python uses "error"|"warning" (string)
**Why it happens:** Different type systems need normalization
**How to avoid:** Standardize on lowercase strings in comparison layer

### Pitfall 3: FP/FN classification drift
**What goes wrong:** Violations with different descriptions counted as different
**Why it happens:** No normalize function for violation comparison
**How to avoid:** Compare by (check_id, net, ref) with fuzzy description matching

### Pitfall 4: Empty schematic edge case
**What goes wrong:** Schematics with no components cause parse errors
**Why it happens:** NativeERC may handle differently than Python
**How to avoid:** Add tolerance setting: `tolerance: 0.05` (5% variance allowed)

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — corpus in GitHub | Download/stage 1000 schematics |
| Live service config | None — local batch test | None |
| OS-registered state | None | None |
| Secrets/env vars | None | None |
| Build artifacts | None | None |

## Existing Test Patterns

### Swift Tests (`macos-app/Tests/KiCadAgentTests/`)
```swift
// Pattern: XCTest with ModelContainer cleanup
@MainActor
func testBasicFunctionality() async throws {
    let container = ModelContainer.preview
    // test logic
    try container.deleteAll()  // cleanup
}
```

### Python Tests (`tests/`)
```python
# Pattern: pytest with fixtures
class TestSomething:
    def test_behavior(self, fixture_path: Path):
        result = my_function(fixture_path)
        assert result.passed
```

### Existing ERC Tests
- Phase 218: 50/50 schematic batch test (SUCCESS)
- Files: `macos-app/Tests/KiCadAgentTests/Governance/VerificationLoopTests.swift`

## File Inventory

### Files to Create
| Path | Purpose |
|------|---------|
| `.planning/phases/234/scripts/batch_erc_parity.py` | Python driver for parity testing |
| `.planning/phases/234/corpus/` | Directory for 1000 sampled schematics |
| `.planning/phases/234/PARITY-REPORT.md` | Markdown summary report (generated) |
| `.planning/phases/234/parity-results.json` | Raw JSON results (generated) |
| `macos-app/Tests/KiCadAgentTests/BatchERCParityTests.swift` | Swift tests (optional validation) |

### Files to Modify
| Path | Purpose |
|------|---------|
| `PARITY-REPORT.md` | Initial report template (generated by harness) |

### Canonical References
- `/Users/bretbouchard/apps/kicad-agent/macos-app/Sources/KiCadAgent/Validation/NativeERC.swift`
- `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/validation/native_erc.py`
- `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/validation/native_drc_runner.py`
- `/Users/bretbouchard/apps/kicad-agent/.planning/phases/218-native-erc-drc-engine/218-01-SUMMARY.md`
- `/Users/bretbouchard/apps/kicad-agent/macos-app/daemon/handlers.py` (kicad_native_check handler)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.x (Python) + XCTest (Swift) |
| Config file | `/Users/bretbouchard/apps/kicad-agent/pytest.ini` (Python) |
| Quick run command | `pytest scripts/test_batch_erc_parity.py -x` |
| Full suite command | `pytest tests/ -k "erc" --tb=short` |
| Swift test command | `cd macos-app && swift test --no-parallel` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-01 | Swift engine runs on 1000 schematics | integration | `python3 scripts/batch_erc_parity.py --sample 1000` | ❌ Wave 0 |
| REQ-02 | Python reference runs on 1000 schematics | integration | `python3 scripts/batch_erc_parity.py --sample 1000 --engine python` | ❌ Wave 0 |
| REQ-03 | Parity report generated | unit | `python3 scripts/batch_erc_parity.py --report` | ❌ Wave 0 |
| REQ-04 | FP count <= 5% | unit | `pytest scripts/test_parity_thresholds.py` | ❌ Wave 0 |
| REQ-05 | FN count <= 5% | unit | `pytest scripts/test_parity_thresholds.py` | ❌ Wave 0 |
| REQ-06 | FP/FN patterns documented (top-10) | unit | Parse PARITY-REPORT.md | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest scripts/test_*.py -x`
- **Per wave merge:** `pytest tests/ -k "erc" --tb=short`
- **Phase gate:** All tests green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `{scripts/batch_erc_parity.py}` — core parity driver
- [ ] `{scripts/test_parity_thresholds.py}` — FP/FN threshold validation
- [ ] `{tests/conftest.py}` — shared pytest fixtures for corpus paths

## Risks & Landmines

### Risk 1: Corpus Size 28K vs Available Fixtures
**Severity:** HIGH
**Mitigation:** The 28K corpus is described in CONTEXT.md as "referenced by Phase 218" but actual files are in fixtures. Need to either:
1. Download additional projects via CorpusCurator
2. Use the ~50 fixtures already present + synthetic generation
**Validation:** Verify actual file count in `tests/fixtures/` and `output/legibility/`

### Risk 2: Corotic Mismatch in Edge Cases
**Severity:** MEDIUM
**Examples:** Empty schematics, no power flags, rotated components
**Mitigation:** Add tolerance configuration, document edge cases in report
**Validation:** Sample 50 schematics with known edge cases

### Risk 3: Performance at 1000x Scale
**Severity:** MEDIUM
**Estimate:** NativeERC runs in ~1-5s per schematic (Phase 218 used 50 in reasonable time)
**Mitigation:** Use parallel execution (`concurrent.futures.ProcessPoolExecutor`)
**Validation:** Benchmark on 100 schematics, extrapolate to 1000

### Risk 4: Floating-Point Position Rounding
**Severity:** LOW
**Issue:** 0.1mm difference in position may classify as different violation
**Mitigation:** Round positions to 2 decimal places in comparison
**Validation:** Test with known position variants

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual 50-schematic tests | Batch 1000-schematic with automated reports | Phase 234 | Statistically meaningful validation |
| kicad-cli ground truth | Swift matches Python reference | Phase 218 | App Store sandbox compatible |

## Sources

### Primary (HIGH confidence)
- `/Users/bretbouchard/apps/kicad-agent/macos-app/Sources/KiCadAgent/Validation/NativeERC.swift` — Swift ERC engine
- `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/validation/native_erc.py` — Python ERC engine
- `/Users/bretbouchard/apps/kicad-agent/.planning/phases/234-1000-schematic-swift-erc-batch-test/234-CONTEXT.md` — Phase requirements

### Secondary (MEDIUM confidence)
- Phase 218 SUMMARY.md — 50-board test methodology
- handlers.py — kicad_native_check daemon handler
- corpus_curator.py — Corpus download mechanism

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Uses existing project tools (Swift, Python, pytest)
- Architecture: HIGH — Clear component responsibilities, matching signatures
- Pitfalls: MEDIUM — Some corpus location uncertainty, needs user clarification

**Research date:** 2026-07-14
**Valid until:** 2026-08-14 (30 days)

## Open Questions

1. **Corpus location for 28K schematics**
   - What we know: CONTEXT.md references "28K KiCad corpus"
   - What's unclear: Actual local path, download mechanism
   - Recommendation: Verify corpus staging approach; may need to download via CorpusCurator

2. **Sampling algorithm for 1000 schematics**
   - What we know: Stratified preferred, fixed RNG seed for reproducibility
   - What's unclear: Exact stratification criteria (component count, category, pass/fail)
   - Recommendation: Use existing fixtures as base, supplement with downloads; seed=42

3. **Parallel execution strategy**
   - What we know: Each schematic is independent, can run in parallel
   - What's unclear: Optimal worker count on macOS
   - Recommendation: Use ProcessPoolExecutor with cpu_count() workers; validate on 100 first