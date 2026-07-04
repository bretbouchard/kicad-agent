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

__all__ = [
    "TrainingExample",
    "generate_nl_description",
    "create_training_example",
    "convert_schematic_to_training_data",
    "batch_convert_schematics",
]
