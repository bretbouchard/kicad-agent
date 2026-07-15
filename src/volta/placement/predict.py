"""High-level placement prediction wrapping ONNX model inference.

Provides PlacementPredictor that takes a PlacementGraph and produces
predicted (x, y, rotation) positions for all components. Uses ONNX Runtime
for inference — no PyTorch dependency required.

The model was exported from the PyTorch PlacementModel (304K params, 217 KB
ONNX file). The ONNX Runtime Python wheel is ~2 MB vs torch's 320 MB.

Usage::

    from volta.placement.predict import PlacementPredictor, PlacementPrediction

    predictor = PlacementPredictor()
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
    from volta.placement.graph import PlacementGraph


@dataclass(frozen=True)
class PlacementPrediction:
    """Result of a placement prediction run.

    Args:
        positions: Mapping of reference designator to (x, y, rotation_degrees).
        raw_output: (n_comp, 3) raw model output array.
        model_confidence: Average softmax entropy across output heads (0-1).
    """

    positions: dict[str, tuple[float, float, float]]
    raw_output: numpy.ndarray
    model_confidence: float


class PlacementPredictor:
    """Wraps the ONNX placement model for high-level inference on PlacementGraph.

    Handles feature extraction from the graph, numpy conversion,
    ONNX forward pass, and result mapping back to component references.

    Args:
        model_path: Path to the .onnx model file. Defaults to the bundled model
                    next to this module's daemon directory.
    """

    def __init__(self, model_path: Path | None = None) -> None:
        import onnxruntime as ort

        if model_path is None:
            # Default: look for placement.onnx in likely locations.
            # Frozen daemon (PyInstaller): _internal/placement.onnx
            # App bundle: Contents/Resources/volta-daemon/_internal/placement.onnx
            # Dev: macos-app/daemon/placement.onnx
            import sys
            candidates = [
                Path(sys._MEIPASS) / "placement.onnx" if hasattr(sys, "_MEIPASS") else None,
                Path(__file__).parent / "placement.onnx",
                Path(__file__).parent.parent / "_internal" / "placement.onnx",
                Path("macos-app/daemon/placement.onnx"),
                Path("daemon/placement.onnx"),
            ]
            model_path = next((p for p in candidates if p and p.exists()), candidates[0])

        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )

    @property
    def is_ready(self) -> bool:
        """True if the ONNX session is loaded."""
        return self._session is not None

    def predict(self, graph: PlacementGraph) -> PlacementPrediction:
        """Predict (x, y, rotation) for all components in the graph.

        Args:
            graph: PlacementGraph with component/net features and board dims.

        Returns:
            PlacementPrediction with positions mapped to component references.
        """
        # Extract features from graph
        board_w = graph.board_width
        board_h = graph.board_height
        comp_features = graph.get_component_features(board_w, board_h)
        net_features = graph.get_net_features()
        adj_matrix = graph.get_adjacency_matrix()

        # Add batch dimension (ONNX expects (1, n_comp, ...) etc.)
        comp_arr = numpy.array(comp_features, dtype=numpy.float32).unsqueeze(0) if hasattr(comp_features, "unsqueeze") else numpy.expand_dims(numpy.array(comp_features, dtype=numpy.float32), 0)
        net_arr = numpy.expand_dims(numpy.array(net_features, dtype=numpy.float32), 0)
        adj_arr = numpy.expand_dims(numpy.array(adj_matrix, dtype=numpy.float32), 0)
        bw_arr = numpy.array([board_w], dtype=numpy.float32)
        bh_arr = numpy.array([board_h], dtype=numpy.float32)

        # ONNX forward pass
        outputs = self._session.run(None, {
            "comp_features": comp_arr,
            "net_features": net_arr,
            "adj_matrix": adj_arr,
            "board_w": bw_arr,
            "board_h": bh_arr,
        })

        # Remove batch dimension → (n_comp, 3)
        raw = outputs[0].squeeze(0)

        # Map to component references
        comp_refs = graph.component_nodes()
        ref_names = [nid.replace("comp:", "", 1) for nid in comp_refs]

        positions: dict[str, tuple[float, float, float]] = {}
        for i, ref in enumerate(ref_names):
            positions[ref] = (
                float(raw[i, 0]),
                float(raw[i, 1]),
                float(raw[i, 2]),
            )

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

    x_norm = raw_output[:, 0] / max(board_w, 1.0)
    y_norm = raw_output[:, 1] / max(board_h, 1.0)

    if n_comp > 1:
        x_var = float(numpy.var(x_norm))
        y_var = float(numpy.var(y_norm))
        confidence = min(1.0, (x_var + y_var) * 4.0)
    else:
        confidence = 0.5

    return confidence
