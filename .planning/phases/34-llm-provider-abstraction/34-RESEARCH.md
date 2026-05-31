# Phase 34: LLM Provider Abstraction - Research

**Researched:** 2026-05-30
**Domain:** Python Protocol-based provider abstraction for LLM clients
**Confidence:** HIGH

## Summary

The kicad-agent project has 16 Python files in `src/kicad_agent/llm/` that interact with LLM backends. Currently there are two concrete clients (`LLMClient` wrapping Anthropic SDK, `LocalLLMClient` wrapping mlx-lm) and a `HybridLLMClient` that routes between them. An existing `LLMBackend` protocol in `backend.py` defines `.model` and `.create_message(**kwargs)` -- this protocol is used in `TYPE_CHECKING` blocks across 4 consumer files but never enforced at runtime.

The phase introduces a new `LLMProvider` protocol with a simplified `generate(prompt, system) -> str` method that collapses the current `create_message()` + `response.content[0].text` extraction pattern. However, 4 of 6 consumers use Anthropic `tool_use` extensively (passing `tools=[...]`, `tool_choice=...`, and extracting `tool_use` blocks from response content). These consumers cannot migrate to a simple `generate() -> str` interface without losing structured output capabilities.

**Primary recommendation:** Keep `create_message()` as the primary protocol method since tool_use is fundamental to 4 consumers. Add `generate()` as a convenience method that wraps `create_message()` for text-only callers. The `LLMProvider` protocol should be a superset of `LLMBackend`, not a replacement.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D: Protocol lives in `src/kicad_agent/llm/provider.py` as a new file
- D: Two methods: `generate(prompt: str, system: str | None = None) -> str` and `embed(text: str) -> list[float]`
- D: Protocol is `@runtime_checkable` so isinstance checks work in existing code
- D: AnthropicProvider.generate() wraps create_message() and extracts text from response.content[0].text
- D: `get_provider()` function in `provider.py` reads `KICAD_LLM_PROVIDER` env var
- D: Default is "anthropic" (current behavior)
- D: "mock" returns MockProvider, "anthropic" returns AnthropicProvider
- D: Factory caches provider instance (singleton per provider type)
- D: AnthropicProvider wraps existing LLMClient -- no changes to client.py itself
- D: AnthropicProvider.generate() calls LLMClient.create_message() and returns text string
- D: AnthropicProvider.embed() raises NotImplementedError with clear message
- D: MockProvider: deterministic responses, accepts optional `responses: list[str]`, tracks call count, embed() returns fixed-length zero vector
- D: Consumers import `get_provider()` instead of `LLMClient` directly
- D: Existing `LLMBackend` protocol in backend.py stays (backward compat) -- providers satisfy both protocols
- D: HybridLLMClient updated to work with provider protocol but keeps its own routing logic
- D: DesignCritic, ErrorFixer, ComponentSuggester, IntentParser, UnifiedParsers accept provider via constructor

### Claude's Discretion
- Exact method signatures on the protocol
- How to handle tool_use in generate() -- strip tools from provider.generate(), keep in create_message()
- Whether to keep or deprecate LLMBackend protocol in backend.py
- Test file organization

