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

    return sexpdata.loads(content)  # type: ignore[no-any-return]


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
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    content = path.read_text(encoding="utf-8")
    return parse_raw_sexp(content)
