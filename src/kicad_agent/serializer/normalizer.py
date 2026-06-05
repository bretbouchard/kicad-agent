"""Post-process kiutils output to match KiCad-native format.

After kiutils to_file() serialization, run a normalization pass that fixes
property ordering, whitespace, quoting, and token formatting to match
KiCad's native output (D-11 through D-14).

IMPORTANT: Each rule must preserve two-pass round-trip stability.
If pass1 != pass2 after adding a rule, the rule breaks determinism (Pitfall 3).

The normalizer architecture supports incremental rule addition without
breaking existing rules. Phase 2 implements deterministic serialization
(D-12, D-13) with scientific notation fix and whitespace normalization.
Full byte-identical output (D-14) and KiCad-native property ordering
(D-11) require deeper kiutils fixes in later phases.

Usage:
    from kicad_agent.serializer.normalizer import normalize_kicad_output

    normalized = normalize_kicad_output(kiutils_output)
"""

import logging
import re

logger = logging.getLogger(__name__)

# Scientific notation pattern that avoids matching inside quoted strings.
# Applied only to unquoted segments after string-aware tokenization.
# Requires decimal point in mantissa (e.g. 1.5e-07) to avoid matching
# hex digits in UUID tokens like 000000e95976 (Verifier gap fix).
_SCI_NOTATION = re.compile(r'(?<![a-zA-Z_"(])([-+]?\d+\.\d+)[eE]([-+]?\d+)')

# Pattern matching (at X Y) with exactly 2 numeric values — no third value.
# Negative Y values are common in KiCad (origin at top-left).
_AT_TWO_VAL = re.compile(
    r'\(at\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)'
)

# Elements that natively omit angle from (at X Y) in KiCad format.
_EXCLUDE_AT_TOKENS = ('junction', 'no_connect')


def normalize_kicad_output(content: str) -> str:
    """Post-process kiutils output to match KiCad-native format.

    Applies normalization rules in order:
    1. Fix scientific notation (Pitfall 13) -- e.g. 1.5e-07 -> 0.0000002
    2. Fix missing angle in (at X Y) (Bug #29) -- e.g. (at 10 20) -> (at 10 20 0)
    3. Normalize whitespace to spaces with consistent indentation (D-12)

    IMPORTANT: Each rule must preserve two-pass round-trip stability.
    If pass1 != pass2 after adding a rule, the rule breaks determinism (Pitfall 3).

    Args:
        content: Serialized S-expression string from kiutils.

    Returns:
        Normalized content string.
    """
    content = _fix_generator_quoting(content)
    content = _remove_generator_version(content)
    content = _fix_scientific_notation(content)
    content = _fix_at_angle(content)
    content = _normalize_whitespace(content)
    return content


def _fix_generator_quoting(content: str) -> str:
    """Fix kiutils quoting the generator token (Pitfall: ERC parse failure).

    kiutils outputs ``(generator "eeschema")`` but KiCad 10 expects
    ``(generator eeschema)`` (unquoted). kicad-cli ERC fails to load
    schematics with quoted generator.
    """
    content = content.replace('(generator "eeschema")', '(generator eeschema)')
    content = content.replace('(generator "kiutils")', '(generator eeschema)')
    return content


def _remove_generator_version(content: str) -> str:
    """Remove kiutils-injected generator_version line.

    kiutils adds ``(generator_version "10.0")`` which does not appear in
    native KiCad files. Harmless but unnecessary.
    """
    return re.sub(r'^\s*\(generator_version\s+"[^"]*"\)\n', '', content, flags=re.MULTILINE)