### Deferred Ideas (OUT OF SCOPE)
- OpenAI provider -- not needed yet, abstraction enables future addition
- Ollama REST provider -- same as above
- Actual embedding implementation -- Anthropic doesn't offer embeddings API
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LLM-13 | Provider protocol with generate(prompt, system) -> str and embed(text) -> list[float] methods | New `LLMProvider` protocol in `provider.py` with `@runtime_checkable` decorator [VERIFIED: Python 3.11 typing.Protocol] |
| LLM-14 | AnthropicProvider implements protocol using anthropic SDK (already installed) | AnthropicProvider wraps existing LLMClient, calls create_message() and extracts text [VERIFIED: anthropic 0.61.0 installed] |
| LLM-15 | Existing LLM calls migrated to provider protocol (llm/ directory) | 7 consumer files identified with exact import patterns and constructor signatures [VERIFIED: codebase analysis] |
| LLM-16 | Provider selection via KICAD_LLM_PROVIDER env var (default "anthropic") | Factory function get_provider() with env var, singleton cache [VERIFIED: existing pattern in HybridLLMClient] |
| LLM-17 | MockProvider for deterministic testing without API calls | MockProvider with configurable responses list, call tracking, zero-vector embed() [VERIFIED: existing MockClient pattern in test_hybrid_client.py] |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Provider protocol definition | Library (llm/) | -- | Protocol is a library concern, not application logic |
| Provider factory + env var | Library (llm/) | Configuration | Env var selection is configuration, factory is library |
| Consumer migration | Library (llm/) | -- | All consumers are within the llm/ module itself |
| MockProvider | Test infrastructure | Library (llm/) | Used primarily by tests but lives in library for imports |
| Existing LLMBackend compat | Library (llm/) | -- | Backward compat is library responsibility |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| typing.Protocol | 3.11 stdlib | Structural subtyping for provider interface | Python built-in, already used by LLMBackend [VERIFIED: codebase] |
| typing.runtime_checkable | 3.11 stdlib | isinstance() checks on Protocol | Required by CONTEXT.md decisions, verified working [VERIFIED: tested] |
| anthropic | 0.61.0 | Anthropic API client | Already installed, wrapped by LLMClient [VERIFIED: pip show] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 8.4.2 | Test framework | All LLM tests [VERIFIED: pyproject.toml] |
| unittest.mock | stdlib | Mocking Anthropic client in tests | Existing pattern across all LLM tests [VERIFIED: conftest_llm.py] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| typing.Protocol | abc.ABC | Protocol enables structural subtyping (duck typing) -- any class with matching methods satisfies it without inheritance. ABC requires explicit inheritance. Protocol is better here because LocalLLMClient and LLMClient already exist without a common base. [VERIFIED: existing LLMBackend uses Protocol] |
| New provider.py module | Extend backend.py | Separate file avoids circular imports (HybridLLMClient imports LLMClient, providers would import LLMClient too). New module keeps responsibilities clear. |

**Installation:**
```bash
# No new dependencies needed -- all using Python 3.11 stdlib + existing anthropic
```

**Version verification:**
- `typing.Protocol`: Python 3.11 stdlib (verified runtime_checkable works)
- `anthropic`: 0.61.0 (verified via `python3 -c "import anthropic; print(anthropic.__version__)"`)

## Architecture Patterns

### System Architecture Diagram

```
                    +------------------+
                    |  get_provider()  |  <-- KICAD_LLM_PROVIDER env var
                    |  (factory)       |
                    +--------+---------+
                             |
              +--------------+---------------+
              |                              |
    +---------v--------+          +----------v---------+
    | AnthropicProvider|          |   MockProvider      |
    |  (wraps LLMClient)|         |  (test fixtures)    |
    +---------+--------+          +---------------------+
              |
    +---------v--------+
    |   LLMClient      |  <-- ANTHROPIC_API_KEY env var
    |   (client.py)    |
    +---------+--------+
              |
    +---------v--------+
    | anthropic SDK    |
    +------------------+

    Consumers (import get_provider or accept provider):
    +------------------+    +------------------+    +------------------+
    |  DesignCritic    |    |  ErrorFixer      |    |  IntentParser    |
    +------------------+    +------------------+    +------------------+
    +------------------+    +------------------+    +------------------+
    | ComponentSuggest |    | UnifiedParsers   |    | Pipeline         |
    +------------------+    +------------------+    +------------------+

    Existing (unchanged, backward compat):
    +------------------+    +------------------+
    | HybridLLMClient  |    | LLMBackend proto |
    +------------------+    +------------------+
```

