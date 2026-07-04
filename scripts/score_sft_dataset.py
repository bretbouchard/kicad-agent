#!/usr/bin/env python3
"""Phase 110 Plan 02 Task 2: CLI for scoring a KiCad schematic corpus with SRS.

Walks --corpus-dir recursively for .kicad_sch files, scores each via the
SFTLabeller verified chain, emits one JSONL row per file to --output.

Output lands at /Volumes/Storage/models/kicad-agent/datasets/sft/srs_labels.jsonl
by convention (D-02). Falls back to local disk if /Volumes/Storage unmounted.

Exit codes:
    0: success, >=1 schematic scored
    1: no schematics scored (likely wrong corpus dir or all-failed)
    2: /Volumes/Storage not mounted (when --output points there)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Add src to path when running as a script
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from kicad_agent.io.atomic_write import atomic_write  # noqa: E402
from kicad_agent.training.sft_labeller import SFTLabeller  # noqa: E402

logger = logging.getLogger("score_sft_dataset")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Score KiCad schematic corpus with Phase 48.5 SRS for SFT data.",
    )
    p.add_argument(
        "--corpus-dir",
        required=True,
        type=Path,
        help="Directory to walk recursively for .kicad_sch files.",
    )
    p.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output JSONL path. Parent dirs are created.",
    )
    p.add_argument("--limit", type=int, default=None, help="Cap on schematics processed.")
    p.add_argument("--source-tag", default="kicad-crawler", help="Source tag in JSONL rows.")
    p.add_argument("--max-file-mb", type=int, default=50, help="Skip files larger than this (ME-110-10).")
    p.add_argument("--verbose", action="store_true", help="Debug logging.")
    return p.parse_args(argv)


def _check_storage_mounted(output: Path) -> None:
    """If output points under /Volumes/Storage, verify the volume is mounted."""
    try:
        resolved = output.resolve()
    except OSError:
        return
    if str(resolved).startswith("/Volumes/Storage"):
        if not Path("/Volumes/Storage").is_mount():
            print(
                f"ERROR: External storage not mounted at /Volumes/Storage "
                f"— mount and retry (output path: {output})",
                file=sys.stderr,
            )
            sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.corpus_dir.exists():
        print(f"ERROR: --corpus-dir {args.corpus_dir} does not exist", file=sys.stderr)
        return 1

    _check_storage_mounted(args.output)

    # Collect .kicad_sch paths
    sch_paths = sorted(args.corpus_dir.rglob("*.kicad_sch"))
    if args.limit:
        sch_paths = sch_paths[: args.limit]

    if not sch_paths:
        print(f"ERROR: no .kicad_sch files under {args.corpus_dir}", file=sys.stderr)
        return 1

    logger.info("Scoring %d schematics from %s", len(sch_paths), args.corpus_dir)
    start = time.monotonic()

    labeller = SFTLabeller(source_tag=args.source_tag, max_file_mb=args.max_file_mb)
    rows = labeller.label_corpus(sch_paths)

    elapsed = time.monotonic() - start

    # Atomic write — mkdir parents first
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(rows) + ("\n" if rows else "")
    atomic_write(args.output, payload)

    print(
        f"n_scored={labeller.stats.n_scored} "
        f"n_skipped={labeller.stats.n_skipped} "
        f"n_errors={labeller.stats.n_errors} "
        f"elapsed_s={elapsed:.1f} "
        f"output={args.output}",
        file=sys.stderr,
    )

    if labeller.stats.n_scored == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
