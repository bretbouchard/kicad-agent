"""Phase 98 R-2: Defensive JSON extractor from free-text model output.

The Gemma 4 12B V2 adapter was trained on free-text PCB analysis. When asked
for JSON, it may emit: bare JSON, markdown-fenced JSON, JSON with natural
language preambles, JSON with trailing prose, partial/truncated JSON, or
multiple JSON fragments.

This parser tries a sequence of extraction strategies in priority order and
NEVER raises — returning {} on total failure. The caller treats {} as a
signal to trigger the R-6 deterministic fallback (Plan 98-02).

Algorithm (per RESEARCH.md Pattern 2):
1. Strip + empty check
2. Try direct json.loads
3. Try markdown fences (```json ... ```)
4. Brace-match outermost spans, keep the largest parseable dict
5. Fallback to {}
"""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_strategy_json(raw: str) -> dict:
    """Extract a strategy dict from raw model output.

    Args:
        raw: Raw text from the vision model (may be fenced, prefixed, malformed).

    Returns:
        Parsed dict on success, {} on any failure. NEVER raises.
    """
    if not raw:
        return {}
    stripped = raw.strip()
    if not stripped:
        return {}

    # 1. Try direct json.loads (ideal case — bare JSON)
    candidate = _try_parse(stripped)
    if isinstance(candidate, dict):
        return candidate

    # 2. Extract from markdown fences
    for match in _FENCE_RE.finditer(stripped):
        candidate = _try_parse(match.group(1))
        if isinstance(candidate, dict):
            return candidate

    # 3. Find all brace-matched spans; keep the largest parseable dict
    spans = _extract_brace_spans(stripped)
    best: dict | None = None
    best_key_count = -1
    for span in spans:
        candidate = _try_parse(span)
        if isinstance(candidate, dict):
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


def _extract_brace_spans(text: str) -> list[str]:
    """Extract all top-level brace-balanced spans from text.

    Tracks brace depth accounting for string literals (so braces inside JSON
    string values do not confuse the matcher).

    IN-02 (Council): single-pass O(n) implementation using a stack of open-brace
    positions. The previous implementation re-scanned from ``start + 1`` when a
    span failed to close, giving O(n^2) worst-case on deeply nested input with
    no matching close. This version visits each character exactly once.
    """
    spans: list[str] = []
    # Stack of open-brace indices that are at depth 0 (top-level span starts).
    # Nested opens are tracked via depth but only depth-0 starts are recorded.
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