### Recommended Project Structure
```
src/kicad_agent/llm/
  provider.py         # NEW: LLMProvider protocol + AnthropicProvider + MockProvider + get_provider()
  client.py           # UNCHANGED: LLMClient wrapper
  local_client.py     # UNCHANGED: LocalLLMClient
  backend.py          # MINIMAL CHANGE: HybridLLMClient accepts providers
  __init__.py         # UPDATED: export get_provider, LLMProvider, etc.
  design_critic.py    # MIGRATED: accepts provider via constructor
  error_fixer.py      # MIGRATED: accepts provider via constructor
  component_suggester.py  # MIGRATED: accepts provider via constructor
  intent_parser.py    # MIGRATED: accepts provider via constructor
  unified_parsers.py  # MIGRATED: accepts provider via constructor
  pipeline.py         # MIGRATED: uses get_provider()
```

### Pattern 1: LLMProvider Protocol with Dual Interface
**What:** Protocol defines both the simple `generate()` and the full `create_message()` for tool_use consumers.
**When to use:** All consumers should depend on the protocol, not on LLMClient directly.
**Example:**
```python
# Source: [ASSUMED based on CONTEXT.md decisions + codebase analysis]
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    All providers must implement generate() for text-only use cases and
    create_message() for full API compatibility including tool_use.
    """

    @property
    def model(self) -> str: ...

    def generate(self, prompt: str, system: str | None = None) -> str: ...

    def embed(self, text: str) -> list[float]: ...

    def create_message(self, **kwargs: Any) -> Any: ...
```

### Pattern 2: AnthropicProvider Wrapping Existing Client
**What:** AnthropicProvider delegates to LLMClient, collapsing the create_message() + content[0].text pattern.
**When to use:** For text-only consumers that don't need tool_use.
**Example:**
```python
class AnthropicProvider:
    """Anthropic provider wrapping existing LLMClient."""

    def __init__(self, model: str | None = None) -> None:
        from kicad_agent.llm.client import LLMClient
        self._client = LLMClient(model=model)

    @property
    def model(self) -> str:
        return self._client.model

    def generate(self, prompt: str, system: str | None = None) -> str:
        kwargs: dict[str, Any] = {
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = self._client.create_message(**kwargs)
        return response.content[0].text

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Anthropic does not offer an embeddings API. "
            "Use a different provider for embedding support."
        )

    def create_message(self, **kwargs: Any) -> Any:
        return self._client.create_message(**kwargs)
```

### Pattern 3: MockProvider for Testing
**What:** Deterministic responses, call tracking, zero-vector embeddings.
**When to use:** All tests that currently mock `anthropic.Anthropic`.
**Example:**
```python
class MockProvider:
    """Mock provider for deterministic testing."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or ["mock response"]
        self._call_count = 0

    @property
    def model(self) -> str:
        return "mock-provider"

    @property
    def call_count(self) -> int:
        return self._call_count

    def generate(self, prompt: str, system: str | None = None) -> str:
        self._call_count += 1
        idx = min(self._call_count - 1, len(self._responses) - 1)
        return self._responses[idx]

    def embed(self, text: str) -> list[float]:
        return [0.0] * 768

    def create_message(self, **kwargs: Any) -> Any:
        self._call_count += 1
        idx = min(self._call_count - 1, len(self._responses) - 1)
        # Return Anthropic-compatible response
        class _Content:
            type = "text"
            text = self._responses[idx]
        class _Msg:
            content = [_Content()]
            role = "assistant"
            model = "mock-provider"
            stop_reason = "end_turn"
        return _Msg()
```

### Pattern 4: Provider Factory with Singleton Cache
**What:** `get_provider()` reads env var, caches instance, returns provider.
**When to use:** Entry point for all consumer code.
**Example:**
```python
_cache: dict[str, Any] = {}

def get_provider(name: str | None = None) -> Any:
    """Get LLM provider by name or KICAD_LLM_PROVIDER env var."""
    import os
    provider_name = name or os.environ.get("KICAD_LLM_PROVIDER", "anthropic")

    if provider_name in _cache:
        return _cache[provider_name]

    if provider_name == "anthropic":
        provider = AnthropicProvider()
    elif provider_name == "mock":
        provider = MockProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")

    _cache[provider_name] = provider
    return provider
```

