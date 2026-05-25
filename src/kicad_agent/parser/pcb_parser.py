"""PCB (.kicad_pcb) file parser.

Parses KiCad PCB files into kiutils Board objects with raw content preservation.
CRITICAL: kiutils drops all UUID tokens from PCB files (only handles legacy tstamp).
Raw content MUST be preserved for UUID extraction via the raw_parser or regex.

Usage:
    from kicad_agent.parser.pcb_parser import parse_pcb

    result = parse_pcb(Path("my_board.kicad_pcb"))
    footprints = result.kiutils_obj.footprints
    raw_text = result.raw_content  # Essential for UUID extraction
"""

import re
from pathlib import Path

from kiutils.board import Board

from kicad_agent.parser.types import ParseResult


def _fix_pad_net_syntax(content: str) -> str:
    """Fix pad net references that lack net numbers for kiutils compatibility.

    KiCad 10 can emit pad nets as ``(net "NETNAME")`` (without a net number)
    inside footprint pad definitions. kiutils 1.4.8 expects
    ``(net NUMBER "NETNAME")`` and crashes with IndexError on the short form.

    This pre-processor detects the short form inside pad definitions and
    injects a placeholder net number (0). The number is not meaningful for
    pad-level net refs -- the name is what matters for connectivity.

    Only matches ``(net "...")`` that appear inside ``(pad ...`` blocks
    (indented with tabs), not the board-level ``(net N "name")`` declarations.
    """
    # Match pad-level net refs: tab-indented (net "name") without a number
    # Board-level nets have the format (net N "name") at the top level
    return re.sub(
        r'^(\t{1,20}\(net )"([^"]+)"\)$',
        r'\g<1>0 "\2")',
        content,
        flags=re.MULTILINE,
    )


def parse_pcb(path: Path) -> ParseResult:
    """Parse a .kicad_pcb file into a kiutils Board object.

    Reads the file text for raw content preservation BEFORE parsing.
    This is critical because kiutils 1.4.8 drops all UUID tokens from
    PCB files -- the raw content is the only source for UUID extraction.

    Also pre-processes pad net syntax that kiutils cannot parse.

    Args:
        path: Path to a .kicad_pcb file.

    Returns:
        ParseResult with kiutils_obj as Board, raw_content as file text,
        file_type as 'pcb'.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If file extension is not .kicad_pcb.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"PCB file not found: {path}")

    if resolved.suffix != ".kicad_pcb":
        raise ValueError(f"Expected .kicad_pcb file, got {resolved.suffix}")

    raw_content = resolved.read_text(encoding="utf-8")

    # Pre-process for kiutils compatibility
    fixed_content = _fix_pad_net_syntax(raw_content)

    # Write fixed content to a temp file for kiutils parsing
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".kicad_pcb", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(fixed_content)
        tmp_path = tmp.name

    try:
        board = Board.from_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return ParseResult(
        kiutils_obj=board,
        raw_content=raw_content,
        file_path=path,
        file_type="pcb",
    )
