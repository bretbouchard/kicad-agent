"""AI legibility critic — Gemma 4 primary + Claude R-4 fallback (Phase 109).

Scores autolayout output (or any schematic) against the Phase 48.5 Schematic
Readability Score (SRS) signal. Implements the hybrid pattern proven in the
Phase 98-101 routing stack: deterministic-primary + AI-fallback with R-4
validation gate.

LOCKED DECISIONS (see 109-CONTEXT.md):
- D-01: Gemma 4 12B V2 primary, Claude R-4 fallback
- D-02: Overall SRS + per-factor scores (density/clarity/spacing/organization)
- D-03: Structured JSON only (no markdown emission from models)
- D-04: Separate critique_sch op (decoupled from auto_layout_sch)

HARD CONSTRAINTS:
- LO-04 (Phase 107 §no-coordinates-from-AI): Suggestions NEVER contain x/y/
  position/coord fields. Enforced at three layers: prompt, parser, constructor.
- Phase 100 CR-01: CritiqueResult is frozen. factors dict wrapped with
  MappingProxy via factors_view() (MED-02 Option B).
- Phase 98 R-2: parse_legibility_json NEVER raises, returns {} on failure.
- Phase 98 R-6: Critic path NEVER raises. Broad except → fallback result with
  model_used="none" and confidence=0.0.
- Phase 101 P101-INV-01: NEVER kiutils.Schematic.to_file(). Read-only op —
  no file mutation at all.
- LO-08 (Phase 109 Gate 2 finding, fixed in Phase 110 Plan 01 Task 0):
  max_tokens=2048 bound on every Claude create_message call. Prevents
  unbounded verbose responses from consuming token budget and triggering
  pathological brace-matching in parse_legibility_json.

Integration Testing
-------------------
Real Gemma 4 12B V2 (23.8 GB) and real Claude API invocation are deferred to
the Phase 110 eval harness. Unit tests inject FakePipeline / FakeClaudeClient.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from kicad_agent.inference.vision_pipeline import KiCadVisionPipeline
    from kicad_agent.llm.client import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Phase 107 LO-04: forbidden coordinate field names in AI output. Defense in
# depth — prompt discourages these, parser rejects them, constructor blocks them.
_FORBIDDEN_COORD_KEYS = frozenset({"x", "y", "position", "coord", "coords", "px", "py"})

# D-02: factor names match Phase 48.5 SchematicReadabilityScorer exactly
_REQUIRED_FACTORS = frozenset({"density", "clarity", "spacing", "organization"})

# Severity sort rank (lower = higher priority)
_SEVERITY_RANK = {"critical": 0, "warning": 1, "suggestion": 2}

# Context §Claude's Discretion: suggestion cap
_MAX_SUGGESTIONS = 10

# Markdown fence extractor (Phase 98 R-2 step 2)
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# ---------------------------------------------------------------------------
# SECTION A — Schemas (frozen per Phase 100 CR-01)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Suggestion:
    """A relative legibility suggestion (Phase 107 §no-coordinates-from-AI).

    LO-04 hardening: text-only — NEVER contains x/y/position/coord fields.
    Constructor rejects forbidden field names at construction time.

    Attributes:
        text: Human-readable suggestion text (relative, not coordinate-laden).
        severity: "critical" | "warning" | "suggestion".
        category: "density" | "clarity" | "spacing" | "organization".
    """

    text: str
    severity: str
    category: str

    def __post_init__(self) -> None:
        # LO-04 defense layer 3 (constructor): reject any forbidden field name.
        # This catches hand-constructed Suggestions like Suggestion(x=50).
        for forbidden in _FORBIDDEN_COORD_KEYS:
            if forbidden in self.__dict__:
                raise ValueError(
                    f"LO-04 violation: Suggestion cannot contain coordinate field {forbidden!r}"
                )
        # Severity / category sanity (cheap validation, no hard constraint)
        if self.severity not in _SEVERITY_RANK:
            # Not a hard error — accept unknown severity with default rank
            pass


@dataclass(frozen=True)
class CritiqueResult:
    """Result of a legibility critique (Phase 110 GRPO contract).

    Frozen per Phase 100 CR-01. The factors dict is wrapped in MappingProxy
    via factors_view() for read-only access — direct .factors[key] = value
    is technically possible but consumers should use factors_view() for
    immutability guarantees (MED-02 Option B documented deviation).

    Attributes:
        overall_srs: Composite Schematic Readability Score (0.0-1.0).
        factors: Per-factor scores — density/clarity/spacing/organization.
        suggestions: Capped tuple of Suggestion objects (sorted by severity).
        model_used: "gemma4" | "claude" | "none".
        confidence: Model's self-reported confidence (0.0-1.0).
        latency_ms: Wall-clock latency of the critique call in ms.
    """

    overall_srs: float
    factors: dict[str, float]
    suggestions: tuple[Suggestion, ...]
    model_used: str
    confidence: float
    latency_ms: int

    def factors_view(self) -> MappingProxyType[str, float]:
        """Return an immutable MappingProxy view of factors.

        MED-02 Option B mitigation: Phase 110 consumers should use this method
        for read-only access. Direct .factors[key] = value will mutate the
        underlying dict — factors_view() returns a TypeError-on-write proxy.
        """
        return MappingProxyType(self.factors)


# ---------------------------------------------------------------------------
# SECTION B — Validation helpers
# ---------------------------------------------------------------------------


def validate_no_coordinates(d: dict) -> None:
    """Recursively scan dict for forbidden coordinate field names (LO-04).

    Raises:
        ValueError: If any forbidden key (x/y/position/coord/coords/px/py) is
            found anywhere in the dict, including nested dicts/lists.
    """
    if not isinstance(d, dict):
        return
    for key, value in d.items():
        if key in _FORBIDDEN_COORD_KEYS:
            raise ValueError(
                f"LO-04 violation: forbidden coordinate field {key!r} in AI output"
            )
        if isinstance(value, dict):
            validate_no_coordinates(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    validate_no_coordinates(item)


def validate_factors(factors: dict[str, float]) -> None:
    """Validate that factors dict has exactly the 4 required factor names (D-02).

    Raises:
        ValueError: If factors dict is missing a required factor or contains
            an extra factor.
    """
    keys = set(factors.keys())
    missing = _REQUIRED_FACTORS - keys
    extra = keys - _REQUIRED_FACTORS
    if missing or extra:
        raise ValueError(
            f"factors dict must have exactly {_REQUIRED_FACTORS}; "
            f"missing={missing}, extra={extra}"
        )


def validate_score_range(value: float, name: str = "score") -> None:
    """Validate that score is in [0.0, 1.0].

    Raises:
        ValueError: If value < 0.0 or value > 1.0.
    """
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be in [0.0, 1.0], got {value}")


# ---------------------------------------------------------------------------
# SECTION C — LegibilityCritic Protocol (mirrors routing/strategy.py)
# ---------------------------------------------------------------------------


class LegibilityCritic(Protocol):
    """Protocol for legibility critics.

    Implementations include GemmaLegibilityCritic (primary), ClaudeLegibilityCritic
    (R-4 fallback), and HybridLegibilityCritic (dispatcher). Protocol enables
    structural subtyping — implementations don't need to inherit.
    """

    def critique(
        self,
        image: Any,
        file_path: str = "",
    ) -> CritiqueResult:
        """Score a rendered schematic image for legibility.

        Args:
            image: PIL.Image of the rendered schematic.
            file_path: Optional file path for logging context.

        Returns:
            CritiqueResult with overall_srs, factors, suggestions, model_used,
            confidence, and latency_ms.

        R-6: Implementations NEVER raise. On any failure, return
        CritiqueResult(model_used="none", confidence=0.0).
        """
        ...


# ---------------------------------------------------------------------------
# SECTION D — build_legibility_prompt
# ---------------------------------------------------------------------------


def build_legibility_prompt() -> str:
    """Build the legibility-critique prompt for Gemma 4.

    Few-shot prompt instructing the model to emit JSON with overall_srs,
    factors{density,clarity,spacing,organization}, suggestions (relative text
    only, NEVER x/y/position), and confidence.

    LO-04 prompt hardening (defense layer 1): explicit instruction forbidding
    coordinate fields.

    ponytail: prompt is intentionally short — the validator (parse_legibility_json
    + Suggestion.__post_init__) does the heavy lifting, not the prompt. Models
    hallucinate; validators don't.
    """
    return """You are reviewing a KiCad schematic for legibility and visual quality.

