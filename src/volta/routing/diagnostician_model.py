"""Phase 106: Model-based blocker diagnostician.

Wraps KiCadVisionPipeline to provide AI-powered blocker diagnosis, mirroring
the AiRoutingStrategy pattern (ai_strategy.py). The model consumes a board
render + the failure description and emits a blocker classification.

Graceful degradation (R-6): on ANY failure (model crash, parse error, garbage
output), delegates to the deterministic BlockerDiagnostician fallback. This
mirrors ai_strategy.py:168 where AiRoutingStrategy falls back to
DeterministicStrategy.

The model is opt-in only — the deterministic diagnostician remains the
default in NegotiationLoop. To use the model:

    from volta.routing.diagnostician_model import BlockerDiagnosticianModel

    model_diag = BlockerDiagnosticianModel(
        pipeline=my_pipeline,
        pcb_path=pcb_path,
        fallback=deterministic_diagnostician,
        board_bounds=bounds,
    )
    # Use in NegotiationLoop
    NegotiationLoop(..., diagnostician=model_diag)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from volta.routing.diagnostician import (
    Blocker,
    BlockerDiagnostician,
    BlockerDiagnosis,
)
from volta.routing.diagnostician_model_prompts import (
    build_diagnostician_prompt,
    get_system_prompt,
)
from volta.routing.pathfinder import RouteFailure

logger = logging.getLogger(__name__)

# Regex patterns for parsing the model's response.
# Matches the training format from generate_diagnostic_training_data.py:179-187.
_BLOCKER_ENTRY_RE = re.compile(
    r"(\d+)\.\s+(\w+)\s+'([^']+)'\s*\(([^)]+)\)",
)
_CLASSIFICATION_RE = re.compile(r"Classification:\s*(\w+)", re.IGNORECASE)
_CAUSAL_RE = re.compile(r"Causal blocker:\s*(True|False)", re.IGNORECASE)
_ACTION_RE = re.compile(r"Recommended action:\s*(\w+)", re.IGNORECASE)
_BENEFIT_RE = re.compile(r"Removal benefit:\s*([\d.]+)", re.IGNORECASE)

_VALID_CLASSIFICATIONS = {
    "SOFT_OTHER", "SOFT_OWN", "HARD_COMPONENT", "HARD_FIXED", "CONTESTED",
}
_VALID_ACTIONS = {
    "rip_and_reroute", "reroute_self", "nudge_component",
    "escalate", "raise_priority",
}


class BlockerDiagnosticianModel:
    """AI-powered blocker diagnostician with deterministic fallback.

    Implements the same contract as BlockerDiagnostician:
        diagnose(failure: RouteFailure) -> BlockerDiagnosis

    The model is untrusted — on any failure, it falls back to the
    deterministic diagnostician (R-6 graceful degradation).
    """

    def __init__(
        self,
        pipeline: Any,
        pcb_path: Path,
        fallback: BlockerDiagnostician,
        board_bounds: tuple[float, float, float, float],
        render_fn: Callable[[Path], Any] | None = None,
    ) -> None:
        """Initialize the model-based diagnostician.

        Args:
            pipeline: KiCadVisionPipeline instance (typed Any to avoid
                importing mlx-vlm at module load — the pipeline is ~24GB).
            pcb_path: Path to the .kicad_pcb file (for board rendering).
            fallback: Deterministic BlockerDiagnostician for graceful
                degradation. Required — the model is untrusted.
            board_bounds: (x_min, y_min, x_max, y_max) for prompt context.
            render_fn: Optional board-to-image renderer. If None, uses
                volta.export.pcb_image_renderer.render_pcb_layer_png.
        """
        self._pipeline = pipeline
        self._pcb_path = pcb_path
        self._fallback = fallback
        self._board_bounds = board_bounds
        self._render_fn = render_fn

        # Lazy-load the renderer to avoid import overhead.
        if self._render_fn is None:
            from volta.export.pcb_image_renderer import render_pcb_layer_png
            self._render_fn = render_pcb_layer_png

    def diagnose(self, failure: RouteFailure) -> BlockerDiagnosis:
        """Diagnose a routing failure using the AI model.

        On any exception, falls back to the deterministic diagnostician.

        Args:
            failure: The RouteFailure from route_net.

        Returns:
            BlockerDiagnosis with identified blockers.
        """
        try:
            return self._diagnose_with_model(failure)
        except Exception as e:
            logger.warning(
                "Model diagnosis failed for net %s: %s — falling back to "
                "deterministic diagnostician",
                failure.net_name, e,
            )
            return self._fallback.diagnose(failure)

    def _diagnose_with_model(self, failure: RouteFailure) -> BlockerDiagnosis:
        """Run the model inference and parse the result."""
        # 1. Render the board to an image.
        image = self._render_fn(self._pcb_path)

        # 2. Build the prompt (exact training format).
        prompt = build_diagnostician_prompt(failure, self._board_bounds)

        # 3. Run model inference.
        raw_output = self._pipeline.generate_from_image(image, prompt)

        if not raw_output or not raw_output.strip():
            raise ValueError("Model returned empty output")

        # 4. Parse the response into Blocker objects.
        blockers = self._parse_response(raw_output)

        if not blockers:
            raise ValueError(
                f"Model output contained no parseable blockers: "
                f"{raw_output[:200]}..."
            )

        # 5. Construct the diagnosis.
        return BlockerDiagnosis(
            net_name=failure.net_name,
            dead_end_point=failure.dead_end_point,
            target_point=failure.target_point,
            blockers=tuple(blockers),
            failure_type=failure.failure_type,
        )

    def _parse_response(self, raw_output: str) -> list[Blocker]:
        """Parse the model's free-text response into Blocker objects.

        Expected format (from training data):
            Blockers identified (ranked by removal benefit):
              1. footprint 'KEEP_GND' (KEEPOUT_...)
                 Classification: HARD_FIXED
                 Causal blocker: True
                 Recommended action: escalate
                 Removal benefit: 0.1
        """
        blockers: list[Blocker] = []

        # Split into entries by the numbered list pattern.
        entries = re.split(r"\n\s*\d+\.\s+", raw_output)

        for entry in entries[1:]:  # Skip the preamble before "1."
            # Extract entity type and reference from the first line.
            first_line = entry.strip().split("\n")[0]
            type_match = re.match(
                r"(\w+)\s+'([^']+)'\s*\(([^)]+)\)", first_line,
            )

            if not type_match:
                continue

            entity_type = type_match.group(1).lower()
            reference = type_match.group(2)
            entity_id = type_match.group(3)

            # Extract classification, causal, action, benefit from subsequent lines.
            classification = self._extract_pattern(
                entry, _CLASSIFICATION_RE, "HARD_FIXED",
            ).upper()
            if classification not in _VALID_CLASSIFICATIONS:
                classification = "HARD_FIXED"

            causal_str = self._extract_pattern(entry, _CAUSAL_RE, "False")
            blocks_path = causal_str.lower() == "true"

            action = self._extract_pattern(
                entry, _ACTION_RE, "escalate",
            ).lower()
            if action not in _VALID_ACTIONS:
                action = "escalate"

            benefit_str = self._extract_pattern(entry, _BENEFIT_RE, "0.1")
            try:
                removal_benefit = float(benefit_str)
            except ValueError:
                removal_benefit = 0.1

            blockers.append(Blocker(
                entity_type=entity_type,
                entity_id=entity_id,
                classification=classification,
                blocks_path=blocks_path,
                recommended_action=action,
                removal_benefit=removal_benefit,
                reference=reference,
            ))

        return blockers

    @staticmethod
    def _extract_pattern(
        text: str,
        pattern: re.Pattern,
        default: str,
    ) -> str:
        """Extract the first regex match from text, or return default."""
        match = pattern.search(text)
        return match.group(1) if match else default