### Anti-Patterns to Avoid
- **Protocol without create_message():** 4 consumers (DesignCritic, ErrorFixer, IntentParser, ComponentSuggester) pass `tools=[...]` and `tool_choice={...}` to `create_message()`, then iterate `response.content` looking for `tool_use` blocks. A `generate() -> str` only protocol cannot serve these consumers. The protocol MUST include `create_message()` for backward compatibility.
- **Breaking LLMBackend compatibility:** HybridLLMClient, UnifiedParsers, and test infrastructure depend on the existing `LLMBackend` protocol. The new provider protocol should be a superset, and providers should satisfy both protocols implicitly.
- **Mutating existing client.py:** CONTEXT.md explicitly locks "no changes to client.py itself." AnthropicProvider wraps LLMClient without modifying it.
- **Changing consumer behavior:** "Pure refactor" -- all consumer logic stays the same, only the import source changes.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Provider protocol | Custom ABC with register() | typing.Protocol + runtime_checkable | Structural subtyping works with existing classes without inheritance changes [VERIFIED: LLMBackend already uses this pattern] |
| Response mocking | Complex mock object hierarchies | MockProvider with Anthropic-compatible response objects | Simple, deterministic, matches existing FakeMessage/FakeTextBlock pattern [VERIFIED: conftest_llm.py] |
| Singleton caching | Thread-safe cache with locks | Simple dict keyed by provider name | Single-threaded context (MCP server), no concurrency concern |
| Embedding stub | Fake embedding with random vectors | Fixed zero vector [0.0] * 768 | Deterministic for testing, clear "not implemented" via NotImplementedError for real use |

**Key insight:** The existing codebase already has two protocols (`LLMBackend`) and mock patterns (`MockClient` in test_hybrid_client.py, `FakeMessage`/`FakeToolUseBlock` in conftest_llm.py). The new protocol should be additive, not a replacement.

## Runtime State Inventory

> This is a pure refactor phase (no rename/migration). No runtime state inventory needed.

N/A -- no stored data, service config, OS registrations, secrets, or build artifacts affected.

## Common Pitfalls

### Pitfall 1: tool_use Consumers Cannot Use generate()
**What goes wrong:** If the protocol only has `generate(prompt, system) -> str`, 4 consumers that pass `tools=[CRITIC_TOOL]` and extract `tool_use` blocks from response content cannot migrate to the protocol.
**Why it happens:** `generate()` returns a plain string, but tool_use consumers need the full Anthropic response object with `content` list containing `tool_use` blocks with `name`, `input`, and `id` attributes.
**How to avoid:** The protocol MUST include `create_message(**kwargs) -> Any` alongside `generate()`. AnthropicProvider's `create_message()` delegates directly to LLMClient without modification. Consumers that need tool_use call `create_message()` directly.
**Warning signs:** If a consumer migration removes `tools=` parameter or replaces `for block in response.content` with simple text extraction.

### Pitfall 2: Circular Import Between provider.py and backend.py
**What goes wrong:** If `provider.py` imports from `backend.py` and `backend.py` imports from `provider.py`, Python raises ImportError at module load time.
**Why it happens:** AnthropicProvider needs LLMClient from client.py (no cycle there). But if HybridLLMClient in backend.py tries to import get_provider from provider.py, and provider.py imports anything from backend.py, a cycle forms.
**How to avoid:** Keep provider.py imports minimal: only import LLMClient from client.py (which has no llm/ imports). backend.py can optionally import from provider.py (one-way dependency). Never import from backend.py into provider.py.
**Warning signs:** ImportError on first test run after creating provider.py.

### Pitfall 3: Breaking Existing Tests That Mock anthropic.Anthropic
**What goes wrong:** Existing tests use `conftest_llm.py`'s `mock_anthropic_client` fixture which patches `anthropic.Anthropic` at the module level. If consumers switch to `get_provider()` but tests don't set `KICAD_LLM_PROVIDER=mock`, tests will try to create real Anthropic clients.
**Why it happens:** MockProvider replaces the mock at a different level (provider vs SDK). The existing mock patches the SDK directly; MockProvider patches at the provider factory level.
**How to avoid:** Tests for migrated consumers should either (a) inject MockProvider via constructor parameter, or (b) set `KICAD_LLM_PROVIDER=mock` env var. Existing tests that mock at the SDK level can continue to work for AnthropicProvider since it wraps LLMClient which uses the same SDK.
**Warning signs:** Tests failing with LLMConfigError about missing ANTHROPIC_API_KEY.

