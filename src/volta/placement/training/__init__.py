"""Placement training infrastructure: dataset, reward, and trainer.

Provides synthetic placement data generation, spatial reward computation,
and GRPO-based training for the PlacementModel.

Usage::

    from volta.placement.training import (
        PlacementSample,
        PlacementDataset,
        placement_reward,
        compute_placement_loss,
        PlacementTrainer,
        PlacementTrainConfig,
    )
"""

from volta.placement.training.dataset import (
    PlacementDataset,
    PlacementSample,
)
from volta.placement.training.reward import (
    compute_placement_loss,
    placement_reward,
)
from volta.placement.training.train import (
    PlacementTrainConfig,
    PlacementTrainer,
)

__all__ = [
    "PlacementSample",
    "PlacementDataset",
    "placement_reward",
    "compute_placement_loss",
    "PlacementTrainer",
    "PlacementTrainConfig",
]
