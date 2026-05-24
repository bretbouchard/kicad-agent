"""Tests for placement model architecture and prediction API.

Tests cover:
- Model output shape and bounds
- Gradient flow for differentiable training
- Attention layer residual connections
- PlacementPredictor end-to-end inference
- Lazy import behavior
"""

from pathlib import Path

import pytest
import torch

from kicad_agent.placement.model import BipartiteAttentionLayer, PlacementModel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def model() -> PlacementModel:
    """Fresh PlacementModel with default architecture."""
    return PlacementModel()


@pytest.fixture
def sample_inputs():
    """Random tensors for model forward pass: batch=2, n_comp=5, n_net=3."""
    torch.manual_seed(42)
    batch, n_comp, n_net = 2, 5, 3
    comp_features = torch.randn(batch, n_comp, 32)
    net_features = torch.randn(batch, n_net, 16)
    adj_matrix = torch.ones(batch, n_comp, n_net)  # fully connected
    board_w = torch.tensor([100.0, 120.0])
    board_h = torch.tensor([80.0, 90.0])
    return comp_features, net_features, adj_matrix, board_w, board_h


# ---------------------------------------------------------------------------
# Model architecture tests
# ---------------------------------------------------------------------------


class TestPlacementModel:
    """Tests for PlacementModel architecture."""

    def test_model_output_shape(self, model, sample_inputs):
        """Model output shape is (batch, n_comp, 3)."""
        comp_features, net_features, adj_matrix, board_w, board_h = sample_inputs
        output = model(comp_features, net_features, adj_matrix, board_w, board_h)
        assert output.shape == (2, 5, 3)

    def test_model_output_bounds(self, model, sample_inputs):
        """x in [0, board_w], y in [0, board_h], rotation in [-180, 180]."""
        comp_features, net_features, adj_matrix, board_w, board_h = sample_inputs
        output = model(comp_features, net_features, adj_matrix, board_w, board_h)

        for b in range(2):
            # x bounds
            assert output[b, :, 0].min().item() >= 0.0
            assert output[b, :, 0].max().item() <= board_w[b].item() + 1e-5

            # y bounds
            assert output[b, :, 1].min().item() >= 0.0
            assert output[b, :, 1].max().item() <= board_h[b].item() + 1e-5

            # rotation bounds
            assert output[b, :, 2].min().item() >= -180.0 - 1e-5
            assert output[b, :, 2].max().item() <= 180.0 + 1e-5

    def test_model_gradient_flow(self, model, sample_inputs):
        """Backward pass produces no NaN gradients."""
        comp_features, net_features, adj_matrix, board_w, board_h = sample_inputs
        output = model(comp_features, net_features, adj_matrix, board_w, board_h)

        # Compute a simple loss
        loss = output.sum()
        loss.backward()

        for name, param in model.named_parameters():
            if param.grad is not None:
                assert not torch.isnan(param.grad).any(), (
                    f"NaN gradient in {name}"
                )

    def test_model_different_batch_sizes(self, model):
        """Model works with batch size 1."""
        torch.manual_seed(123)
        comp = torch.randn(1, 3, 32)
        net = torch.randn(1, 2, 16)
        adj = torch.ones(1, 3, 2)
        bw = torch.tensor([50.0])
        bh = torch.tensor([40.0])

        output = model(comp, net, adj, bw, bh)
        assert output.shape == (1, 3, 3)

    def test_model_custom_architecture(self):
        """Model works with non-default hidden_dim and layers."""
        m = PlacementModel(
            comp_feature_dim=32,
            net_feature_dim=16,
            hidden_dim=64,
            n_layers=2,
            n_heads=2,
        )
        torch.manual_seed(99)
        comp = torch.randn(1, 4, 32)
        net = torch.randn(1, 2, 16)
        adj = torch.ones(1, 4, 2)
        bw = torch.tensor([100.0])
        bh = torch.tensor([80.0])

        output = m(comp, net, adj, bw, bh)
        assert output.shape == (1, 4, 3)


# ---------------------------------------------------------------------------
# Attention layer tests
# ---------------------------------------------------------------------------


