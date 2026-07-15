"""LLM integration module for AI-driven PCB generation.

Provides natural language to GenerationIntent conversion, component suggestion,
and context assembly for Claude via the Anthropic SDK. Also supports local-first
inference via HybridLLMClient with cloud fallback.

This module requires the ``anthropic`` package. Install with::

    pip install kicad-agent[llm]

For local inference (mlx-lm on Apple Silicon)::

    pip install kicad-agent[local]

Usage::

    from volta.llm import IntentParser, ComponentSuggester, LLMClient

    client = LLMClient()
    parser = IntentParser()
    intent = parser.parse("Design a 3.3V voltage regulator")

Hybrid local-first mode::

    from volta.llm import HybridLLMClient
    client = HybridLLMClient()  # local-first with cloud fallback
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
        "LLMClient": "volta.llm.client",
        "IntentParser": "volta.llm.intent_parser",
        "ComponentSuggester": "volta.llm.component_suggester",
        "ContextBuilder": "volta.llm.context_builder",
        "LLMConfigError": "volta.llm.client",
        "INTENT_TOOL": "volta.llm.tools",
        "SUGGEST_TOOL": "volta.llm.tools",
        "COMPONENT_SYSTEM_PROMPT": "volta.llm.tools",
        "DesignCritic": "volta.llm.design_critic",
        "CritiqueFinding": "volta.llm.design_critic",
        "CritiqueReport": "volta.llm.design_critic",
        "CritiqueSeverity": "volta.llm.design_critic",
        "CRITIC_SYSTEM_PROMPT": "volta.llm.design_critic",
        "CRITIC_TOOL": "volta.llm.design_critic",
        "build_spatial_context": "volta.llm.design_critic",
        "ErrorFixer": "volta.llm.error_fixer",
        "FixResult": "volta.llm.error_fixer",
        "FIX_SYSTEM_PROMPT": "volta.llm.error_fixer",
        "FIX_TOOL": "volta.llm.error_fixer",
        "llm_refine_design": "volta.llm.refinement",
        "LLMRefinementResult": "volta.llm.refinement",
        "LLMRefinementIteration": "volta.llm.refinement",
        "llm_generate": "volta.llm.pipeline",
        "LLMGenerationResult": "volta.llm.pipeline",
        # New: hybrid backend + text parsers + unified parsers
        "HybridLLMClient": "volta.llm.backend",
        "HybridResponse": "volta.llm.backend",
        "LLMBackend": "volta.llm.backend",
        "ConfidenceScorer": "volta.llm.confidence",
        "ConfidenceScore": "volta.llm.confidence",
        "extract_json_from_text": "volta.llm.text_prompts",
        "TextIntentParser": "volta.llm.text_parsers",
        "TextErrorFixer": "volta.llm.text_parsers",
        "TextCritiqueParser": "volta.llm.text_parsers",
        "UnifiedIntentParser": "volta.llm.unified_parsers",
        "UnifiedErrorFixer": "volta.llm.unified_parsers",
        # Provider abstraction
        "LLMProvider": "volta.llm.provider",
        "AnthropicProvider": "volta.llm.provider",
        "MockProvider": "volta.llm.provider",
        "get_provider": "volta.llm.provider",
        "KnowledgeManager": "volta.llm.knowledge",
    }

    if name not in _lazy:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # Hybrid/local classes don't require anthropic
    _no_anthropic_required = {
        "HybridLLMClient", "HybridResponse", "LLMBackend",
        "ConfidenceScorer", "ConfidenceScore",
        "extract_json_from_text",
        "TextIntentParser", "TextErrorFixer", "TextCritiqueParser",
        "UnifiedIntentParser", "UnifiedErrorFixer",
        "LLMProvider", "AnthropicProvider", "MockProvider", "get_provider",
        "KnowledgeManager",
    }

    if name not in _no_anthropic_required:
        _check_anthropic_available()

    import importlib

    module_path = _lazy[name]
    module = importlib.import_module(module_path)
    return getattr(module, name)


__all__ = [
    "AnthropicProvider",
    "ComponentSuggester",
    "COMPONENT_SYSTEM_PROMPT",
    "ConfidenceScore",
    "ConfidenceScorer",
    "ContextBuilder",
    "CRITIC_SYSTEM_PROMPT",
    "CRITIC_TOOL",
    "CritiqueFinding",
    "CritiqueReport",
    "CritiqueSeverity",
    "DesignCritic",
    "ErrorFixer",
    "extract_json_from_text",
    "FIX_SYSTEM_PROMPT",
    "FIX_TOOL",
    "FixResult",
    "get_provider",
    "HybridLLMClient",
    "HybridResponse",
    "IntentParser",
    "KnowledgeManager",
    "INTENT_TOOL",
    "LLMBackend",
    "LLMClient",
    "LLMConfigError",
    "LLMGenerationResult",
    "LLMProvider",
    "LLMRefinementIteration",
    "LLMRefinementResult",
    "MockProvider",
    "SUGGEST_TOOL",
    "TextCritiqueParser",
    "TextErrorFixer",
    "TextIntentParser",
    "UnifiedErrorFixer",
    "UnifiedIntentParser",
    "build_spatial_context",
    "llm_generate",
    "llm_refine_design",
]
