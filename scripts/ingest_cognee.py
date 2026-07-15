#!/usr/bin/env python3
"""Ingest KiCad reference documents into Cognee knowledge graph.

Reads docs/*.md and outputs JSON MCP command payloads for Cognee
ingestion. Pipe the output to Claude Code or save to a file for
manual execution.

Usage:
    python scripts/ingest_cognee.py                  # Print JSON to stdout
    python scripts/ingest_cognee.py --output cmds.json  # Write to file
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_NAME = "kicad-agent-reference"

DOC_FILES = [
    "volta_reference.md",
    "pcb_editor_reference.md",
    "gerbview_reference.md",
    "kicad_docs.md",
]

# Verification queries with expected content indicators
VERIFICATION_QUERIES = [
    ("pin at coordinate", "volta_reference"),
    ("grid snap schematic", "volta_reference"),
    ("working with footprints", "pcb_editor_reference"),
    ("copper zones", "pcb_editor_reference"),
    ("Gerber", "gerbview_reference"),
    ("Schematic Editor", "kicad_docs"),
]

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def ingest_doc(doc_name: str, content: str) -> dict[str, object]:
    """Build a JSON-serializable dict representing one Cognee MCP remember call.

    This is a PURE function -- it does NOT call any MCP tool.

    Args:
        doc_name: Filename of the source document (used as label).
        content: Full text content of the document.

    Returns:
        Dict with keys: tool, data, dataset_name.

    Raises:
        ValueError: If content is empty or whitespace-only.
    """
    stripped = content.strip()
    if not stripped:
        raise ValueError(f"Content for {doc_name} is empty")

    return {
        "tool": "remember",
        "data": f"[Source: {doc_name}]\n\n{stripped}",
        "dataset_name": DATASET_NAME,
    }


def verify_ingestion() -> list[dict[str, object]]:
    """Build JSON-serializable dicts for Cognee MCP recall verification calls.

    This is a PURE function -- it does NOT call any MCP tool.

    Returns:
        List of dicts, one per verification query, with keys: tool, query, datasets.
    """
    return [
        {
            "tool": "recall",
            "query": query,
            "datasets": [DATASET_NAME],
        }
        for query, _source in VERIFICATION_QUERIES
    ]


def main(argv: list[str] | None = None) -> int:
    """Run Cognee ingestion payload generation.

    Reads all DOC_FILES from ROOT/docs/, generates JSON MCP payloads, and
    writes them as JSONL (one JSON object per line) to stdout or to a file.

    Args:
        argv: Command-line arguments. None means no arguments (used by tests).
              Pass sys.argv[1:] from __main__ for CLI usage.

    Returns:
        0 if all docs processed successfully.
        1 if some docs failed (partial failure).
        2 if import/setup error occurred.
    """
    parser = argparse.ArgumentParser(
        description="Generate JSON MCP payloads for Cognee ingestion of KiCad reference docs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSONL to this file instead of stdout.",
    )
    args = parser.parse_args(argv if argv is not None else [])

    docs_dir = ROOT / "docs"
    payloads: list[dict[str, object]] = []
    ready_count = 0
    failed_count = 0

    for doc_name in DOC_FILES:
        doc_path = docs_dir / doc_name
        if not doc_path.exists():
            logger.warning("Doc not found: %s", doc_path)
            failed_count += 1
            continue
        try:
            content = doc_path.read_text(encoding="utf-8")
            payload = ingest_doc(doc_name, content)
            payloads.append(payload)
            ready_count += 1
            logger.info("Ready: %s", doc_name)
        except ValueError as exc:
            logger.warning("Failed: %s -- %s", doc_name, exc)
            failed_count += 1
        except Exception as exc:
            logger.error("Failed: %s -- %s", doc_name, exc)
            failed_count += 1

    # Append verification queries
    verification = verify_ingestion()
    payloads.extend(verification)

    # Write output
    output_text = "\n".join(json.dumps(p) for p in payloads) + "\n" if payloads else ""

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        sys.stdout.write(output_text)

    # Summary to stderr
    print(
        f"Prepared {ready_count}/{len(DOC_FILES)} ingestion payloads + {len(verification)} verification queries",
        file=sys.stderr,
    )

    if failed_count == 0:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
