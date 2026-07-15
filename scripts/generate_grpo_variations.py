#!/usr/bin/env python3
"""Phase 110 Plan 03 Task 2: CLI for generating GRPO exploration data.

Walks --corpus-dir for .kicad_sch files, generates --n-variations perturbed
variations per base, scores each via the verified SRS chain, emits JSONL.

Output lands at /Volumes/Storage/models/kicad-agent/datasets/grpo/exploration.jsonl
by convention (D-02). Falls back to local disk if /Volumes/Storage unmounted.

Exit codes:
    0: success, >=1 variation row emitted
    1: no variations generated (wrong corpus dir or all-failed)
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

from volta.io.atomic_write import atomic_write  # noqa: E402
from volta.training.grpo_data_builder import (  # noqa: E402
    GRPODataBuilder,
    GRPODataBuilderError,
)
from volta.training.rewards import AlignmentJitter  # noqa: E402

logger = logging.getLogger("generate_grpo_variations")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate GRPO exploration data from KiCad schematic corpus.",
    )
    p.add_argument("--corpus-dir", required=True, type=Path,
                   help="Directory to walk recursively for base .kicad_sch files.")
    p.add_argument("--output", required=True, type=Path,
                   help="Output JSONL path. Parent dirs are created.")
    p.add_argument("--n-variations", type=int, default=8,
                   help="Variations generated per base (D-02 default: 8).")
    p.add_argument("--seed", type=int, default=42,
                   help="Base RNG seed (Phase 63 H-12 deterministic seeding).")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap on base schematics processed (smoke testing).")
    p.add_argument("--jitter-mm", type=float, default=0.1,
                   help="D-04 alignment jitter amplitude in mm.")
    p.add_argument("--variations-dir", type=Path, default=None,
                   help="Where to write variation .kicad_sch files. Default: sibling of --output.")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def _check_storage_mounted(output: Path) -> None:
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

    sch_paths = sorted(args.corpus_dir.rglob("*.kicad_sch"))
    if args.limit:
        sch_paths = sch_paths[: args.limit]
    if not sch_paths:
        print(f"ERROR: no .kicad_sch files under {args.corpus_dir}", file=sys.stderr)
        return 1

    variations_dir = args.variations_dir or (args.output.parent / "variations")
    variations_dir.mkdir(parents=True, exist_ok=True)

    builder = GRPODataBuilder(
        jitter=AlignmentJitter(amplitude_mm=args.jitter_mm),
        output_dir=variations_dir,
    )

    logger.info(
        "Generating %d variations for %d bases from %s",
        args.n_variations, len(sch_paths), args.corpus_dir,
    )
    start = time.monotonic()

    all_rows: list[str] = []
    n_errors = 0
    for base in sch_paths:
        try:
            rows = builder.build_exploration_rows(base, args.n_variations, seed=args.seed)
            all_rows.extend(rows)
        except GRPODataBuilderError as exc:
            logger.warning("skip base %s: %s", base, exc)
            n_errors += 1
        except Exception as exc:
            # Catch broad to ensure one bad base doesn't abort the full run
            logger.warning("skip base %s: %s: %s", base, type(exc).__name__, exc)
            n_errors += 1

    elapsed = time.monotonic() - start

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(all_rows) + ("\n" if all_rows else "")
    atomic_write(args.output, payload)

    print(
        f"n_bases={len(sch_paths)} "
        f"n_variations_total={len(all_rows)} "
        f"n_errors={n_errors} "
        f"elapsed_s={elapsed:.1f} "
        f"output={args.output}",
        file=sys.stderr,
    )

    if not all_rows:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
