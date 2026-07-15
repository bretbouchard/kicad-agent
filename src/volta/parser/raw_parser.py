"""Raw S-expression fallback parser using sexpdata.

This module provides a fallback parser for KiCad file constructs that kiutils
cannot handle. It uses the sexpdata library to parse arbitrary S-expressions
into nested Python lists.

Primary use cases:
- Parsing unknown or future KiCad tokens that kiutils hasn't adopted yet
- Extracting UUID tokens from PCB/footprint files (kiutils drops these)
- Debugging raw S-expression content

For structured parsing, prefer the typed parsers (schematic_parser, pcb_parser,
symbol_parser, footprint_parser) which return rich dataclass objects.
"""

from pathlib import Path

import sexpdata

# Maximum S-expression nesting depth (P-BUG-001: depth pre-scan)
_MAX_SEXP_DEPTH = 200


def _pre_scan_depth(content: str, max_depth: int = _MAX_SEXP_DEPTH) -> int:
    """Count maximum parenthesis nesting depth in O(n) without parsing.

    P-BUG-001: Prevents RecursionError from sexpdata.loads() on deeply
    nested content. CPython's RecursionError is unsafe to catch -- it can
    leave the interpreter in an inconsistent state. This O(n) scan rejects
    malicious content BEFORE sexpdata touches it.

    Args:
        content: Raw S-expression text.
        max_depth: Maximum allowed nesting depth.

    Returns:
        Maximum nesting depth found.

    Raises:
        ValueError: If nesting depth exceeds max_depth.
    """
    depth = 0
    max_found = 0
    in_string = False
    escape_next = False

    for char in content:
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "(":
            depth += 1
            if depth > max_found:
                max_found = depth
            if depth > max_depth:
                raise ValueError(
                    f"S-expression nesting depth {depth} exceeds maximum "
                    f"allowed depth of {max_depth}. Content may be malformed "
                    "or maliciously nested."
                )
        elif char == ")":
            if depth > 0:
                depth -= 1

    return max_found


def parse_raw_sexp(content: str) -> list:
    """Parse raw S-expression string into a nested Python list.

    This is the fallback parser for constructs that kiutils cannot handle.
    Use it for unknown tokens, UUID extraction, or debugging raw file content.

    Args:
        content: Raw S-expression string content from a KiCad file.

    Returns:
        Nested list structure representing the parsed S-expression.

    Raises:
        ValueError: If content is empty or exceeds 50MB size limit.
        sexpdata.ExpectCloseBracket: If S-expression syntax is malformed.
    """
    if not content:
        raise ValueError("Cannot parse empty S-expression content")

    max_size = 50 * 1024 * 1024  # 50MB limit (T-01-01: DoS mitigation)
    if len(content) > max_size:
        raise ValueError(
            f"Content exceeds 50MB size limit ({len(content)} bytes). "
            "File may be malformed or maliciously large."
        )

    # P-BUG-001: Depth pre-scan BEFORE sexpdata.loads() to prevent
    # RecursionError from leaving the interpreter in an inconsistent state.
    _pre_scan_depth(content)

    try:
        return sexpdata.loads(content)  # type: ignore[no-any-return]
    except RecursionError:
        raise ValueError(
            "S-expression nesting depth exceeded interpreter recursion limit. "
            "File may be malformed or maliciously nested."
        )


def parse_raw_sexp_file(path: Path) -> list:
    """Read a KiCad file and parse its S-expression content.

    Convenience function that reads the file and passes content to parse_raw_sexp.

    Args:
        path: Path to a KiCad file to parse.

    Returns:
        Nested list structure representing the parsed S-expression.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If content is empty or exceeds size limit.
        sexpdata.ExpectCloseBracket: If S-expression syntax is malformed.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")

    # Check file size before reading into memory (T-01-01: DoS mitigation)
    max_size = 50 * 1024 * 1024  # 50MB
    file_size = resolved.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"File exceeds 50MB size limit ({file_size} bytes). "
            "File may be malformed or maliciously large."
        )

    content = resolved.read_text(encoding="utf-8")
    return parse_raw_sexp(content)
