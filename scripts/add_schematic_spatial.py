#!/usr/bin/env python3
"""Add spatial extraction to schematic-only records in training_data_merged.

Reads each record, checks if spatial data is missing, parses the schematic file,
extracts spatial primitives, and updates the spatial_summary_json field.

Usage:
    python3 scripts/add_schematic_spatial.py
    python3 scripts/add_schematic_spatial.py --dry-run
"""

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [add_spatial] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.parser import parse_schematic
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.spatial.extractor import extract_schematic_all
from kicad_agent.training.graph_builder import _build_spatial_summary


def needs_spatial(record: dict) -> bool:
    """Check if a record is missing spatial data."""
    ss = record.get("spatial_summary_json", "{}")
    if isinstance(ss, str):
        try:
            ss = json.loads(ss)
        except json.JSONDecodeError:
            return True
    return ss.get("box_count", 0) == 0 and ss.get("path_count", 0) == 0


def add_spatial_to_record(record: dict) -> bool:
    """Add spatial data to a record by parsing its schematic file.

    Returns True if spatial data was successfully added.
    """
    sch_path = record.get("schematic_path", "")
    if not sch_path:
        return False

    path = Path(sch_path)
    if not path.exists():
        logger.debug("Schematic not found: %s", sch_path)
        return False

    try:
        result = parse_schematic(path)
        sch_ir = SchematicIR(_parse_result=result)
        spatial_data = extract_schematic_all(sch_ir)

        # Update spatial summary
        new_summary = _build_spatial_summary(spatial_data)
        record["spatial_summary_json"] = new_summary

        return True
    except Exception as e:
        logger.debug("Failed to extract spatial from %s: %s", sch_path, e)
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Add spatial data to schematic records")
    parser.add_argument("--dry-run", action="store_true", help="Count records needing update")
    parser.add_argument("--input", type=Path, default=Path("training_data_merged"))
    args = parser.parse_args()

    total_updated = 0
    total_failed = 0
    total_skipped = 0

    for split in ["train", "val", "test"]:
        input_path = args.input / f"{split}.jsonl"
        if not input_path.exists():
            continue

        if args.dry_run:
            count = 0
            need = 0
            with open(input_path) as f:
                for line in f:
                    count += 1
                    if needs_spatial(json.loads(line)):
                        need += 1
            logger.info("  %s: %d of %d records need spatial data", split, need, count)
            continue

        # Stream: read, update, write to temp file
        tmp_path = input_path.with_suffix(".tmp.jsonl")
        updated = 0
        skipped = 0
        with open(input_path) as fin, open(tmp_path, "w") as fout:
            for i, line in enumerate(fin):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    fout.write(line + "\n")
                    continue

                if needs_spatial(record):
                    if add_spatial_to_record(record):
                        updated += 1
                    else:
                        total_failed += 1
                else:
                    skipped += 1
                    total_skipped += 1

                fout.write(json.dumps(record, ensure_ascii=False) + "\n")

                if (i + 1) % 500 == 0:
                    logger.info("  Progress: %d processed", i + 1)

        # Atomic replace
        tmp_path.replace(input_path)
        logger.info(
            "  %s: %d updated, %d skipped, %d failed",
            split, updated, skipped, total_failed,
        )
        total_updated += updated

    if args.dry_run:
        logger.info("Dry run complete")
    else:
        logger.info("Done: %d records updated with spatial data", total_updated)


if __name__ == "__main__":
    main()
