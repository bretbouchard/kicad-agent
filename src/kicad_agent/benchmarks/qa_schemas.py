"""Pydantic schemas for Circuit QA dataset.

Defines CircuitQAPair (single open-ended QA pair) and CircuitQADataset
(ordered collection of QA pairs with metadata and train/val/test splits).

Unlike BenchmarkQuestion (multi-choice), CircuitQAPair represents free-form
question-answer pairs for fine-tuning circuit understanding models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class CircuitQAPair(BaseModel):
    """A single circuit QA pair with open-ended question and answer.

    Attributes:
        id: Unique identifier in qa-NNNN format.
        qa_type: One of 6 QA categories.
        question: The question text (open-ended, not multi-choice).
        answer: The answer text with explanation and context.
        source: File path or identifier of the originating schematic.
        source_type: What kind of source the QA pair comes from.
        difficulty: easy (simple lookup), medium (analysis), hard (synthesis).
        tags: Free-form tags for filtering and analysis.
        split: Dataset split assignment (train/val/test).
    """

    id: str = Field(pattern=r"^qa-\d{4}$")
    qa_type: Literal[
        "violation_diagnosis",
        "signal_flow",
        "component_function",
        "net_purpose",
        "design_review",
        "value_calculation",
    ]
    question: str = Field(min_length=10, max_length=5000)
    answer: str = Field(min_length=20, max_length=10000)
    source: str = Field(min_length=1, max_length=512)
    source_type: Literal["schematic", "erc_report", "netlist", "bom", "datasheet", "manual"]
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str] = Field(default_factory=list, max_length=10)
    split: Literal["train", "val", "test"] = "train"


class CircuitQADataset(BaseModel):
    """A complete Circuit QA dataset with train/validation/test splits.

    Attributes:
        version: Semantic version string (e.g. "1.0.0").
        generated_at: ISO 8601 timestamp of generation.
        qa_pairs: Ordered list of QA pairs.
        metadata: Generation metadata (seed, split counts, source count, etc.).
    """

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    generated_at: str
    qa_pairs: list[CircuitQAPair] = Field(min_length=1)
    metadata: dict = Field(default_factory=dict)
