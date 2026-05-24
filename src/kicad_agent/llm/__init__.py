"""LLM integration module for AI-driven PCB generation.

Provides natural language to GenerationIntent conversion, component suggestion,
and context assembly for Claude via the Anthropic SDK.

This module requires the ``anthropic`` package. Install with::

    pip install kicad-agent[llm]

Usage::

    from kicad_agent.llm import IntentParser, ComponentSuggester, LLMClient

    client = LLMClient()
    parser = IntentParser()
    intent = parser.parse("Design a 3.3V voltage regulator")
"""

from __future__ import annotations


def _check_anthropic_available() -> None:
    """Verify anthropic is importable; raise ImportError if not."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise ImportError(
            "The 'anthropic' package is required for LLM features. "
            "Install it with: pip install kicad-agent[llm]"
        )


def __getattr__(name: str):
    """Lazy imports that raise ImportError if anthropic is not installed."""
    _lazy = {
        "LLMClient": "kicad_agent.llm.client",
        "IntentParser": "kicad_agent.llm.intent_parser",
        "ComponentSuggester": "kicad_agent.llm.component_suggester",
        "ContextBuilder": "kicad_agent.llm.context_builder",
        "LLMConfigError": "kicad_agent.llm.client",
        "INTENT_TOOL": "kicad_agent.llm.tools",
        "SUGGEST_TOOL": "kicad_agent.llm.tools",
        "COMPONENT_SYSTEM_PROMPT": "kicad_agent.llm.tools",
    }

    if name not in _lazy:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # Check anthropic availability before importing any LLM module
    _check_anthropic_available()

    import importlib

    module_path = _lazy[name]
    module = importlib.import_module(module_path)
    return getattr(module, name)


__all__ = [
    "ComponentSuggester",
    "COMPONENT_SYSTEM_PROMPT",
    "ContextBuilder",
    "IntentParser",
    "INTENT_TOOL",
    "LLMClient",
    "LLMConfigError",
    "SUGGEST_TOOL",
]
