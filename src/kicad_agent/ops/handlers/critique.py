"""Handler for the critique_sch operation — AI legibility critic (read-only).

D-04: separate op, decoupled from auto_layout_sch. Routes through
execute_schematic_query (no Transaction, no serialize) — file mtime
unchanged.

Flow:
1. Render schematic to PDF via kicad-cli sch export pdf (mirror Phase 48.5)
2. Convert PDF to PIL image (lazy import: pdf2image if available)
3. Construct HybridLegibilityCritic with lazy model loading
4. Dispatch critique, return CritiqueResult dict
5. Wrap entire body in try/except → return fallback dict (R-6, NEVER raises)

Model loading discipline (Phase 98-03 STATE.md decision):
- Gemma model load (23.8 GB) only when op.claude_only == False
- Claude client construction only when op.gemma_only == False
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kicad_agent.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)


def handle_critique_sch(
    op: Any,
    ir: "SchematicIR",
    file_path: Path,
) -> dict[str, Any]:
    """Handle critique_sch operation — AI legibility critic (read-only).

    Mirrors _handle_review_schematic pattern but emits CritiqueResult from
    HybridLegibilityCritic instead of SchematicReadabilityScorer output.

    D-04: separate op, decoupled from auto_layout_sch. R-6: NEVER raises;
    on any failure returns dict with model_used='none', confidence=0.0.

    Args:
        op: CritiqueSchOp with target_file, gemma_only, claude_only,
            include_suggestions fields.
        ir: Parsed SchematicIR (unused — critic operates on rendered image).
        file_path: Resolved path to the target schematic file.

    Returns:
        Dict with: overall_srs, factors, suggestions, model_used, confidence,
        latency_ms.
    """
    try:
        from kicad_agent.analysis.legibility_critic import (
            CritiqueResult,
            HybridLegibilityCritic,
        )

        # 1. Render schematic to PDF
        image = _render_schematic_to_image(file_path)
        if image is None:
            logger.warning("critique_sch: schematic render failed")
            return _fallback_dict(include_suggestions=getattr(op, "include_suggestions", True))

        # 2. Construct HybridLegibilityCritic with lazy model loading
        hybrid = _build_hybrid_critic(op)
        if hybrid is None:
            # Both lazy factories declined (claude_only with no API key, etc.)
            return _fallback_dict(include_suggestions=getattr(op, "include_suggestions", True))

        # 3. Dispatch critique
        result = hybrid.critique(image=image, file_path=str(file_path))

        # 4. Return JSON-friendly dict
        return _result_to_dict(result, include_suggestions=getattr(op, "include_suggestions", True))
    except Exception as exc:
        # R-6: NEVER raise from handler. T-109-02 logs type+message only.
        logger.warning(
            "critique_sch R-6 fallback: %s: %s",
            type(exc).__name__, exc,
        )
        return _fallback_dict(include_suggestions=getattr(op, "include_suggestions", True))


def _build_hybrid_critic(op: Any) -> HybridLegibilityCritic | None:
    """Construct HybridLegibilityCritic with lazy model loading.

    - Gemma loaded only when claude_only is False
    - Claude loaded only when gemma_only is False

    Returns None if neither model can be loaded (extreme edge case).
    """
    from kicad_agent.analysis.legibility_critic import (
        ClaudeLegibilityCritic,
        GemmaLegibilityCritic,
        HybridLegibilityCritic,
    )

    claude_only = bool(getattr(op, "claude_only", False))
    gemma_only = bool(getattr(op, "gemma_only", False))

    gemma_critic = None
    claude_critic = None

    if not claude_only:
        gemma_critic = _load_gemma_critic()
    if not gemma_only:
        claude_critic = _load_claude_critic()

    # If we couldn't load either, fall back
    if gemma_critic is None and claude_critic is None:
        return None

    # Provide a stub for whichever critic we couldn't load — it will R-6 fallback
    # immediately when called. This keeps the HybridLegibilityCritic contract intact.
    if gemma_critic is None:
        # Construct a stub that always returns R-6 fallback
        from kicad_agent.analysis.legibility_critic import GemmaLegibilityCritic
        class _StubPipeline:
            def generate_from_image(self, image: Any, prompt: str) -> str:
                raise RuntimeError("Gemma model not loaded")
        gemma_critic = GemmaLegibilityCritic(_StubPipeline())  # type: ignore[arg-type]
    if claude_critic is None:
        from kicad_agent.analysis.legibility_critic import ClaudeLegibilityCritic
        class _StubClient:
            def create_message(self, **kwargs: Any) -> Any:
                raise RuntimeError("Claude client not configured")
        claude_critic = ClaudeLegibilityCritic(_StubClient())  # type: ignore[arg-type]

    return HybridLegibilityCritic(
        gemma=gemma_critic,
        claude=claude_critic,
        gemma_only=gemma_only,
        claude_only=claude_only,
    )


def _load_gemma_critic() -> Any:
    """Lazy-load Gemma 4 12B V2 critic. Returns None on any failure.

    Isolated so unit tests never trigger the 23.8 GB model load (Phase 98-03).
    Real invocation deferred to Phase 110 eval harness.
    """
    try:
        from kicad_agent.analysis.legibility_critic import GemmaLegibilityCritic
        from kicad_agent.inference.vision_pipeline import (
            KiCadVisionConfig,
            KiCadVisionPipeline,
        )
        pipeline = KiCadVisionPipeline(KiCadVisionConfig())
        return GemmaLegibilityCritic(pipeline)
    except Exception as exc:
        logger.warning("Gemma critic load failed: %s: %s", type(exc).__name__, exc)
        return None


def _load_claude_critic() -> Any:
    """Lazy-load Claude critic via LLMClient wrapper. Returns None on any failure.

    Returns None when ANTHROPIC_API_KEY is missing (T-15-03 LLMConfigError).
    """
    try:
        from kicad_agent.analysis.legibility_critic import ClaudeLegibilityCritic
        from kicad_agent.llm.client import LLMClient
        client = LLMClient()
        return ClaudeLegibilityCritic(client)
    except Exception as exc:
        logger.warning("Claude critic load failed: %s: %s", type(exc).__name__, exc)
        return None


def _render_schematic_to_image(file_path: Path) -> Any:
    """Render schematic to PIL image via kicad-cli sch export pdf.

    LO-03: pdf2image is not a project dependency. We attempt multiple
    conversion paths in priority order:
    1. pdf2image if installed (preferred — Phase 48.5 dependency assumption)
    2. cairosvg via kicad-cli sch export svg (fallback)
    3. None on any failure (R-6 will fall back to placeholder)

    Caller cleans up temp files via the returned image's lifecycle.
    """
    try:
        from PIL import Image  # noqa: F401  (assert dep available)
    except ImportError:
        logger.warning("Pillow not installed — cannot render schematic image")
        return None

    pdf_path: str | None = None
    try:
        # Render PDF via kicad-cli
        with tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False, prefix="critique_sch_"
        ) as tmp:
            pdf_path = tmp.name

        result = subprocess.run(
            [
                "kicad-cli", "sch", "export", "pdf",
                str(file_path), "-o", pdf_path,
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            logger.warning("kicad-cli sch export pdf failed: %s", result.stderr[:200])
            return None

        # Try pdf2image conversion (Phase 48.5 assumed dependency)
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(pdf_path, dpi=150)
            if images:
                return images[0]
            return None
        except ImportError:
            logger.info("pdf2image not installed — trying SVG conversion fallback")

        # Fallback: SVG + cairosvg
        return _render_via_svg(file_path)
    except Exception as exc:
        logger.warning(
            "Schematic render failed: %s: %s", type(exc).__name__, exc
        )
        return None
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.unlink(pdf_path)
            except OSError:
                pass


def _render_via_svg(file_path: Path) -> Any:
    """Render schematic via SVG export + cairosvg conversion. May return None."""
    svg_dir = tempfile.mkdtemp(prefix="critique_sch_svg_")
    try:
        result = subprocess.run(
            [
                "kicad-cli", "sch", "export", "svg",
                str(file_path), "-o", svg_dir,
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return None

        svg_files = list(Path(svg_dir).glob("*.svg"))
        if not svg_files:
            return None

        try:
            import cairosvg
            from PIL import Image
            png_data = cairosvg.svg2png(url=str(svg_files[0]), output_width=1024)
            import io
            return Image.open(io.BytesIO(png_data))
        except ImportError:
            logger.info("cairosvg not installed — cannot convert SVG to PIL")
            return None
    finally:
        # Best-effort cleanup
        try:
            import shutil
            shutil.rmtree(svg_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


def _result_to_dict(result: Any, *, include_suggestions: bool = True) -> dict[str, Any]:
    """Convert CritiqueResult to JSON-friendly dict."""
    return {
        "overall_srs": float(result.overall_srs),
        "factors": dict(result.factors),
        "suggestions": (
            [
                {"text": s.text, "severity": s.severity, "category": s.category}
                for s in result.suggestions
            ]
            if include_suggestions
            else []
        ),
        "model_used": result.model_used,
        "confidence": float(result.confidence),
        "latency_ms": int(result.latency_ms),
    }


def _fallback_dict(*, include_suggestions: bool = True) -> dict[str, Any]:
    """R-6 fallback dict — zero values, model_used='none'."""
    return {
        "overall_srs": 0.0,
        "factors": {"density": 0.0, "clarity": 0.0, "spacing": 0.0, "organization": 0.0},
        "suggestions": [] if include_suggestions else [],
        "model_used": "none",
        "confidence": 0.0,
        "latency_ms": 0,
    }