class TestBipartiteAttentionLayer:
    """Tests for BipartiteAttentionLayer."""

    def test_attention_layer_residual(self):
        """BipartiteAttentionLayer output differs from input (residual applied)."""
        layer = BipartiteAttentionLayer(comp_dim=128, net_dim=128, n_heads=4)
        torch.manual_seed(42)

        comp = torch.randn(1, 5, 128)
        net = torch.randn(1, 3, 128)
        adj = torch.ones(1, 5, 3)

        output = layer(comp, net, adj)

        # Output should differ from input (residual + attention contribution)
        assert not torch.allclose(output, comp, atol=1e-6)

        # But should be in same ballpark (residual adds to input)
        diff = (output - comp).abs().mean().item()
        assert diff > 0.0  # Some change happened

    def test_attention_with_sparse_adjacency(self):
        """Attention works when most adj entries are zero."""
        layer = BipartiteAttentionLayer(comp_dim=64, net_dim=64, n_heads=2)
        torch.manual_seed(42)

        comp = torch.randn(1, 3, 64)
        net = torch.randn(1, 5, 64)
        # Only comp 0 connects to net 0, comp 1 to net 2, comp 2 to net 4
        adj = torch.zeros(1, 3, 5)
        adj[0, 0, 0] = 1.0
        adj[0, 1, 2] = 1.0
        adj[0, 2, 4] = 1.0

        output = layer(comp, net, adj)
        assert output.shape == (1, 3, 64)
        assert not torch.isnan(output).any()


# ---------------------------------------------------------------------------
# PlacementPredictor tests
# ---------------------------------------------------------------------------


class TestPlacementPredictor:
    """Tests for PlacementPredictor."""

    def test_predictor_from_graph(self, sample_placement_graph):
        """PlacementPredictor produces positions for all components."""
        from kicad_agent.placement.predict import PlacementPredictor

        predictor = PlacementPredictor(model_path=None)
        prediction = predictor.predict(sample_placement_graph)

        # Should have positions for all 5 components
        assert len(prediction.positions) == 5
        assert set(prediction.positions.keys()) == {"U1", "R1", "C1", "J1", "L1"}

        # Each position is a tuple of 3 floats
        for ref, (x, y, rot) in prediction.positions.items():
            assert isinstance(x, float)
            assert isinstance(y, float)
            assert isinstance(rot, float)

    def test_predictor_positions_in_bounds(self, sample_placement_graph):
        """Predicted (x, y) within [0, board_width] x [0, board_height]."""
        from kicad_agent.placement.predict import PlacementPredictor

        predictor = PlacementPredictor(model_path=None)
        prediction = predictor.predict(sample_placement_graph)

        board_w = sample_placement_graph.board_width
        board_h = sample_placement_graph.board_height

        for ref, (x, y, rot) in prediction.positions.items():
            assert 0.0 <= x <= board_w, f"{ref} x={x} out of [0, {board_w}]"
            assert 0.0 <= y <= board_h, f"{ref} y={y} out of [0, {board_h}]"
            assert -180.0 <= rot <= 180.0, f"{ref} rot={rot} out of [-180, 180]"

    def test_predictor_lazy_import(self):
        """Import of PlacementPredictor succeeds (torch is installed)."""
        from kicad_agent.placement.predict import PlacementPredictor

        assert PlacementPredictor is not None

    def test_predictor_no_model_file(self):
        """PlacementPredictor(model_path=None) initializes with random weights."""
        from kicad_agent.placement.predict import PlacementPredictor

        predictor = PlacementPredictor(model_path=None)
        assert predictor.is_ready is True

    def test_predictor_raw_output_shape(self, sample_placement_graph):
        """Raw output has shape (n_comp, 3)."""
        from kicad_agent.placement.predict import PlacementPredictor

        predictor = PlacementPredictor(model_path=None)
        prediction = predictor.predict(sample_placement_graph)

        assert prediction.raw_output.shape == (5, 3)

    def test_predictor_confidence_range(self, sample_placement_graph):
        """Model confidence is in [0, 1]."""
        from kicad_agent.placement.predict import PlacementPredictor

        predictor = PlacementPredictor(model_path=None)
        prediction = predictor.predict(sample_placement_graph)

        assert 0.0 <= prediction.model_confidence <= 1.0

    def test_predictor_nonexistent_model_file(self):
        """PlacementPredictor with nonexistent path still initializes."""
        from kicad_agent.placement.predict import PlacementPredictor

        predictor = PlacementPredictor(model_path=Path("/nonexistent/model.pt"))
        assert predictor.is_ready is True