def _fix_scientific_notation(content: str) -> str:
    """Replace scientific notation floats with fixed-point (D-14, Pitfall 13).

    kiutils may output coordinates in scientific notation (e.g. 1.5e-07)
    while KiCad uses fixed-point. This normalizes all scientific notation
    to 6 decimal places, matching KiCad's precision.

    Council M-01: String-aware parsing. S-expression content may contain
    quoted strings with text that looks like scientific notation (e.g.
    property values). This function tokenizes the content to skip quoted
    strings before applying the regex replacement.

    Approach: Split content into quoted and unquoted segments using a
    state machine, apply regex only to unquoted segments, rejoin.
    """

    def _replace_sci(match: re.Match) -> str:
        mantissa = match.group(1)
        exponent = match.group(2)
        value = float(f"{mantissa}e{exponent}")
        return f"{value:.6f}"

    # Council M-01: String-aware tokenization
    result_parts = []
    i = 0
    while i < len(content):
        if content[i] == '"':
            # Find end of quoted string (handle escaped quotes)
            j = i + 1
            while j < len(content):
                if content[j] == '\\' and j + 1 < len(content):
                    j += 2  # Skip escaped character
                elif content[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            # Append quoted string unchanged
            result_parts.append(content[i:j])
            i = j
        else:
            # Find next quote or end of content
            j = content.find('"', i)
            if j == -1:
                j = len(content)
            # Apply sci-notation fix only to unquoted segment
            segment = content[i:j]
            result_parts.append(_SCI_NOTATION.sub(_replace_sci, segment))
            i = j
    return "".join(result_parts)


def _fix_at_angle(content: str) -> str:
    """Add missing rotation angle to (at X Y) position elements (Bug #29).

    kiutils omits the angle when it is 0, producing ``(at X Y)`` instead of
    the required ``(at X Y 0)``.  KiCad 10 requires 3 coordinate values for
    most position elements (properties, labels, power symbols).  However,
    some elements natively omit the angle — these are excluded.

    Exclusions (native KiCad format without angle):
    - ``(junction (at X Y))`` — junctions never have an angle
    - ``(no_connect (at X Y))`` — no-connect markers never have an angle
    - ``(symbol ... (at X Y) (unit ...`` — non-power symbols at 0 deg

    Uses a two-pass approach: first pass identifies exclusion spans in the
    raw content (before quote splitting), second pass applies replacements
    only to non-excluded spans. This handles quoted strings correctly.
    """
    # Pass 1: Find all (at X Y) spans that should be excluded.
    excluded_spans: list[tuple[int, int]] = []

    for m in _AT_TWO_VAL.finditer(content):
        # Check junction / no_connect in line prefix
        line_start = content.rfind('\n', 0, m.start()) + 1
        prefix = content[line_start:m.start()]
        is_excluded = False
        for token in _EXCLUDE_AT_TOKENS:
            if f'({token} ' in prefix or f'({token}\t' in prefix:
                is_excluded = True
                break
        if is_excluded:
            excluded_spans.append((m.start(), m.end()))
            continue

        # Check symbol context: (symbol ... (at X Y) (unit/mirror ...
        # Scan backward for (symbol (skipping quoted strings)
        before = content[:m.start()]
        if _token_present_outside_quotes(before, '(symbol'):
            after = content[m.end():]
            window = after[:200]
            if _token_present_outside_quotes(window, '(unit') or _token_present_outside_quotes(window, '(mirror'):
                excluded_spans.append((m.start(), m.end()))

    # Pass 2: String-aware replacement, skipping excluded spans.
    result_parts: list[str] = []
    i = 0
    while i < len(content):
        if content[i] == '"':
            j = i + 1
            while j < len(content):
                if content[j] == '\\' and j + 1 < len(content):
                    j += 2
                elif content[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            result_parts.append(content[i:j])
            i = j
        else:
            j = content.find('"', i)
            if j == -1:
                j = len(content)
            segment = content[i:j]

            def _replace_at(
                match: re.Match, _seg: str = segment, _offset: int = i
            ) -> str:
                abs_start = _offset + match.start()
                abs_end = _offset + match.end()
                for exc_start, exc_end in excluded_spans:
                    if abs_start == exc_start and abs_end == exc_end:
                        return match.group(0)
                return f'(at {match.group(1)} {match.group(2)} 0)'

            segment = _AT_TWO_VAL.sub(_replace_at, segment)
            result_parts.append(segment)
            i = j
    return "".join(result_parts)


def _token_present_outside_quotes(text: str, token: str) -> bool:
    """Check if a token appears in text outside quoted strings."""
    i = 0
    while i < len(text):
        if text[i] == '"':
            j = i + 1
            while j < len(text):
                if text[j] == '\\' and j + 1 < len(text):
                    j += 2
                elif text[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            i = j
        else:
            j = text.find('"', i)
            if j == -1:
                j = len(text)
            if token in text[i:j]:
                return True
            i = j
    return False


def _normalize_whitespace(content: str) -> str:
    """Normalize whitespace to spaces with consistent indentation (D-12).

    KiCad uses spaces (not tabs) for indentation. kiutils may produce
    tabs in some contexts. This normalizes all tabs to spaces.

    Does NOT change indentation depth -- kiutils' indentation is already
    close to KiCad's. Only converts tabs to spaces.
    """
    # Replace tabs with spaces (KiCad uses spaces exclusively)
    content = content.replace("\t", "    ")
    return content
