"""Demo pipeline: one-command schematic generation with validation and rendering."""

from kicad_agent.demo.pipeline import DemoPipeline, DemoReport
from kicad_agent.demo.templates import DemoTemplate, get_template, list_templates, get_random_template

__all__ = [
    "DemoPipeline",
    "DemoReport",
    "DemoTemplate",
    "get_template",
    "list_templates",
    "get_random_template",
]
