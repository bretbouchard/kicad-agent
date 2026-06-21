"""Auto-route pipeline handler: chains Freerouting + cleanup into one operation.

Implements ae-23 auto_route_freerouting as a full pipeline:
  DSN export -> Freerouting headless route -> SES import -> strip_shorts -> remove_dangling_tracks

Consolidates the 5-script manual pipeline into a single kicad-agent operation.
Cleanup stages are best-effort -- routing is the critical path.
"""

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_AUTO_ROUTE_HANDLERS: dict[str, Callable] = {}


def register_auto_route(op_type: str) -> Callable:
    """Decorator to register an auto-route operation handler."""
    def decorator(fn: Callable) -> Callable:
        _AUTO_ROUTE_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_auto_route("auto_route_freerouting")
def _handle_auto_route_freerouting(
    op: Any,
    ir: Any,
    file_path: Path,
) -> dict[str, Any]:
    """Full auto-route pipeline: DSN export -> Freerouting -> SES import -> cleanup.

    Executes in sequence:
    1. Export DSN from PCB
    2. Run Freerouting headless batch auto-router
    3. Import SES routing result into PCB
    4. Strip shorting segments (optional, default on)
    5. Remove dangling tracks/vias (optional, default on)

    Cleanup stages are best-effort: if they fail, a warning is logged but
    the pipeline still returns success with the routing results. Only the
    routing stage itself is a hard failure.

    Args:
        op: AutoRouteFreeroutingOp with target_file, passes, cleanup_shorts,
            cleanup_dangling.
        ir: PcbIR providing raw PCB text and commit_raw_content.
        file_path: Resolved path to the .kicad_pcb file.

    Returns:
        Dict with routes_added, vias_added, unrouted, shorts_stripped,
        dangling_removed, strategy, ses_path, dsn_path.
    """
    from kicad_agent.routing.freerouting import (
        route_with_freerouting,
        import_ses_into_pcb,
    )

    stats: dict[str, Any] = {}
    passes = getattr(op, "passes", 25)

    # --- Stage 1-2: Export DSN and run Freerouting ---
    logger.info("Stage 1-2: Routing with Freerouting (%d passes)", passes)
    fr_result = route_with_freerouting(
        file_path,
        max_passes=passes,
    )

    if not fr_result.success:
        return {
            "error": f"Freerouting failed: {fr_result.stderr}",
            "stage": "routing",
            "strategy": "freerouting",
            "routes_added": 0,
            "vias_added": 0,
            "unrouted": 0,
            "shorts_stripped": 0,
            "dangling_removed": 0,
        }

    logger.info(
        "Freerouting completed. DSN: %s, SES: %s",
        fr_result.dsn_path,
        fr_result.ses_path,
    )

    # --- Stage 3: Import SES into PCB ---
    logger.info("Stage 3: Importing SES into PCB")
    pcb_content = ir.raw_content if ir.raw_content else file_path.read_text()
    new_content, import_stats = import_ses_into_pcb(
        fr_result.ses_path, pcb_content,
    )
    ir.commit_raw_content(new_content)

    stats.update({
        "routes_added": import_stats.get("segments", 0),
        "vias_added": import_stats.get("vias", 0),
        "unrouted": import_stats.get("skipped", 0),
        "ses_path": str(fr_result.ses_path),
        "dsn_path": str(fr_result.dsn_path),
    })
    logger.info(
        "Import complete: %d segments, %d vias, %d unrouted",
        stats["routes_added"], stats["vias_added"], stats["unrouted"],
    )

    # --- Stage 4: Strip shorts (best-effort) ---
    # TODO(M-4): Each cleanup stage re-runs kicad-cli pcb drc independently.
    # Consider caching the DRC report between strip_shorts and
    # remove_dangling_tracks to avoid redundant subprocess invocations.
    cleanup_shorts = getattr(op, "cleanup_shorts", True)
    if cleanup_shorts:
        logger.info("Stage 4: Stripping shorts")
        try:
            from kicad_agent.ops.handlers.pcb_cleanup import _do_strip_shorts

            short_stats = _do_strip_shorts(file_path, ir, tolerance_mm=0.01)
            stats["shorts_stripped"] = short_stats.get("removed", 0)
            if not short_stats.get("success", False):
                logger.warning(
                    "strip_shorts failed (non-fatal): %s",
                    short_stats.get("error", "unknown"),
                )
                stats["shorts_stripped"] = 0
                stats["cleanup_shorts_error"] = short_stats.get("error", "unknown")
        except Exception as exc:
            logger.warning("strip_shorts raised exception (non-fatal): %s", exc)
            stats["shorts_stripped"] = 0
            stats["cleanup_shorts_error"] = str(exc)
    else:
        stats["shorts_stripped"] = 0

    # --- Stage 5: Remove dangling tracks (best-effort) ---
    cleanup_dangling = getattr(op, "cleanup_dangling", True)
    if cleanup_dangling:
        logger.info("Stage 5: Removing dangling tracks")
        try:
            from kicad_agent.ops.handlers.pcb_cleanup import _do_remove_dangling

            dangling_stats = _do_remove_dangling(
                file_path, ir, max_iterations=30, tolerance_mm=0.001,
            )
            stats["dangling_removed"] = dangling_stats.get("tracks_removed", 0)
            if not dangling_stats.get("success", False):
                logger.warning(
                    "remove_dangling_tracks failed (non-fatal): %s",
                    dangling_stats.get("error", "unknown"),
                )
                stats["dangling_removed"] = 0
                stats["cleanup_dangling_error"] = dangling_stats.get("error", "unknown")
        except Exception as exc:
            logger.warning(
                "remove_dangling_tracks raised exception (non-fatal): %s", exc,
            )
            stats["dangling_removed"] = 0
            stats["cleanup_dangling_error"] = str(exc)
    else:
        stats["dangling_removed"] = 0

    stats["strategy"] = "freerouting"
    return stats
