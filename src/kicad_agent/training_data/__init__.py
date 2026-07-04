"""Phase 159: AI Training Data Factory.

Turns KiCad schematics into SFT training data for the NL→SKIDL model.
"""
from kicad_agent.training_data.nl_generator import (
    TrainingExample,
    generate_nl_description,
    create_training_example,
    convert_schematic_to_training_data,
    batch_convert_schematics,
)
from kicad_agent.training_data.skidl_corpus import (
    convert_repo_to_skidl,
    batch_convert_corpus,
    load_discovered_repos,
)
from kicad_agent.training_data.sim_aware_reward_combiner import (
    combine_rewards,
    compute_spice_reward,
    compute_combined_reward,
)
from kicad_agent.training_data.placement_pair_builder import (
    PlacementPair,
    build_placement_pairs,
    build_pairs_batch,
)

__all__ = [
    "TrainingExample",
    "generate_nl_description",
    "create_training_example",
    "convert_schematic_to_training_data",
    "batch_convert_schematics",
    "convert_repo_to_skidl",
    "batch_convert_corpus",
    "load_discovered_repos",
    "combine_rewards",
    "compute_spice_reward",
    "compute_combined_reward",
    "PlacementPair",
    "build_placement_pairs",
    "build_pairs_batch",
]
