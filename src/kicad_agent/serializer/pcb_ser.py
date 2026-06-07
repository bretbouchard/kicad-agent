"""PCB (.kicad_pcb) file serializer with UUID re-injection.

Serializes parsed KiCad PCB files back to disk. Writes via a temp file,
normalizes the output, and re-injects UUIDs that kiutils drops during
serialization. Uses atomic_write for crash safety (S-BUG-001).

Usage:
    from kicad_agent.serializer.pcb_ser import serialize_pcb

    output_path = serialize_pcb(parse_result, Path("output.kicad_pcb"), uuid_map=uuid_map)
"""

import tempfile
from pathlib import Path
from typing import Optional

from kicad_agent.io.atomic_write import atomic_write
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap
from kicad_agent.serializer.normalizer import normalize_kicad_output
from kicad_agent.serializer.uuid_reinjector import reinject_uuids


def serialize_pcb(
    parse_result: ParseResult,
    output_path: Path,
    uuid_map: Optional[UUIDMap] = None,
) -> Path:
    """Serialize a parsed PCB back to a .kicad_pcb file.

    Uses kiutils' to_file() to serialize to a temporary file, then reads
    the content back for normalization and UUID re-injection. The final
    output is written via atomic_write for crash safety (S-BUG-001).

    This avoids leaving a corrupted file on disk if kiutils to_file()
    produces malformed output -- the temp file is discarded after reading.

    Args:
        parse_result: ParseResult from parse_pcb().
        output_path: Target file path for the serialized PCB.
        uuid_map: Optional UUIDMap for re-injecting dropped UUIDs.

    Returns:
        The output path (same as input output_path).
    """
    if parse_result.file_type != "pcb":
        raise ValueError(
            f"Expected file_type='pcb', got file_type={parse_result.file_type!r}"
        )

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file via kiutils, then read back for post-processing.
    # This avoids leaving a corrupted file on disk if to_file() produces
    # malformed output (S-BUG-001).
    fd, tmp_path = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=".kicad_pcb_",
        suffix=".tmp",
    )
    try:
        import os
        os.close(fd)
        parse_result.kiutils_obj.to_file(tmp_path)
        serialized = Path(tmp_path).read_text(encoding="utf-8")
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass

    # Normalize kiutils output to match KiCad-native format
    content = normalize_kicad_output(serialized)

    # Re-inject UUIDs that kiutils dropped
    if uuid_map is not None and uuid_map.entries:
        content = reinject_uuids(content, uuid_map)

    # Atomic write for crash safety
    atomic_write(output_path, content)

    return output_path
