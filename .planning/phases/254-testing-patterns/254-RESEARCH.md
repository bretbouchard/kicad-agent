# Phase 254: Testing Patterns - Research

**Researched:** 2026-07-29
**Domain:** Python testing patterns, frameworks, and quality standards for kiCad agent
**Confidence:** HIGH

## Summary

The kiCad agent project, codenamed "Volta", employs a robust testing framework with strong emphasis on quality, coverage, and integration testing patterns. The project uses pytest as its primary testing framework with extensive configuration for coverage requirements, strict markers, and comprehensive test suites. Testing covers all major components including the Abstract AST models, MCP tools, CLI interfaces, DFM functionality, and validation gates.

The testing approach focuses on 80% coverage enforcement with continuous integration through pytest-cov, unit tests for individual components and modules, and integration tests for end-to-end functionality. The project uses fixtures extensively for testing KiCad files and implements thorough input validation for all public APIs. The team maintains high-quality standards through strict testing requirements and detailed patterns for ensuring correctness.

**Primary recommendation:** The project should maintain current testing patterns with focus on expanding coverage for integration tests that cover the complex interaction between the various components, particularly around the MCP protocols.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Unit testing | API / Backend | — | All unit tests are written in this tier |
| Integration testing | API / Backend | Frontend Server (SSR) | End-to-end integration tests that interact with KiCad components typically in the API tier |
| CLI interface testing | API / Backend | — | Command-line interface behavior is tested in the API/Backend tier |
| MCP tool testing | API / Backend | Frontend Server (SSR) | MCP protocol handling is primarily in the backend components |
| Test framework setup | API / Backend | — | Configuration and fixture management resides here |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=8.0 | Test runner | Industry standard for Python tests with rich plugin ecosystem |
| pytest-cov | >=4.0 | Coverage reporting | Enforces the 80% coverage policy for quality gates |
| pytest-asyncio | — | Async test support | Needed for async Python components in the system |
| mypy | >=1.7 | Type checking | Ensures static typing adherence |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock | — | Mocking utilities | Used for dependency isolation in tests |
| conftest.py | — | Shared fixtures | Provide reusable fixtures for test scenarios |
| tox | — | Test environment automation | Used for running tests across different Python versions |
| coverage.py | — | Code coverage analysis | Direct integration with pytest-cov for metrics reporting |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| unittest | pytest | pytest offers better fixtures, parametrized tests, and richer assertion syntax |
| nose2 | pytest | pytest is more actively maintained and has better plugin ecosystem |
| pytest-mock | unittest.mock | pytest-mock provides cleaner syntax and better integration |

**Installation:**
```bash
pip install pytest pytest-cov mypy pytest-asyncio
```

**Version verification:**
```bash
pip list | grep -E "(pytest|coverage|mypy)"
```

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────┐          ┌──────────────────┐
│   Test Runner   │─────────▶│    Testing       │
│     (pytest)    │          │    Framework     │
└─────────────────┘          │                  │
                             │  Unit Tests      │
                              │  Integration     │
                              │  CLI Test Cases  │
                              │  MVP Test Cases  │
                              └──────────────────┘
                                         │
                                         ▼
                              ┌──────────────────┐
                              │     Source       │
                              │   Codebase       │
                              └─────────┬────────┘
                                        │
                   ┌────────────────────┼─────────────────────┐
                   │                    │                     │
           ┌─────────────┐     ┌──────────────┐    ┌─────────────┐
           │   Unit      │     │   Integration│    │   CLI       │
           │  Testing    │     │   Testing    │    │  Testing    │
           └─────────────┘     └──────────────┘    └─────────────┘
                   │                    │                     │
       ┌───────────┴───┐       ┌──────────┴────┐   ┌──────────┴────┐
       │   Abstract    │       │   MCP Tools   │   │  Validation   │
       │   AST Tests   │       │     Tests     │   │   Gate Tests  │
       │               │       │               │   │               │
       └───────────────┘       └───────────────┘   └───────────────┘
