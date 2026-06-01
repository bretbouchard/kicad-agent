"""Pydantic schemas for PCB MMLU benchmark questions and datasets.

Defines BenchmarkQuestion (single multi-choice question) and BenchmarkDataset
(ordered collection of questions with metadata). All questions have exactly
4 choices with 1 correct answer, validated at schema level.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class BenchmarkQuestion(BaseModel):
    """A single PCB MMLU multi-choice benchmark question.

    Attributes:
        id: Unique identifier in pcb-mmlu-NNNN format.
        category: One of 8 benchmark categories.
        difficulty: easy (1-3 components), medium (4-8), hard (9+).
        question: The question text.
        choices: Exactly 4 answer choices, all unique and non-empty.
        correct_index: Index (0-3) of the correct answer in choices.
        explanation: Why the correct answer is right.
        source: File path or identifier of the source schematic.
        source_type: What kind of source the question comes from.
        tags: Free-form tags for filtering and analysis.
    """

    id: str = Field(pattern=r"^pcb-mmlu-\d{4}$")
    category: Literal[
        "component_identification",
        "topology_recognition",
        "signal_flow",
        "power_design",
        "pin_function",
        "net_purpose",
        "design_rules",
        "troubleshooting",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    question: str = Field(min_length=10, max_length=2000)
    choices: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=10, max_length=5000)
    source: str = Field(min_length=1, max_length=512)
    source_type: Literal["schematic", "datasheet", "erc_report", "netlist", "manual"]
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("choices")
    @classmethod
    def _no_duplicate_choices(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("Choices must be unique")
        return v

    @field_validator("choices")
    @classmethod
    def _no_empty_choices(cls, v: list[str]) -> list[str]:
        if any(not c.strip() for c in v):
            raise ValueError("Choices must not be empty")
        return v


class BenchmarkDataset(BaseModel):
    """A complete PCB MMLU benchmark dataset.

    Attributes:
        version: Semantic version string (e.g. "1.0.0").
        generated_at: ISO 8601 timestamp of generation.
        questions: Ordered list of benchmark questions.
        metadata: Generation metadata (seed, source count, etc.).
    """

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    generated_at: str
    questions: list[BenchmarkQuestion] = Field(min_length=1)
    metadata: dict = Field(default_factory=dict)
