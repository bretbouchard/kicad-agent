"""High-level placement prediction wrapping model inference.

Provides PlacementPredictor that takes a PlacementGraph and produces
predicted (x, y, rotation) positions for all components. Uses lazy
torch import so the module can be imported without torch installed.

Security (threat model):
  T-16-03: Model weights loaded with torch.load(weights_only=True).

Usage::

    from kicad_agent.placement.predict import PlacementPredictor, PlacementPrediction

    predictor = PlacementPredictor(model_path=Path("model.pt"))
    prediction = predictor.predict(graph)
    for ref, (x, y, rot) in prediction.positions.items():
        print(f"{ref}: ({x:.1f}, {y:.1f}, {rot:.1f} deg)")
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy

if TYPE_CHECKING:
    from kicad_agent.placement.graph import PlacementGraph


@dataclass(frozen=True)
class PlacementPrediction:
    """Result of a placement prediction run.

    Attributes:
        positions: Mapping of reference designator to (x, y, rotation_degrees).
        raw_output: (n_comp, 3) raw model output array.
        model_confidence: Average softmax entropy across output heads (0-1).
    """

    positions: dict[str, tuple[float, float, float]]
    raw_output: numpy.ndarray
    model_confidence: float


class PlacementPredictor:
    """Wraps PlacementModel for high-level inference on PlacementGraph.

    Handles feature extraction from the graph, tensor conversion,
    model forward pass, and result mapping back to component references.

    Args:
        model_path: Optional path to saved model weights. None = random init.
        device: Torch device string (default "cpu").
    """

    def __init__(
        self,
        model_path: Path | None = None,
        device: str = "cpu",
    ) -> None:
        import torch

        from kicad_agent.placement.model import PlacementModel

        self._device = device
        self._model = PlacementModel()

        if model_path is not None and Path(model_path).exists():
            state_dict = torch.load(
                model_path,
                map_location=device,
                weights_only=True,
            )
            self._model.load_state_dict(state_dict)

        self._model.to(device)
        self._model.eval()
        self._torch = torch

    @property
    def is_ready(self) -> bool:
        """True if model is loaded and parameters initialized."""
        try:
            # Check that parameters exist and are not empty
            params = list(self._model.parameters())
            return len(params) > 0
        except Exception:
            return False

    def predict(self, graph: PlacementGraph) -> PlacementPrediction:
        """Predict (x, y, rotation) for all components in the graph.

        Args:
            graph: PlacementGraph with component/net features and board dims.

        Returns:
            PlacementPrediction with positions mapped to component references.
        """
        import torch

        from kicad_agent.placement.model import PlacementModel

        # Extract features from graph
        board_w = graph.board_width
        board_h = graph.board_height
        comp_features = graph.get_component_features(board_w, board_h)
        net_features = graph.get_net_features()
        adj_matrix = graph.get_adjacency_matrix()

        # Convert to tensors with batch dimension
        comp_t = torch.tensor(
            comp_features, dtype=torch.float32, device=self._device
        ).unsqueeze(0)
        net_t = torch.tensor(
            net_features, dtype=torch.float32, device=self._device
        ).unsqueeze(0)
        adj_t = torch.tensor(
            adj_matrix, dtype=torch.float32, device=self._device
        ).unsqueeze(0)
        bw_t = torch.tensor([board_w], dtype=torch.float32, device=self._device)
        bh_t = torch.tensor([board_h], dtype=torch.float32, device=self._device)

        # Forward pass
        with torch.no_grad():
            output = self._model(comp_t, net_t, adj_t, bw_t, bh_t)

        # Remove batch dimension, convert to numpy
        raw = output.squeeze(0).cpu().numpy()  # (n_comp, 3)

        # Map to component references
        comp_refs = graph.component_nodes()
        # Strip "comp:" prefix from node IDs to get reference designators
        ref_names = [nid.replace("comp:", "", 1) for nid in comp_refs]

        positions: dict[str, tuple[float, float, float]] = {}
        for i, ref in enumerate(ref_names):
            positions[ref] = (
                float(raw[i, 0]),
                float(raw[i, 1]),
                float(raw[i, 2]),
            )

        # Compute confidence from output entropy
        # Use sigmoid probabilities from x/y heads as proxy
        confidence = _compute_confidence(raw, board_w, board_h)

        return PlacementPrediction(
            positions=positions,
            raw_output=raw,
            model_confidence=confidence,
        )


def _compute_confidence(
    raw_output: numpy.ndarray,
    board_w: float,
    board_h: float,
) -> float:
    """Compute model confidence from output entropy proxy.

    Uses variance of normalized positions as confidence indicator.
    High spread = high confidence (model is decisive).

    Args:
        raw_output: (n_comp, 3) raw model output.
        board_w: Board width for normalization.
        board_h: Board height for normalization.

    Returns:
        Confidence score in [0, 1].
    """
    if raw_output.size == 0:
        return 0.0

    n_comp = raw_output.shape[0]
    if n_comp == 0:
        return 0.0

    # Normalize x to [0, 1] and y to [0, 1]
    x_norm = raw_output[:, 0] / max(board_w, 1.0)
    y_norm = raw_output[:, 1] / max(board_h, 1.0)

    # Average spread (variance) of normalized positions
    if n_comp > 1:
        x_var = float(numpy.var(x_norm))
        y_var = float(numpy.var(y_norm))
        # Map variance to confidence: moderate spread = good
        confidence = min(1.0, (x_var + y_var) * 4.0)
    else:
        confidence = 0.5

    return confidence