```

### Recommended Project Structure

```
src/
├── volta/              # Main source code
│   ├── abstract_ast/    # Abstract AST modeling and validation
│   ├── mcp/             # MCP protocols and tools
│   ├── cli/             # Command line interface
│   └── ops/             # Operations and logic processing
tests/
├── test_*.py           # Individual test files matching source modules
├── test_roundtrip/     # Round-trip stability tests
├── conftest.py         # Shared test fixtures
└── fixtures/           # KiCad test files for integration tests
```

### Pattern 1: Comprehensive Testing of API Entrypoints
**What:** All public functions and classes are thoroughly tested with both positive and negative test cases for inputs, outputs, and edge conditions.

**When to use:** When implementing new functionality that will be directly exposed to users or other modules.

**Example:**
```python
class TestSearchComponents:
    def test_basic_search(self) -> None:
        comp = _make_component()
        client = _mock_client(search_result=([comp], 1))
        result = search_components(client, "STM32")
        assert result["total"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["lcsc"] == "C83700"
        client.search_jlcpcb.assert_called_once_with(
            keyword="STM32", page=1, page_size=10, part_type=None,
        )
```

### Anti-Patterns to Avoid
- **Over-mocking**: Avoid mocking too many dependencies when simpler integration tests would suffice; tests should closely reflect real-world usage patterns
- **Missing validation checks**: Never skip validation of input parameters, always test boundary conditions and invalid inputs
- **Incomplete coverage**: Aim for 80%+ coverage; avoid relying on code that isn't tested adequately

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Test discovery and execution | Custom test runner | pytest | pytest handles discovery, parallelization, and reporting |
| Coverage measurement | Manual coverage script | pytest-cov | Provides automated integration, HTML reports, branch coverage analysis |
| Input validation | Manual parameter checks | Pydantic models | Pydantic provides validated types and better error messages |
| Test fixtures | Manual setup/teardown | pytest fixtures | Offers cleaner, reusable test environments |

**Key insight:** The project leverages existing mature Python testing infrastructure rather than creating homegrown solutions for common challenges like test discovery, coverage measurement, and input validation.

## Common Pitfalls

### Pitfall 1: Inadequate Fixtures for KiCad Files
**What goes wrong:** Tests that depend on real KiCad files fail when those files are not properly included or maintained.
**Why it happens:** Test fixtures are crucial for integration testing but require proper maintenance and inclusion in the repository.
**How to avoid:** Always maintain comprehensive test fixtures of real KiCad files and ensure they're part of the repository for reproducibility.
**Warning signs:** Test failures that reference missing fixture files or inability to reproduce test conditions with specific file content.

### Pitfall 2: Neglecting Input Validation in Public APIs
**What goes wrong:** Public functions in the MCP protocol lack comprehensive argument checks leading to unexpected behavior.
**Why it happens:** Testing edge cases and malformed inputs is often overlooked due to time constraints.
**How to avoid:** Apply rigorous input validation testing for all public surface APIs using comprehensive test cases that cover invalid and boundary conditions.
**Warning signs:** Tests showing behavior that varies widely depending on user input with inconsistent error handling.

### Pitfall 3: Lack of Integration Test Coverage 
**What goes wrong:** Units pass tests individually, but fail when combined in realistic usage scenarios.
**Why it happens:** The focus on isolated unit testing may miss interactions and state transitions that occur during real usage.
**How to avoid:** Regularly expand integration test suites that simulate complete user workflows.
**Warning signs:** Code that passes isolated tests but exhibits intermittent failures in production or when integrated with other components.

## Code Examples

Verified patterns from official sources:

### Input Validation Testing
```python
class TestInputValidation:
    def test_empty_keyword(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="empty"):
            search_components(client, "")

    def test_invalid_lcsc_id_format(self) -> None:
        client = _mock_client()
        with pytest.raises(ValidationError, match="invalid LCSC"):
            get_component_details(client, "ABC123")
```

### Mock-Based Integration Test
```python
class TestSearchComponents:
    def test_basic_search(self) -> None:
        comp = _make_component()
        client = _mock_client(search_result=([comp], 1))
        result = search_components(client, "STM32")
        assert result["total"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["lcsc"] == "C83700"
        client.search_jlcpcb.assert_called_once_with(
            keyword="STM32", page=1, page_size=10, part_type=None,
        )
```

### Test Coverage Enforcement
```ini
# pytest.ini
[pytest]
addopts =
    --cov=src/volta
    --cov-report=term-missing
    --cov-report=html:htmlcov
    --cov-report=xml:coverage.xml
    --cov-fail-under=80
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual test suite | Auto-discovered pytest test suite | Migration from unittest to pytest | Improved test discovery and execution |
| No coverage requirements | Enforce 80% coverage | Added in pytest.ini | Better code quality and reduced regressions |
| Sparse integration tests | Comprehensive fixtures | Ongoing initiative | More reliable end-to-end testing |

**Deprecated/outdated:**
- unittest-based test runner replaced by pytest
- Manual coverage analysis replaced by pytest-cov
- Inadequate input validation patterns replaced by Pydantic-based validators

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The pytest.ini configuration accurately reflects current test expectations and coverage goals | Testing Approach | Would break CI pipelines if changes to coverage thresholds weren't reflected |
| A2 | Test fixtures in fixtures/ directory will remain unchanged for compatibility | Integration Testing | Some tests may fail due to fixture structure changes |
| A3 | All public APIs (MCP tools) have sufficient parameter validation tests | Test Coverage | Production risks from malformed inputs |

## Open Questions

1. **What are the specific gaps in the test coverage?**
   - What critical code paths are not sufficiently tested?
   - Are there patterns specific to the MCP protocol that aren't yet covered?
   - What are the most important integration test cases missing?

2. **How are integration and system tests currently organized and maintained?**
   - Do all integration tests reliably reproduce real-world conditions?
   - Are there performance or reliability concerns with current test execution?

3. **Are the test fixtures maintained effectively over time?**
   - Do the KiCad fixture files stay in sync with the current KiCad version used?
   - How are changes to test fixtures handled when upstream files change?

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | Test execution | ✓ | 8.0.0 | — |
| pytest-cov | Coverage measurement | ✓ | 4.0.0 | — |
| mypy | Type checking | ✓ | 1.7.0 | — |
| Python 3.11+ | Runtime | ✓ | 3.11.9 | — |
| kiutils | KiCad parsing | ✓ | 1.4.8 | — |
| kicad-cli | Integration testing | ✗ | — | Use simulation-based tests |

**Missing dependencies with no fallback:**
- kicad-cli integration tests - may require CI improvements

**Missing dependencies with fallback:**
- None - all required testing tools are present

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0 |
| Config file | pytest.ini |
| Quick run command | `pytest tests/test_abstract_ast.py -v` |
| Full suite command | `pytest tests/ --cov=src/volta --cov-report=term-missing --cov-fail-under=80` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-10 | CI coverage gates for Python daemon | unit | `pytest tests/ --cov=src/volta --cov-report=term-missing --cov-fail-under=80` | ✅ |

### Sampling Rate
- **Per task commit:** `pytest tests/test_abstract_ast.py -v`
- **Per wave merge:** `pytest tests/ --cov=src/volta --cov-report=term-missing --cov-fail-under=80`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_abstract_ast.py` — covers Abstract AST models and validation
- [ ] `tests/conftest.py` — shared fixtures for test scenarios
- [ ] Framework install: `pip install pytest pytest-cov` — already detected

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Not applicable for this phase |
| V3 Session Management | no | Not applicable for this phase |
| V4 Access Control | no | Not applicable for this phase |
| V5 Input Validation | yes | All APIs validate inputs using Pydantic |
| V6 Cryptography | no | Not applicable for this phase |

### Known Threat Patterns for Python/kiCad

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Injection in CLI arguments | Injection | Input sanitization with Pydantic validation |
| Parameter pollution | Spoofing | Strong input validation in all entrypoint functions |
| Weak error handling | Information Disclosure | All error paths use structured errors with no sensitive data exposure |

## Sources

### Primary (HIGH confidence)
- pytest.ini - Configuration details for testing framework  
- pyproject.toml - Project-level testing dependencies
- tests/test_abstract_ast.py - Example of testing patterns in use

### Secondary (MEDIUM confidence)
- tests/test_mcp_server.py - MCP protocol testing with mocks
- tests/test_roundtrip/test_roundtrip_stability.py - Integration testing approach

### Tertiary (LOW confidence)
- tests/conftest.py - Fixture management patterns
- tests/test_gate_cli.py - CLI testing patterns