### Pitfall 4: ComponentSuggester Does Not Accept client Parameter
**What goes wrong:** ComponentSuggester's constructor is `__init__(self, model: str | None = None)` with no `client` parameter. Other consumers (DesignCritic, ErrorFixer, IntentParser) accept `client: LLMBackend | None = None`.
**Why it happens:** ComponentSuggester was written earlier and hasn't been updated to support dependency injection.
**How to avoid:** Add `client` parameter to ComponentSuggester's constructor matching the pattern used by DesignCritic and IntentParser: `self._client = client or LLMClient(model=model)`.
**Warning signs:** ComponentSuggester migration creates a different constructor pattern than other consumers.

### Pitfall 5: HybridLLMClient Assumes LLMBackend Protocol Shape
**What goes wrong:** HybridLLMClient's `_dispatch_local()` calls `client.create_message(**local_kwargs)` and accesses `raw_response.content[0].text`. If the new provider protocol changes response shapes, hybrid routing breaks.
**Why it happens:** HybridLLMClient assumes the response has Anthropic-compatible `.content` list with text blocks.
**How to avoid:** AnthropicProvider's `create_message()` passes through the real Anthropic response unchanged. MockProvider's `create_message()` returns an object with `.content[0].text`. Both satisfy HybridLLMClient's expectations.
**Warning signs:** `AttributeError: 'str' object has no attribute 'content'` in hybrid tests.

## Code Examples

### Consumer Constructor Pattern (Current)
```python
# Source: [VERIFIED: src/kicad_agent/llm/design_critic.py lines 223-228]
class DesignCritic:
    def __init__(
        self,
        model: str | None = None,
        client: LLMBackend | None = None,
    ) -> None:
        self._client = client or LLMClient(model=model)
```

```python
# Source: [VERIFIED: src/kicad_agent/llm/component_suggester.py lines 47-48]
class ComponentSuggester:
    def __init__(self, model: str | None = None) -> None:
        self._client = LLMClient(model=model)
```

### Consumer Constructor Pattern (After Migration)
```python
# DesignCritic, ErrorFixer, IntentParser -- already accept client, just change type hint
class DesignCritic:
    def __init__(
        self,
        model: str | None = None,
        client: LLMBackend | None = None,  # stays compatible
        provider: LLMProvider | None = None,  # NEW optional param
    ) -> None:
        if provider is not None:
            self._client = provider  # provider satisfies LLMBackend too
        else:
            self._client = client or LLMClient(model=model)
```

```python
# ComponentSuggester -- needs client param added (currently missing)
class ComponentSuggester:
    def __init__(
        self,
        model: str | None = None,
        provider: Any | None = None,
    ) -> None:
        if provider is not None:
            self._client = provider
        else:
            self._client = LLMClient(model=model)
```

### Existing LLMBackend Protocol (Stays)
```python
# Source: [VERIFIED: src/kicad_agent/llm/backend.py lines 53-64]
@runtime_checkable
class LLMBackend(Protocol):
    """Protocol for LLM clients that can produce messages."""

    @property
    def model(self) -> str: ...

    def create_message(self, **kwargs: Any) -> Any: ...
```

### How Consumers Use create_message (tool_use pattern)
```python
# Source: [VERIFIED: src/kicad_agent/llm/design_critic.py lines 259-266]
message = self._client.create_message(
    max_tokens=16000,
    system=CRITIC_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_content}],
    tools=[CRITIC_TOOL],
    tool_choice={"type": "tool", "name": "design_critique"},
    thinking={"type": "enabled", "budget_tokens": 8000},
)

# Then iterate content blocks:
for block in message.content:
    if block.type == "tool_use" and block.name == "design_critique":
        tool_block = block
        break
```

