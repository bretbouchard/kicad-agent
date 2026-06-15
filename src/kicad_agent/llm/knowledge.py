"""Knowledge base integration for local model inference.

Loads KiCad reference documents, chunks by section, and injects
relevant context into LLM prompts based on operation type.

Usage:
    from kicad_agent.llm.knowledge import KnowledgeManager

    km = KnowledgeManager()
    context = km.get_context_for_op("add_wire", "kicad_sch")
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from kicad_agent.ops.registry import OPERATION_REGISTRY

logger = logging.getLogger(__name__)

__all__ = ["KnowledgeManager", "get_context_for_op", "CORE_RULES", "OP_SECTION_MAP"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CORE_RULES: str = (
    "## KiCad Critical Rules\n"
    "- Pin (at X Y) = wire connection point, not pin graphic tip\n"
    "- Schematic Y is INVERTED: abs_Y = comp_Y - pin_rel_Y\n"
    "- Device:R/C have 3.81mm pin offsets (not 2.54mm)\n"
    "- Wires terminate at (at) coordinates\n"
    "- Grid snap: 50 mil (1.27mm) for schematics, 0.25mm for PCBs\n"
)

DOC_FILES: list[str] = [
    "kicad_agent_reference.md",
    "pcb_editor_reference.md",
    "gerbview_reference.md",
    "kicad_docs.md",
]

SECTION_TOKEN_CAP: int = 800  # Max tokens per individual section

# ---------------------------------------------------------------------------
# Category defaults: maps each registry category to doc section tuples
# (doc_name, section_name). section_name=None means inject entire document.
# ---------------------------------------------------------------------------

_CATEGORY_DEFAULTS: dict[str, list[tuple[str, str | None]]] = {
    # Schematic component operations
    "component": [
        ("kicad_agent_reference.md", "Working with symbols"),
        ("kicad_agent_reference.md", "Editing object properties"),
    ],
    # Wire and connection operations
    "wire": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    # Net operations
    "net": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    # Reference designator operations
    "reference": [
        ("kicad_agent_reference.md", "Reference designators and symbol annotation"),
    ],
    # Footprint operations
    "footprint": [
        ("pcb_editor_reference.md", "Working with footprints"),
        ("kicad_agent_reference.md", "Assigning Footprints in Symbol Properties"),
    ],
    # PCB layout operations
    "pcb": [
        ("pcb_editor_reference.md", "Design rules overview"),
        ("pcb_editor_reference.md", "Constraints"),
        ("pcb_editor_reference.md", "Net classes"),
    ],
    # Routing operations
    "routing": [
        ("pcb_editor_reference.md", "Routing tracks and vias"),
    ],
    # ERC operations
    "erc": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    # ERC smart operations
    "erc_smart": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    # Gate operations
    "gate": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
    ],
    # Library operations
    "library": [
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
    ],
    # Sheet operations
    "sheet": [
        ("kicad_agent_reference.md", "Forward and back annotation"),
    ],
    # Cross-file operations
    "crossfile": [
        ("kicad_agent_reference.md", "Forward and back annotation"),
        ("pcb_editor_reference.md", "Update PCB From Schematic"),
    ],
    # Repair operations
    "repair": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("pcb_editor_reference.md", "Design rules checking"),
    ],
    # Schematic intelligence operations
    "schematic_intel": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    # Constraint operations
    "constraint": [
        ("pcb_editor_reference.md", "Constraints"),
        ("pcb_editor_reference.md", "Net classes"),
    ],
    # Gap analysis operations
    "gap": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("pcb_editor_reference.md", "Design rules checking"),
    ],
    # Readability operations
    "readability": [
        ("kicad_agent_reference.md", "Reference designators and symbol annotation"),
    ],
    # Create operations
    "create": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    # Remove operations
    "remove": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    # Query operations
    "query": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
}

# ---------------------------------------------------------------------------
# Per-operation overrides for more specific section mappings
# ---------------------------------------------------------------------------

_PER_OP_OVERRIDES: dict[str, list[tuple[str, str | None]]] = {
    # Special: InferenceWrapper.analyze() uses "analyze" as a general PCB
    # analysis operation -- not in OPERATION_REGISTRY but used at inference time.
    "analyze": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_docs.md", "Electrical rules checking"),
        ("pcb_editor_reference.md", "Design rules overview"),
    ],
    # Schematic wire/connection ops -> wire section from kicad_docs
    "add_wire": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "add_label": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "add_power": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "add_no_connect": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "add_junction": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    "add_power_flag": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    # Component-specific overrides
    "add_component": [
        ("kicad_agent_reference.md", "Working with symbols"),
        ("kicad_agent_reference.md", "Assigning Footprints in Symbol Properties"),
    ],
    "move_component": [
        ("kicad_agent_reference.md", "Editing object properties"),
        ("kicad_docs.md", "Schematic Setup"),
    ],
    "snap_components_to_grid": [
        ("kicad_agent_reference.md", "Grids and snapping"),
        ("kicad_docs.md", "Schematic Setup"),
    ],
    # Footprint-specific overrides
    "assign_footprint": [
        ("kicad_agent_reference.md", "Assigning Footprints in Symbol Properties"),
        ("pcb_editor_reference.md", "Working with footprints"),
    ],
    "swap_footprint": [
        ("pcb_editor_reference.md", "Working with footprints"),
    ],
    "update_footprint_from_library": [
        ("pcb_editor_reference.md", "Working with footprints"),
    ],
    "verify_pin_map": [
        ("pcb_editor_reference.md", "Working with footprints"),
        ("pcb_editor_reference.md", "Footprint pads"),
    ],
    # PCB zone ops
    "add_copper_zone": [
        ("pcb_editor_reference.md", "Working with zones"),
    ],
    "modify_copper_zone": [
        ("pcb_editor_reference.md", "Working with zones"),
    ],
    "remove_copper_zone": [
        ("pcb_editor_reference.md", "Working with zones"),
    ],
    "refill_copper_zone": [
        ("pcb_editor_reference.md", "Working with zones"),
    ],
    "modify_zone_polygon": [
        ("pcb_editor_reference.md", "Working with zones"),
    ],
    # PCB design rules
    "add_design_rule": [
        ("pcb_editor_reference.md", "Custom rules"),
    ],
    "modify_design_rule": [
        ("pcb_editor_reference.md", "Custom rules"),
    ],
    "remove_design_rule": [
        ("pcb_editor_reference.md", "Custom rules"),
    ],
    # Board outline
    "set_board_outline": [
        ("pcb_editor_reference.md", "Board outlines (Edge Cuts)"),
    ],
    # Net class ops
    "add_net_class": [
        ("pcb_editor_reference.md", "Net classes"),
    ],
    "modify_net_class": [
        ("pcb_editor_reference.md", "Net classes"),
    ],
    "remove_net_class": [
        ("pcb_editor_reference.md", "Net classes"),
    ],
    "assign_net_class": [
        ("pcb_editor_reference.md", "Net classes"),
    ],
    "list_net_classes": [
        ("pcb_editor_reference.md", "Net classes"),
    ],
    # Routing ops
    "auto_route": [
        ("pcb_editor_reference.md", "Routing tracks and vias"),
    ],
    "route_diff_pair": [
        ("pcb_editor_reference.md", "Routing differential pairs"),
    ],
    "match_lengths": [
        ("pcb_editor_reference.md", "Length tuning"),
    ],
    # PCB keepout ops
    "add_keepout_area": [
        ("pcb_editor_reference.md", "Rule areas (keepouts)"),
    ],
    "remove_keepout_area": [
        ("pcb_editor_reference.md", "Rule areas (keepouts)"),
    ],
    # Sheet ops
    "add_sheet": [
        ("kicad_agent_reference.md", "Forward and back annotation"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "add_sheet_pin": [
        ("kicad_agent_reference.md", "Forward and back annotation"),
    ],
    "navigate_hierarchy": [
        ("kicad_agent_reference.md", "Forward and back annotation"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "rebuild_root_sheet": [
        ("kicad_agent_reference.md", "Forward and back annotation"),
    ],
    # Cross-file ops
    "update_pcb_from_schematic": [
        ("pcb_editor_reference.md", "Update PCB From Schematic"),
        ("kicad_agent_reference.md", "Forward and back annotation"),
    ],
    "propagate_symbol_change": [
        ("kicad_agent_reference.md", "Forward and back annotation"),
    ],
    # Gate ops
    "run_gate_check": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "gate_status": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
    ],
    # Annotation ops
    "annotate": [
        ("kicad_agent_reference.md", "Reference designators and symbol annotation"),
    ],
    "renumber_refs": [
        ("kicad_agent_reference.md", "Reference designators and symbol annotation"),
    ],
    "validate_refs": [
        ("kicad_agent_reference.md", "Reference designators and symbol annotation"),
    ],
    "cross_ref_check": [
        ("kicad_agent_reference.md", "Reference designators and symbol annotation"),
    ],
    # ERC ops
    "parse_erc": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "validate_power_nets": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "validate_schematic": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "pre_pcb_schematic_gate": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "extract_violation_positions": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "validate_hlabels": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    # Constraint ops
    "set_constraints": [
        ("pcb_editor_reference.md", "Constraints"),
        ("pcb_editor_reference.md", "Net classes"),
    ],
    "get_constraints": [
        ("pcb_editor_reference.md", "Constraints"),
        ("pcb_editor_reference.md", "Net classes"),
    ],
    # Library ops
    "add_lib_entry": [
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
    ],
    "remove_lib_entry": [
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
    ],
    "list_lib_entries": [
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
    ],
    "update_symbols_from_library": [
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
    ],
    # Schematic intel ops
    "extract_nets": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    "infer_connectivity": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    "detect_net_conflicts": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    "suggest_net_names": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    "detect_net_shorts": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    "trace_net_from_label": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    "analyze_ground_topology": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    # Net ops
    "add_net": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Setup"),
    ],
    "remove_net": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Setup"),
    ],
    "rename_net": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Setup"),
    ],
    # Remove ops
    "remove_wire": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "remove_label": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "remove_labels": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "remove_junction": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    "remove_no_connect": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    # Create ops
    "create_schematic": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
        ("kicad_docs.md", "Schematic Setup"),
    ],
    "create_pcb": [
        ("pcb_editor_reference.md", "Board editor layers"),
    ],
    "create_project": [
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "create_symbol": [
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
    ],
    "create_footprint": [
        ("pcb_editor_reference.md", "Working with footprints"),
        ("pcb_editor_reference.md", "Footprint pads"),
    ],
    "embed_symbol": [
        ("kicad_docs.md", "Symbols and Symbol Libraries"),
    ],
    "convert_kicad6_to_10": [
        ("kicad_docs.md", "Introduction to the KiCad Schematic Editor"),
    ],
    # Query ops
    "query_connectivity": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
    ],
    # Readability ops
    "review_schematic": [
        ("kicad_agent_reference.md", "Reference designators and symbol annotation"),
        ("kicad_docs.md", "The Schematic Editor User Interface"),
    ],
    # Gap ops
    "analyze_gaps": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("pcb_editor_reference.md", "Design rules checking"),
    ],
    "fill_gaps": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("pcb_editor_reference.md", "Design rules checking"),
    ],
    # Repair ops
    "repair_schematic": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "snap_to_grid": [
        ("kicad_agent_reference.md", "Grids and snapping"),
        ("kicad_docs.md", "Schematic Setup"),
    ],
    "fix_shorted_nets": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "fix_pin_type_mismatches": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "fix_net_short": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "break_wire_shorts": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "place_missing_units": [
        ("kicad_agent_reference.md", "Working with symbols"),
    ],
    "remove_dangling_wires": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "rename_net_label": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "resolve_shorted_nets": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    # Routing ops
    "batch_connect": [
        ("pcb_editor_reference.md", "Routing tracks and vias"),
    ],
    "connect_pins": [
        ("pcb_editor_reference.md", "Routing tracks and vias"),
    ],
    "place_net_labels": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    "resolve_pin_positions": [
        ("kicad_agent_reference.md", "Editing object properties"),
    ],
    "detect_routing_collisions": [
        ("pcb_editor_reference.md", "Routing tracks and vias"),
    ],
    "detect_pin_overlaps": [
        ("pcb_editor_reference.md", "Working with footprints"),
    ],
    "regenerate_wiring": [
        ("kicad_agent_reference.md", "Electrical connections between sheets"),
        ("pcb_editor_reference.md", "Routing tracks and vias"),
    ],
    # ERC smart ops
    "classify_violations": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "diagnose_violations": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "erc_auto_fix": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
    ],
    "erc_auto_fix_hierarchical": [
        ("kicad_agent_reference.md", "Generating a Netlist"),
        ("kicad_docs.md", "Electrical rules checking"),
        ("kicad_docs.md", "Schematic Creation and Editing"),
    ],
    # PCB ops that need more specific sections
    "auto_place": [
        ("pcb_editor_reference.md", "Working with footprints"),
        ("pcb_editor_reference.md", "Design rules overview"),
    ],
    "move_footprint": [
        ("pcb_editor_reference.md", "Working with footprints"),
        ("kicad_docs.md", "Schematic Setup"),
    ],
    "batch_expand_footprints": [
        ("pcb_editor_reference.md", "Working with footprints"),
    ],
    "fix_silkscreen_over_copper": [
        ("pcb_editor_reference.md", "Graphics and text"),
    ],
    "analyze_split_plane": [
        ("pcb_editor_reference.md", "Working with zones"),
    ],
    "list_design_rules": [
        ("pcb_editor_reference.md", "Design rules overview"),
        ("pcb_editor_reference.md", "Custom rules"),
    ],
    "modify_project_settings": [
        ("pcb_editor_reference.md", "Design rules overview"),
    ],
    "update_from_schematic": [
        ("pcb_editor_reference.md", "Update PCB From Schematic"),
    ],
    "array_replicate": [
        ("kicad_agent_reference.md", "Editing object properties"),
        ("pcb_editor_reference.md", "Arrays"),
    ],
    "duplicate_component": [
        ("kicad_agent_reference.md", "Working with symbols"),
    ],
    "modify_property": [
        ("kicad_agent_reference.md", "Editing object properties"),
    ],
    "swap_symbol": [
        ("kicad_agent_reference.md", "Working with symbols"),
    ],
}

# ---------------------------------------------------------------------------
# Build OP_SECTION_MAP: covers ALL operations from OPERATION_REGISTRY
# ---------------------------------------------------------------------------

OP_SECTION_MAP: dict[str, list[tuple[str, str | None]]] = {}

for _op_type, _meta in OPERATION_REGISTRY.items():
    if _op_type in _PER_OP_OVERRIDES:
        OP_SECTION_MAP[_op_type] = _PER_OP_OVERRIDES[_op_type]
    else:
        OP_SECTION_MAP[_op_type] = _CATEGORY_DEFAULTS.get(_meta.category, [])

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _chunk_by_h2(text: str) -> dict[str, str]:
    """Split markdown text into sections keyed by ## header names.

    Returns dict mapping section title (stripped of ## prefix) to section body.
    Text before the first ## header is ignored.
    NOTE: If a header appears twice, last-wins (second occurrence overwrites first).
    """
    sections: dict[str, str] = {}
    parts = re.split(r'\n(?=## )', text)
    for part in parts:
        if part.startswith("## "):
            lines = part.split("\n", 1)
            title = lines[0][3:].strip()
            body = lines[1] if len(lines) > 1 else ""
            sections[title] = body.strip()
    return sections


def _truncate_section(text: str, max_tokens: int = SECTION_TOKEN_CAP) -> str:
    """Truncate a single section to max_tokens.

    Splits on double-newline boundaries (paragraphs) and takes as many
    complete paragraphs as fit within the budget.
    """
    if not text:
        return text
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o-mini")
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        # Split by paragraph, greedily take complete paragraphs
        paragraphs = re.split(r'\n\n+', text)
        result_tokens: list[int] = []
        for para in paragraphs:
            para_tokens = enc.encode(para)
            if len(result_tokens) + len(para_tokens) > max_tokens:
                break
            result_tokens.extend(para_tokens)
        logger.info(
            "Section truncated from %d to %d tokens (cap=%d)",
            len(tokens), len(result_tokens), max_tokens,
        )
        return enc.decode(result_tokens)
    except Exception:
        # Fallback: ~4 chars per token
        char_budget = max_tokens * 4
        if len(text) <= char_budget:
            return text
        return text[:char_budget]


def _enforce_token_budget(text: str, max_tokens: int) -> str:
    """Truncate combined text to fit within total token budget using tiktoken.

    Individual sections are already capped at SECTION_TOKEN_CAP by
    _truncate_section(). This function handles the case where the sum
    of capped sections still exceeds the total budget.

    Falls back to character-based truncation if tiktoken is unavailable.

    Args:
        text: Knowledge context text to potentially truncate.
        max_tokens: Maximum tokens allowed for the combined output.

    Returns:
        Text truncated to max_tokens, or original if under budget.
    """
    if not text:
        return text
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o-mini")
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        logger.warning(
            "Knowledge context truncated from %d to %d tokens",
            len(tokens), max_tokens,
        )
        return enc.decode(tokens[:max_tokens])
    except Exception:
        # Fallback: ~4 chars per token
        char_budget = max_tokens * 4
        if len(text) <= char_budget:
            return text
        logger.warning(
            "Knowledge context truncated (char fallback) from %d to %d chars",
            len(text), char_budget,
        )
        return text[:char_budget]


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

_default_manager: KnowledgeManager | None = None


def get_context_for_op(op_type: str, file_type: str = "") -> str:
    """Get knowledge context for an operation using the default manager.

    Thread-safe singleton pattern: creates the default KnowledgeManager
    on first call and reuses it for subsequent calls.

    Args:
        op_type: Operation type string (e.g. "add_wire").
        file_type: Optional file type hint (e.g. "kicad_sch", "kicad_pcb").

    Returns:
        Knowledge context string with core rules + relevant sections.
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = KnowledgeManager()
    return _default_manager.get_context_for_op(op_type, file_type)


# ---------------------------------------------------------------------------
# KnowledgeManager class
# ---------------------------------------------------------------------------


class KnowledgeManager:
    """Manages loading, chunking, and injecting KiCad reference knowledge."""

    def __init__(
        self,
        docs_dir: Path | None = None,
        max_tokens: int = 0,  # 0 means read from env var or use default
        disabled: bool = False,
    ) -> None:
        if max_tokens == 0:
            max_tokens = int(os.environ.get("KICAD_KNOWLEDGE_TOKEN_BUDGET", "2000"))
        self._max_tokens = max_tokens
        self._disabled = disabled
        self._docs_dir = docs_dir or self._resolve_docs_dir()
        # doc_name -> {section_name -> body}
        self._sections: dict[str, dict[str, str]] = {}
        # doc_name -> full text (for docs without ## headers)
        self._full_docs: dict[str, str] = {}
        self._loaded = False

    @staticmethod
    def _resolve_docs_dir() -> Path:
        """Resolve docs/ directory relative to project root.

        knowledge.py -> llm/ -> kicad_agent/ -> src/ -> project root
        """
        candidate = Path(__file__).resolve().parent.parent.parent.parent / "docs"
        if candidate.is_dir():
            return candidate
        logger.warning("docs/ directory not found at %s", candidate)
        return Path("/nonexistent")

    def _ensure_loaded(self) -> None:
        """Lazy-load and chunk all reference docs."""
        if self._loaded:
            return
        logger.info("Loading knowledge docs from %s", self._docs_dir)
        for doc_name in DOC_FILES:
            path = self._docs_dir / doc_name
            if not path.exists():
                logger.warning("Knowledge doc not found: %s", path)
                continue
            try:
                text = path.read_text(encoding="utf-8")
                sections = _chunk_by_h2(text)
                if sections:
                    self._sections[doc_name] = sections
                    logger.info("Loaded %d sections from %s", len(sections), doc_name)
                else:
                    # No ## headers (e.g. gerbview_reference.md)
                    self._full_docs[doc_name] = text
                    logger.info("Loaded full doc %s (no ## headers)", doc_name)
            except Exception:
                logger.warning("Failed to load knowledge doc: %s", doc_name, exc_info=True)
        self._loaded = True

        # Validate override section names against loaded docs (warn on mismatches)
        self._validate_override_sections()

    def _validate_override_sections(self) -> None:
        """Log warnings for any section names in overrides that don't exist in loaded docs."""
        all_section_names: set[str] = set()
        for doc_name, sections in self._sections.items():
            all_section_names.update(sections.keys())

        missing: list[tuple[str, str, str]] = []
        seen_pairs: set[tuple[str, str | None]] = set()
        for op_type, mappings in OP_SECTION_MAP.items():
            for doc_name, section_name in mappings:
                key = (doc_name, section_name)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                if (
                    section_name is not None
                    and doc_name in self._sections
                    and section_name not in self._sections[doc_name]
                ):
                    missing.append((op_type, doc_name, section_name))

        if missing:
            # Deduplicate by (doc_name, section_name) for the summary
            missing_pairs: set[tuple[str, str]] = set()
            for _op, doc, sec in missing:
                missing_pairs.add((doc, sec))
            for doc, sec in sorted(missing_pairs):
                logger.warning(
                    "Section %q not found in %s -- check override mappings",
                    sec, doc,
                )

    def get_context_for_op(self, op_type: str, file_type: str = "") -> str:
        """Get relevant knowledge context for an operation.

        Returns core rules + mapped section text. Each section is
        individually capped at SECTION_TOKEN_CAP tokens, and the
        combined output is capped at the total token budget.

        The result is sanitized via ContextBuilder.sanitize() to
        strip injection patterns before injection into LLM prompts.

        Args:
            op_type: Operation type string (e.g. "add_wire").
            file_type: Optional file type hint (e.g. "kicad_sch", "kicad_pcb").

        Returns:
            Knowledge context string, or empty string if disabled.
        """
        if self._disabled:
            return ""

        if not self._loaded:
            logger.info("First knowledge lookup (lazy load)")
        self._ensure_loaded()

        parts: list[str] = [CORE_RULES]

        # Look up mapped sections
        mappings = OP_SECTION_MAP.get(op_type, [])
        # Deduplicate by (doc_name, section_name) pairs
        seen: set[tuple[str, str | None]] = set()
        for doc_name, section_name in mappings:
            key = (doc_name, section_name)
            if key in seen:
                continue
            seen.add(key)
            if section_name is None:
                # Full document injection (e.g. gerbview_reference.md)
                body = self._full_docs.get(doc_name, "")
                if body:
                    body = _truncate_section(body)
                    parts.append(f"\n## {doc_name}\n{body}")
            elif doc_name in self._sections:
                body = self._sections[doc_name].get(section_name, "")
                if body:
                    body = _truncate_section(body)
                    parts.append(f"\n## {section_name}\n{body}")

        combined = "\n".join(parts)
        combined = _enforce_token_budget(combined, self._max_tokens)

        # Sanitize before returning (strip injection patterns)
        from kicad_agent.llm.context_builder import ContextBuilder
        return ContextBuilder.sanitize(combined)