Score the schematic on four factors (0.0 to 1.0):
- density: Are components spread out enough to read? Lower density is better.
- clarity: Are labels unique and readable? Penalize duplicate or unclear labels.
- spacing: Are elements properly spaced with no overlaps?
- organization: Do components match functional groups and signal flow?

Provide:
- overall_srs: Composite Schematic Readability Score (0.0 to 1.0).
- factors: Object with density, clarity, spacing, organization scores.
- suggestions: List of relative improvement suggestions. Each suggestion has
  text (relative description only), severity (critical/warning/suggestion),
  and category (density/clarity/spacing/organization).
- confidence: Your confidence in this assessment (0.0 to 1.0).

CRITICAL: Do NOT include x, y, position, coord, or coordinate fields in any
suggestion. Suggestions must be relative descriptions like "reduce density
near U3" — never absolute placements like "move C5 to (50, 30)".

Respond with JSON only, no markdown formatting.

Example response:
{
  "overall_srs": 0.75,
  "factors": {"density": 0.7, "clarity": 0.8, "spacing": 0.75, "organization": 0.7},
  "suggestions": [
    {"text": "reduce density near U3", "severity": "warning", "category": "density"}
  ],
  "confidence": 0.85
}
"""


# ---------------------------------------------------------------------------
# SECTION E — parse_legibility_json (Phase 98 R-2 pattern)
# ---------------------------------------------------------------------------


def parse_legibility_json(raw: str | None) -> dict:
    """Defensively extract a JSON dict from raw model output (Phase 98 R-2).

    Mirrors routing/strategy_parser.py::parse_strategy_json. NEVER raises;
    returns {} on any failure. The caller treats {} as a signal to trigger
    the R-6 fallback.

    Algorithm (4-step + empty check):
    1. Strip + empty check
    2. Try direct json.loads
    3. Try markdown fences
    4. Brace-match outermost spans, keep the largest parseable dict
    5. Fallback to {}

    LO-04 defense layer 2 (parser): after ANY successful parse, recursively
    scan the parsed dict for _FORBIDDEN_COORD_KEYS. If found, return {} (treat
    as unparseable — R-6 will fall back).

    Args:
        raw: Raw text from the vision model (may be fenced, prefixed, malformed).

    Returns:
        Parsed dict on success, {} on any failure or LO-04 violation.
    """
    if not raw:
        return {}
    stripped = raw.strip()
    if not stripped:
        return {}

    # 1. Try direct json.loads (ideal case — bare JSON)
    candidate = _try_parse(stripped)
    if isinstance(candidate, dict):
        return _scan_coordinates(candidate)

    # 2. Extract from markdown fences
    for match in _FENCE_RE.finditer(stripped):
        candidate = _try_parse(match.group(1))
        if isinstance(candidate, dict):
            scanned = _scan_coordinates(candidate)
            if scanned:
                return scanned

    # 3. Find all brace-matched spans; keep the largest parseable dict
    spans = _extract_brace_spans(stripped)
    best: dict | None = None
    best_key_count = -1
    for span in spans:
        candidate = _try_parse(span)
        if isinstance(candidate, dict):
            # LO-04: reject dicts containing forbidden coordinate keys
            try:
                validate_no_coordinates(candidate)
            except ValueError:
                continue
            if len(candidate) > best_key_count:
                best_key_count = len(candidate)
                best = candidate
    if best is not None:
        return best

    # 4. Total failure
    return {}


def _try_parse(text: str) -> dict | None:
    """Attempt json.loads; return dict or None on any failure."""
    try:
        loaded = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(loaded, dict):
        return loaded
    return None


def _scan_coordinates(candidate: dict) -> dict:
    """LO-04: return candidate if clean, {} if it contains coordinates."""
    try:
        validate_no_coordinates(candidate)
    except ValueError:
        return {}
    return candidate


def _extract_brace_spans(text: str) -> list[str]:
    """Extract all top-level brace-balanced spans from text.

    Single-pass O(n) using a stack of open-brace positions. Tracks string
    literals so braces inside JSON string values do not confuse the matcher.
    Mirrors routing/strategy_parser.py IN-02 implementation.
    """
    spans: list[str] = []
    stack: list[int] = []
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                if depth == 0:
                    stack.append(i)
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and stack:
                        start = stack.pop()
                        spans.append(text[start : i + 1])
    return spans


# ---------------------------------------------------------------------------
# SECTION F — GemmaLegibilityCritic (primary, R-6 fallback)
# ---------------------------------------------------------------------------


class GemmaLegibilityCritic:
    """Primary legibility critic — Gemma 4 12B V2 via KiCadVisionPipeline.

    Implements LegibilityCritic Protocol via structural subtyping.
    R-6: on ANY failure, returns CritiqueResult with model_used='none'
    and confidence=0.0. NEVER raises.

    Composition over inheritance: takes pipeline as constructor arg (NOT a
    subclass). Matches Phase 98 AiRoutingStrategy pattern.
    """

    def __init__(self, pipeline: "KiCadVisionPipeline") -> None:
        self._pipeline = pipeline

    def critique(self, image: Any, file_path: str = "") -> CritiqueResult:
        """Run Gemma 4 vision critique. NEVER raises (R-6)."""
        start = time.monotonic()
        try:
            raw = self._pipeline.generate_from_image(image, build_legibility_prompt())
            parsed = parse_legibility_json(raw)
            latency_ms = int((time.monotonic() - start) * 1000)
            if not parsed:
                logger.warning(
                    "GemmaLegibilityCritic: parse failed or LO-04 violation, "
                    "triggering R-6 fallback"
                )
                return self._fallback(latency_ms)
            return self._build_result(parsed, latency_ms)
        except Exception as exc:
            # R-6: broad except — model is untrusted, any failure mode triggers fallback.
            # T-109-02: log ONLY exception type+message (no stack traces with file paths).
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "GemmaLegibilityCritic R-6 fallback: %s: %s",
                type(exc).__name__, exc,
            )
            return self._fallback(latency_ms)

    def _build_result(self, parsed: dict, latency_ms: int) -> CritiqueResult:
        """Build CritiqueResult from parsed dict. Falls back on validation error."""
        try:
            overall_srs = float(parsed.get("overall_srs", 0.0))
            validate_score_range(overall_srs, "overall_srs")

            factors_raw = parsed.get("factors", {})
            if not isinstance(factors_raw, dict):
                return self._fallback(latency_ms)
            factors = {k: float(v) for k, v in factors_raw.items()}
            validate_factors(factors)
            for fname, fval in factors.items():
                validate_score_range(fval, fname)

            confidence = float(parsed.get("confidence", 0.0))
            validate_score_range(confidence, "confidence")

            suggestions = _build_suggestions(parsed.get("suggestions", []))

            return CritiqueResult(
                overall_srs=overall_srs,
                factors=factors,
                suggestions=suggestions,
                model_used="gemma4",
                confidence=confidence,
                latency_ms=latency_ms,
            )
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning(
                "GemmaLegibilityCritic validation failure: %s: %s",
                type(exc).__name__, exc,
            )
            return self._fallback(latency_ms)

    def _fallback(self, latency_ms: int) -> CritiqueResult:
        """R-6 fallback: zero-value CritiqueResult with model_used='none'."""
        return CritiqueResult(
            overall_srs=0.0,
            factors={k: 0.0 for k in _REQUIRED_FACTORS},
            suggestions=(),
            model_used="none",
            confidence=0.0,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# SECTION G — ClaudeLegibilityCritic (R-4 fallback)
# ---------------------------------------------------------------------------


class ClaudeLegibilityCritic:
    """R-4 fallback legibility critic — Claude via LLMClient wrapper.

    Mirrors Phase 48.5 SchematicReviewer.vision_review pattern. Per Council
    MED-01 Option A: uses LLMClient.create_message(**kwargs) (not raw
    anthropic.Anthropic) to reuse existing auth/retry logic.

    R-6: on ANY failure, returns CritiqueResult with model_used='none'.
    NEVER raises.

    LO-08 (Phase 109 Gate 2 finding, fixed in Phase 110 Plan 01 Task 0):
    max_tokens=2048 bound on every create_message call. The bound is a
    class-level constant so it can be inspected and overridden in tests.
    """

    # LO-08: documents the max_tokens bound. 2048 tokens is generous for the
    # JSON shape (max ~10 suggestions * ~30 tokens + ~200 tokens of scoring
    # JSON). A verbose Claude response that rambles for 50K tokens would
    # trigger pathological O(n) brace-matching in parse_legibility_json.
    _MAX_TOKENS: int = 2048

    def __init__(self, client: "LLMClient") -> None:
        self._client = client

    def critique(self, image: Any, file_path: str = "") -> CritiqueResult:
        """Run Claude vision critique. NEVER raises (R-6)."""
        start = time.monotonic()
        try:
            image_b64 = _encode_image_for_claude(image)
            if image_b64 is None:
                logger.warning("ClaudeLegibilityCritic: image encoding failed")
                return self._fallback(int((time.monotonic() - start) * 1000))

            prompt = build_legibility_prompt()
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                    ],
                },
            ]
            # LO-08: bound max_tokens on every create_message call.
            response = self._client.create_message(
                messages=messages,
                max_tokens=self._MAX_TOKENS,
            )
            raw = _extract_claude_text(response)
            parsed = parse_legibility_json(raw)
            latency_ms = int((time.monotonic() - start) * 1000)
            if not parsed:
                logger.warning(
                    "ClaudeLegibilityCritic: parse failed or LO-04 violation, "
                    "triggering R-6 fallback"
                )
                return self._fallback(latency_ms)
            return self._build_result(parsed, latency_ms)
        except Exception as exc:
            # R-6: broad except — API client is untrusted, any failure mode triggers fallback.
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "ClaudeLegibilityCritic R-6 fallback: %s: %s",
                type(exc).__name__, exc,
            )
            return self._fallback(latency_ms)

    def _build_result(self, parsed: dict, latency_ms: int) -> CritiqueResult:
        """Build CritiqueResult from parsed dict. Falls back on validation error."""
        try:
            overall_srs = float(parsed.get("overall_srs", 0.0))
            validate_score_range(overall_srs, "overall_srs")

            factors_raw = parsed.get("factors", {})
            if not isinstance(factors_raw, dict):
                return self._fallback(latency_ms)
            factors = {k: float(v) for k, v in factors_raw.items()}
            validate_factors(factors)
            for fname, fval in factors.items():
                validate_score_range(fval, fname)

            confidence = float(parsed.get("confidence", 0.0))
            validate_score_range(confidence, "confidence")

            suggestions = _build_suggestions(parsed.get("suggestions", []))

            return CritiqueResult(
                overall_srs=overall_srs,
                factors=factors,
                suggestions=suggestions,
                model_used="claude",
                confidence=confidence,
                latency_ms=latency_ms,
            )
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning(
                "ClaudeLegibilityCritic validation failure: %s: %s",
                type(exc).__name__, exc,
            )
            return self._fallback(latency_ms)

    def _fallback(self, latency_ms: int) -> CritiqueResult:
        """R-6 fallback: zero-value CritiqueResult with model_used='none'."""
        return CritiqueResult(
            overall_srs=0.0,
            factors={k: 0.0 for k in _REQUIRED_FACTORS},
            suggestions=(),
            model_used="none",
            confidence=0.0,
            latency_ms=latency_ms,
        )


def _extract_claude_text(response: Any) -> str:
    """Extract text content from Anthropic Message response."""
    if response is None:
        return ""
    content = getattr(response, "content", None)
    if not content:
        return ""
    try:
        return getattr(content[0], "text", "")
    except (IndexError, AttributeError):
        return ""


def _encode_image_for_claude(image: Any) -> str | None:
    """Encode a PIL image to base64 PNG for Claude's image content block.

    Returns None on any failure (R-6 will fall back).
    """
    try:
        buf = io.BytesIO()
        # PIL Image.save signature; works for real PIL images.
        # Tests pass Mock objects with .save attribute or real PIL Images.
        if hasattr(image, "save"):
            image.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        return None
    except Exception as exc:
        logger.warning("Image encoding failed: %s: %s", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# SECTION H — HybridLegibilityCritic dispatcher (D-01 R-4 gate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HybridLegibilityCritic:
    """Hybrid Gemma-primary + Claude-R-4-fallback legibility critic.

    Mirrors Phase 98-101 routing stack hybrid pattern (D-01).
    R-4 gate: if Gemma confidence < threshold OR overall_srs in uncertain_band,
    invoke Claude. R-6: on any failure, return CritiqueResult(model_used='none').

    Frozen dataclass (Phase 100 CR-01). The critic instances it holds
    (GemmaLegibilityCritic, ClaudeLegibilityCritic) are NOT frozen — they
    hold mutable pipeline/client refs. The dispatch config (thresholds, flags)
    is what's frozen.

    Attributes:
        gemma: Primary critic (Gemma 4 12B V2).
        claude: R-4 fallback critic (Claude vision).
        confidence_threshold: R-4 gate — invoke Claude if confidence below this.
        uncertain_band: R-4 gate — invoke Claude if SRS within this (lo, hi) band.
        gemma_only: Skip Claude fallback entirely (debug / fast batch scoring).
        claude_only: Skip Gemma entirely (debug / Phase 110 eval baseline).
    """

    gemma: GemmaLegibilityCritic
    claude: ClaudeLegibilityCritic
    confidence_threshold: float = 0.7  # CONTEXT D-01 default
    uncertain_band: tuple[float, float] = (0.4, 0.7)  # CONTEXT D-01 default
    gemma_only: bool = False
    claude_only: bool = False

    def critique(self, image: Any, file_path: str = "") -> CritiqueResult:
        """Dispatch critique per D-01 R-4 gate logic. NEVER raises (R-6)."""
        if self.claude_only:
            return self.claude.critique(image, file_path)

        gemma_result = self.gemma.critique(image, file_path)
        if self.gemma_only:
            return gemma_result

        if self._needs_claude_fallback(gemma_result):
            claude_result = self.claude.critique(image, file_path)
            # Only override if Claude succeeded; otherwise keep Gemma result.
            if claude_result.model_used == "claude":
                return claude_result

        return gemma_result

    def _needs_claude_fallback(self, gemma_result: CritiqueResult) -> bool:
        """R-4 gate logic per CONTEXT D-01.

        Triggers Claude when:
        - Gemma already fell back (model_used == "none")
        - Gemma confidence < confidence_threshold
        - Gemma SRS is in the uncertain band [lo, hi]
        """
        if gemma_result.model_used == "none":
            return True
        if gemma_result.confidence < self.confidence_threshold:
            return True
        lo, hi = self.uncertain_band
        if lo <= gemma_result.overall_srs <= hi:
            return True
        return False


# ---------------------------------------------------------------------------
# Shared suggestion builder (capped, sorted by severity)
# ---------------------------------------------------------------------------


def _build_suggestions(raw_suggestions: Any) -> tuple[Suggestion, ...]:
    """Build capped Suggestion tuple from raw parsed list.

    - Filters out malformed entries (missing fields, wrong types).
    - Sorts by severity rank (critical > warning > suggestion).
    - Caps at _MAX_SUGGESTIONS (10).
    """
    if not isinstance(raw_suggestions, list):
        return ()

    valid: list[Suggestion] = []
    for entry in raw_suggestions:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text", "")
        severity = entry.get("severity", "suggestion")
        category = entry.get("category", "organization")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            valid.append(Suggestion(text=text, severity=severity, category=category))
        except ValueError:
            # LO-04 violation in nested field — skip this suggestion.
            continue

    # Sort by severity rank (critical first), then preserve insertion order.
    valid.sort(key=lambda s: _SEVERITY_RANK.get(s.severity, 99))

    # Cap at _MAX_SUGGESTIONS.
    return tuple(valid[:_MAX_SUGGESTIONS])