### How Consumers Extract Text (4 consumers use this)
```python
# Source: [VERIFIED: src/kicad_agent/llm/unified_parsers.py lines 48-53]
def _get_text(response: Any) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""
```

### Test Mock Pattern (Existing)
```python
# Source: [VERIFIED: tests/conftest_llm.py lines 16-42]
class FakeToolUseBlock:
    def __init__(self, name: str, tool_input: dict[str, Any]) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = tool_input
        self.id = "toolu_test_123"

class FakeMessage:
    def __init__(self, blocks: list[Any], stop_reason: str = "end_turn") -> None:
        self.content = blocks
        self.stop_reason = stop_reason
        self.model = "claude-sonnet-4-20250514"
        self.usage = {"input_tokens": 100, "output_tokens": 200}
```

### InferenceWrapper Uses LocalLLMClient Directly (Not Migrated)
```python
# Source: [VERIFIED: src/kicad_agent/inference/wrapper.py lines 98-105]
from kicad_agent.llm.local_client import LocalLLMClient
self._llm_client = LocalLLMClient(
    model=self._model_name,
    adapter_dir=self._adapter_dir,
    max_tokens=self._max_tokens,
    temperature=self._temperature,
)
```
Note: InferenceWrapper uses `LocalLLMClient.chat()`, not `create_message()`. It is NOT a candidate for migration to the provider protocol -- it uses a different API surface entirely.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct LLMClient imports | LLMBackend protocol + TYPE_CHECKING | Phase 15 (AI Generation Wiring) | Structural subtyping established |
| Cloud-only inference | HybridLLMClient with local-first | Phase 22 (Agent Integration) | Two-tier routing pattern |
| anthropic.Anthropic mock in tests | conftest_llm.py FakeMessage/FakeToolUseBlock | Phase 15 | Test infrastructure for LLM |

**Deprecated/outdated:**
- None currently -- all patterns are active and in use.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Protocol should include `create_message()` alongside `generate()` for tool_use compatibility | Architecture Patterns | If CONTEXT.md insists on `generate()` only, 4 consumers cannot migrate and the phase scope changes fundamentally |
| A2 | ComponentSuggester constructor needs `client`/`provider` parameter added | Code Examples | If there is a reason it was intentionally excluded, adding it may conflict with design intent |
| A3 | InferenceWrapper should NOT be migrated (uses `.chat()` not `.create_message()`) | Code Examples | If CONTEXT.md intended it for migration, need adapter for `.chat()` API |
| A4 | `KICAD_LLM_PROVIDER` env var name -- CONTEXT.md specifies this name | Standard Stack | If there is a naming conflict with existing env vars, need to verify uniqueness |

**Assumption A1 is the most critical.** The CONTEXT.md decisions say "generate(prompt, system) -> str" but the codebase shows 4 consumers using tool_use with create_message(). The planner must decide: does the protocol include create_message() (superset approach) or do we add a second tool_use-specific method?

## Open Questions

1. **Protocol scope: generate() only vs generate() + create_message()?**
   - What we know: CONTEXT.md says two methods: `generate()` and `embed()`. But 4 of 6 consumers pass `tools=[...]` to `create_message()` and extract tool_use blocks.
   - What's unclear: Whether the locked decision about "two methods" is a hard constraint or whether `create_message()` can be added as a third method for backward compat.
   - Recommendation: Include `create_message()` in the protocol as a third method. The "two methods" in CONTEXT.md refers to the new simplified API surface. `create_message()` is preserved for backward compat, not as a new feature. This is consistent with the locked decision "Existing LLMBackend protocol stays."

2. **Should provider.py also export LLMProviderProtocol type alias?**
   - What we know: LLMBackend already exists as a runtime_checkable Protocol.
   - What's unclear: Whether the new LLMProvider should extend/replace LLMBackend or coexist.
   - Recommendation: Coexist. LLMProvider can implicitly satisfy LLMBackend (same `.model` and `.create_message()` methods). No need for explicit inheritance. This matches "providers satisfy both protocols" from CONTEXT.md.

