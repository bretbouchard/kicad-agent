#!/usr/bin/env python3
"""Re-process schematic records from training_data_merged to add spatial data.

Reads records with source_format=kicad_sch that have zero box/path counts,
extracts spatial primitives from the schematic directly (no PCB needed),
and updates spatial_summary_json and graph_json in-place.

Usage:
    python3 scripts/reprocess_schematics.py
    python3 scripts/reprocess_schematics.py --checkpoint-every 100
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [reprocess] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from volta.parser.schematic_parser import parse_schematic
from volta.ir.schematic_ir import SchematicIR
from volta.spatial.extractor import extract_schematic_all
from volta.ir.base import _clear_registry


def _build_spatial_summary(spatial_data: dict) -> str:
    """Build spatial summary JSON from extracted primitives."""
    points = spatial_data.get("points", [])
    boxes = spatial_data.get("boxes", [])
    paths = spatial_data.get("paths", [])

    all_x = []
    all_y = []
    for pt in points:
        all_x.append(pt.x)
        all_y.append(pt.y)
    for box in boxes:
        all_x.extend([box.x1, box.x2])
        all_y.extend([box.y1, box.y2])

    summary = {
        "point_count": len(points),
        "box_count": len(boxes),
        "path_count": len(paths),
        "region_count": 0,
    }
    if all_x:
        summary["min_x"] = min(all_x)
        summary["max_x"] = max(all_x)
    if all_y:
        summary["min_y"] = min(all_y)
        summary["max_y"] = max(all_y)
    summary["source"] = "schematic"

    return json.dumps(summary)


def _replace_record(split_path: Path, sample_id: int, new_rec: dict) -> None:
    """Replace a record by sample_id within a JSONL file."""
    new_line = json.dumps(new_rec, ensure_ascii=False)

    lines = split_path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        rec = json.loads(line)
        if rec.get("sample_id") == sample_id:
            lines[i] = new_line + "\n"
            break

    split_path.write_text("".join(lines), encoding="utf-8")


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="training_data_merged")
    parser.add_argument("--checkpoint-every", type=int, default=100)
    args = parser.parse_args()

    train_path = Path(args.input) / "train.jsonl"
    val_path = Path(args.input) / "val.jsonl"
    test_path = Path(args.input) / "test.jsonl"

    # Find schematic records needing re-processing
    schematic_records: list[tuple[dict, Path]] = []
    for split_path in [train_path, val_path, test_path]:
        with open(split_path) as f:
            for line in f:
                rec = json.loads(line.strip())
                if rec.get("source_format") != "kicad_sch":
                    continue
                ss = rec.get("spatial_summary_json", "{}")
                if isinstance(ss, str):
                    ss = json.loads(ss)
                if ss.get("box_count", 0) == 0 and ss.get("path_count", 0) == 0:
                    schematic_records.append((rec, split_path))

    logger.info("Found %d schematic records with zero box/path counts", len(schematic_records))

    updated = 0
    failed = 0
    start = time.time()

    for idx, (rec, split_path) in enumerate(schematic_records):
        sch_path = Path(rec["schematic_path"])

        if not sch_path.exists():
            failed += 1
            continue

        try:
            _clear_registry()
            result = parse_schematic(sch_path)
            sch_ir = SchematicIR(_parse_result=result)
            spatial = extract_schematic_all(sch_ir)

            # Update spatial summary
            new_spatial = _build_spatial_summary(spatial)

            # Update graph_json: add spatial attributes to component nodes
            graph = json.loads(rec["graph_json"])
            pin_positions = []
            try:
                pin_positions = sch_ir.get_pin_positions()
            except Exception:
                pass

            # Group pins by reference for node position updates
            ref_positions = {}
            for pin in pin_positions:
                ref = pin.get("reference", "")
                if ref:
                    ref_positions.setdefault(ref, []).append((pin["x"], pin["y"]))

            # Add x_mm, y_mm to nodes that don't have them
            for node in graph.get("nodes", []):
                nid = node.get("id", "")
                if nid in ref_positions and "x_mm" not in node:
                    positions = ref_positions[nid]
                    xs = [p[0] for p in positions]
                    ys = [p[1] for p in positions]
                    node["x_mm"] = sum(xs) / len(xs)
                    node["y_mm"] = sum(ys) / len(ys)

            # Build updated record
            updated_rec = dict(rec)
            updated_rec["spatial_summary_json"] = new_spatial
            updated_rec["graph_json"] = json.dumps(graph, sort_keys=True)

            _replace_record(split_path, rec["sample_id"], updated_rec)
            updated += 1

        except Exception as e:
            failed += 1
            if failed <= 3:
                logger.warning("Failed: %s: %s", sch_path, e)

        if (idx + 1) % args.checkpoint_every == 0:
            elapsed = time.time() - start
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            eta = (len(schematic_records) - idx - 1) / rate if rate > 0 else 0
            logger.info(
                "Progress: %d updated, %d failed | %d/%d | %.1f/s, ETA %.0f min",
                updated, failed, idx + 1, len(schematic_records),
                rate, eta / 60,
            )

    elapsed = time.time() - start
    logger.info("Done: %d updated, %d failed in %.1f min", updated, failed, elapsed / 60)


if __name__ == "__main__":
    main()
