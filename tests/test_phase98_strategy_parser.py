"""Phase 98 Task 2: Defensive JSON extractor from free-text model output (R-2).

The Gemma 4 12B V2 adapter was trained on free-text, so it may emit JSON in
markdown fences, with preambles, with trailing prose, or malformed. The parser
MUST handle all of these and never raise — returning {} on total failure
triggers the R-6 fallback path in Plan 98-02.
"""

from __future__ import annotations

import time

from volta.routing.strategy_parser import _extract_brace_spans, parse_strategy_json


class TestBareJson:
    def test_bare_json_object_returns_dict(self) -> None:
        result = parse_strategy_json('{"net_priorities": ["GND"]}')
        assert isinstance(result, dict)
        assert "net_priorities" in result


class TestFencedJson:
    def test_markdown_fenced_json_returns_dict(self) -> None:
        raw = '```json\n{"net_priorities": ["GND"]}\n```'
        result = parse_strategy_json(raw)
        assert isinstance(result, dict)
        assert "net_priorities" in result


class TestPreamble:
    def test_natural_language_preamble_returns_dict(self) -> None:
        raw = 'Here is the strategy:\n{"net_priorities": ["GND"]}'
        result = parse_strategy_json(raw)
        assert isinstance(result, dict)
        assert result.get("net_priorities") == ["GND"]


class TestTrailingProse:
    def test_trailing_prose_returns_dict(self) -> None:
        raw = '{"net_priorities": ["GND"]}\nThat is my plan.'
        result = parse_strategy_json(raw)
        assert isinstance(result, dict)
        assert result.get("net_priorities") == ["GND"]


class TestEmptyAndMalformed:
    def test_empty_string_returns_empty_dict(self) -> None:
        assert parse_strategy_json("") == {}

    def test_whitespace_only_returns_empty_dict(self) -> None:
        assert parse_strategy_json("   \n\t  ") == {}

    def test_no_json_present_returns_empty_dict(self) -> None:
        assert parse_strategy_json("just words, no json here") == {}

    def test_truncated_json_returns_empty_dict(self) -> None:
        # Truncated object — json.loads will fail
        assert parse_strategy_json('{"net_priorities": ["GND"') == {}


class TestMultipleObjectsLargestWins:
    def test_returns_largest_json_object(self) -> None:
        # Strategy object (5 fields) vs tiny metadata fragment
        raw = (
            'Note: {"id": 1}\n'
            'Here:\n'
            '{"net_priorities": ["GND"], "layer_hints": {}, "keepouts": [], '
            '"router_assignment": {}, "routing_notes": "x"}'
        )
        result = parse_strategy_json(raw)
        assert "net_priorities" in result
        assert "router_assignment" in result


class TestNestedBraces:
    def test_nested_braces_in_string_values_handled(self) -> None:
        raw = '{"keepouts": [{"reason": "zone {0}"}]}'
        result = parse_strategy_json(raw)
        assert isinstance(result, dict)
        keepouts = result.get("keepouts")
        assert isinstance(keepouts, list)
        assert len(keepouts) == 1
        assert keepouts[0]["reason"] == "zone {0}"


class TestExtractBraceSpansPerformance:
    """IN-02 (Council): _extract_brace_spans must be O(n), not O(n^2).

    The previous implementation re-scanned from start+1 when a brace span
    failed to close, giving quadratic worst-case on deeply nested unclosed
    input. The single-pass stack version must handle 100k unclosed braces
    in well under a second.
    """

    def test_extract_spans_balanced(self) -> None:
        spans = _extract_brace_spans('pre {"a": 1} mid {"b": 2} post')
        assert len(spans) == 2
        assert spans[0] == '{"a": 1}'
        assert spans[1] == '{"b": 2}'

    def test_extract_spans_unclosed_returns_empty(self) -> None:
        spans = _extract_brace_spans("{no close here")
        assert spans == []

    def test_extract_spans_ignores_braces_inside_strings(self) -> None:
        spans = _extract_brace_spans('{"reason": "zone {0}"}')
        assert spans == ['{"reason": "zone {0}"}']

    def test_deeply_nested_unclosed_does_not_re_scan_quadratically(self) -> None:
        """100k unclosed braces must complete in under 2 seconds (O(n) check).

        A regression to the old O(n^2) algorithm would take minutes on this input.
        """
        hostile = "{" * 100_000
        start = time.monotonic()
        spans = _extract_brace_spans(hostile)
        elapsed = time.monotonic() - start
        assert spans == []  # all unclosed -> no complete spans
        assert elapsed < 2.0, f"O(n) check failed: took {elapsed:.2f}s"