3. **Should `get_provider()` return type be `Any` or `LLMProvider`?**
   - What we know: runtime_checkable protocols support isinstance() checks.
   - What's unclear: Whether static type checkers (mypy/pyright) will be happy with Protocol return types from a factory.
   - Recommendation: Return `LLMProvider` type. Use `from __future__ import annotations` to avoid circular type evaluation issues.

## Environment Availability

> This phase is purely code/config changes with no external dependencies beyond the existing anthropic SDK.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11 | All code | Yes | 3.11.11 | -- |
| anthropic SDK | AnthropicProvider | Yes | 0.61.0 | -- |
| pytest | Tests | Yes | 8.4.2 | -- |
| typing.Protocol | Provider protocol | Yes | stdlib | -- |
| KICAD_AGENT_MODEL env var | AnthropicProvider | Yes | Existing | "claude-sonnet-4-20250514" default |
| ANTHROPIC_API_KEY env var | AnthropicProvider | Yes (tests use test key) | -- | MockProvider bypasses |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `python3 -m pytest tests/test_llm*.py tests/test_hybrid_client.py -x -q` |
| Full suite command | `python3 -m pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LLM-13 | LLMProvider protocol with generate() and embed() | unit | `python3 -m pytest tests/test_llm_provider.py -x -q` | Wave 0 |
| LLM-14 | AnthropicProvider implements protocol | unit | `python3 -m pytest tests/test_llm_provider.py::TestAnthropicProvider -x -q` | Wave 0 |
| LLM-15 | Consumers migrated to provider protocol | unit (per consumer) | `python3 -m pytest tests/test_llm_*.py -x -q` | Existing (79 LLM tests) |
| LLM-16 | Provider factory with env var | unit | `python3 -m pytest tests/test_llm_provider.py::TestGetProvider -x -q` | Wave 0 |
| LLM-17 | MockProvider deterministic testing | unit | `python3 -m pytest tests/test_llm_provider.py::TestMockProvider -x -q` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_llm*.py tests/test_hybrid_client.py -x -q`
- **Per wave merge:** `python3 -m pytest tests/ -x -q --ignore=tests/test_format_convert.py`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_llm_provider.py` -- covers LLM-13, LLM-14, LLM-16, LLM-17 (protocol, AnthropicProvider, factory, MockProvider)

## Security Domain

> Phase is a pure refactor with no new attack surface. Security enforcement assumed enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Provider wraps existing auth (ANTHROPIC_API_KEY) |
| V3 Session Management | No | Stateless provider |
| V4 Access Control | No | No access control changes |
| V5 Input Validation | Yes | Pydantic validation on all LLM outputs (unchanged from existing) |
| V6 Cryptography | No | No crypto changes |

### Known Threat Patterns for Python Protocol Refactor

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Provider injection via env var | Tampering | KICAD_LLM_PROVIDER validated against whitelist ("anthropic", "mock") |
| MockProvider in production | Spoofing | Document that "mock" is for testing only; default is "anthropic" |

## Sources

### Primary (HIGH confidence)
- Codebase analysis of `src/kicad_agent/llm/` -- all 16 files read and analyzed
- `tests/conftest_llm.py` -- existing mock patterns verified
- `tests/test_hybrid_client.py` -- existing MockClient pattern verified
- Python 3.11 `typing.Protocol` with `@runtime_checkable` -- tested working
- `anthropic` 0.61.0 -- verified installed
- `pyproject.toml` -- pytest 8.4.2, Python 3.11 target

### Secondary (MEDIUM confidence)
- CONTEXT.md decisions -- locked by user, not verified against external sources

### Tertiary (LOW confidence)
- None -- all findings verified against codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all dependencies verified installed, Python 3.11 stdlib confirmed
- Architecture: HIGH - codebase fully analyzed, consumer patterns documented with line numbers
- Pitfalls: HIGH - derived from actual codebase patterns, not hypothetical

**Research date:** 2026-05-30
**Valid until:** 2026-06-30 (stable domain -- Python Protocol patterns don't change rapidly)
