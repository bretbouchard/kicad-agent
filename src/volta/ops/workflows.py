"""Pre-defined workflow templates for common multi-operation sequences."""

from pydantic import BaseModel


class WorkflowStep(BaseModel):
    op_type: str
    description: str
    required: bool = True


class WorkflowTemplate(BaseModel):
    name: str
    description: str
    steps: list[WorkflowStep]
    file_types: list[str]


WORKFLOW_TEMPLATES: dict[str, WorkflowTemplate] = {
    "fix_erc_errors": WorkflowTemplate(
        name="fix_erc_errors",
        description="Parse, classify, diagnose, and auto-fix ERC violations",
        steps=[
            WorkflowStep(op_type="parse_erc", description="Parse ERC report"),
            WorkflowStep(op_type="classify_violations", description="Classify violation types"),
            WorkflowStep(op_type="diagnose_violations", description="Diagnose root causes"),
            WorkflowStep(op_type="erc_auto_fix", description="Auto-fix what's fixable"),
            WorkflowStep(op_type="validate_schematic", description="Verify fixes"),
        ],
        file_types=[".kicad_sch"],
    ),
    "wire_schematic": WorkflowTemplate(
        name="wire_schematic",
        description="Auto-wire a schematic by resolving pins, detecting collisions, and batch-connecting",
        steps=[
            WorkflowStep(op_type="resolve_pin_positions", description="Resolve all pin coordinates"),
            WorkflowStep(op_type="detect_routing_collisions", description="Find collision zones"),
            WorkflowStep(op_type="detect_pin_overlaps", description="Find overlapping pins"),
            WorkflowStep(op_type="batch_connect", description="Connect all nets", required=True),
            WorkflowStep(op_type="validate_schematic", description="Verify wiring"),
        ],
        file_types=[".kicad_sch"],
    ),
    "add_component_full": WorkflowTemplate(
        name="add_component_full",
        description="Full component addition with symbol embedding and footprint assignment",
        steps=[
            WorkflowStep(op_type="create_symbol", description="Create symbol if needed", required=False),
            WorkflowStep(op_type="embed_symbol", description="Embed symbol in schematic"),
            WorkflowStep(op_type="add_component", description="Place component"),
            WorkflowStep(op_type="assign_footprint", description="Assign footprint"),
        ],
        file_types=[".kicad_sch"],
    ),
    "repair_schematic": WorkflowTemplate(
        name="repair_schematic",
        description="Full schematic repair pipeline",
        steps=[
            WorkflowStep(op_type="parse_erc", description="Parse ERC violations"),
            WorkflowStep(op_type="snap_to_grid", description="Fix off-grid points"),
            WorkflowStep(op_type="remove_dangling_wires", description="Clean up dangling wires"),
            WorkflowStep(op_type="fix_shorted_nets", description="Fix shorted nets"),
            WorkflowStep(op_type="add_power_flag", description="Add missing power flags"),
            WorkflowStep(op_type="place_missing_units", description="Place missing multi-unit components"),
            WorkflowStep(op_type="validate_schematic", description="Final validation"),
        ],
        file_types=[".kicad_sch"],
    ),
    "pcb_setup": WorkflowTemplate(
        name="pcb_setup",
        description="Initial PCB setup with board outline, net classes, and zones",
        steps=[
            WorkflowStep(op_type="create_pcb", description="Create PCB file"),
            WorkflowStep(op_type="set_board_outline", description="Define board shape"),
            WorkflowStep(op_type="add_net_class", description="Add default net classes"),
            WorkflowStep(op_type="add_copper_zone", description="Add ground pour"),
        ],
        file_types=[".kicad_pcb"],
    ),
    "design_review": WorkflowTemplate(
        name="design_review",
        description="Comprehensive design review of a schematic",
        steps=[
            WorkflowStep(op_type="parse_erc", description="Parse ERC results"),
            WorkflowStep(op_type="validate_power_nets", description="Check power connectivity"),
            WorkflowStep(op_type="validate_refs", description="Check reference uniqueness"),
            WorkflowStep(op_type="validate_hlabels", description="Check hierarchical labels"),
            WorkflowStep(op_type="cross_ref_check", description="Verify library references"),
            WorkflowStep(op_type="review_schematic", description="Readability review"),
        ],
        file_types=[".kicad_sch"],
    ),
    "full_pcb_layout": WorkflowTemplate(
        name="full_pcb_layout",
        description="Complete PCB layout pipeline from schematic sync through routing",
        steps=[
            WorkflowStep(op_type="move_footprint", description="Place footprints in layout"),
            WorkflowStep(op_type="add_net_class", description="Set up net classes with design rules", required=False),
            WorkflowStep(op_type="add_copper_zone", description="Add copper zones and ground pours", required=False),
            WorkflowStep(op_type="auto_route", description="Auto-route nets"),
            WorkflowStep(op_type="analyze_split_plane", description="Analyze split plane boundaries", required=False),
        ],
        file_types=[".kicad_pcb"],
    ),
    "route_and_fill": WorkflowTemplate(
        name="route_and_fill",
        description="Analyze routing gaps and fill them via iterative fix loop",
        steps=[
            WorkflowStep(op_type="analyze_gaps", description="Analyze PCB for routing gaps"),
            WorkflowStep(op_type="fill_gaps", description="Fill detected routing gaps"),
        ],
        file_types=[".kicad_pcb"],
    ),
    "convert_legacy_schematic": WorkflowTemplate(
        name="convert_legacy_schematic",
        description="Convert and repair a legacy KiCad 5/6 schematic to KiCad 10",
        steps=[
            WorkflowStep(op_type="convert_kicad6_to_10", description="Convert file format to KiCad 10"),
            WorkflowStep(op_type="snap_to_grid", description="Fix off-grid elements"),
            WorkflowStep(op_type="update_symbols_from_library", description="Re-embed mismatched symbols"),
            WorkflowStep(op_type="parse_erc", description="Parse ERC to find conversion issues"),
            WorkflowStep(op_type="repair_schematic", description="Auto-repair common issues"),
            WorkflowStep(op_type="validate_schematic", description="Verify converted schematic"),
        ],
        file_types=[".kicad_sch"],
    ),
}


def list_workflows() -> list[dict]:
    """Return summary of all available workflows."""
    return [
        {"name": w.name, "description": w.description, "steps": len(w.steps)}
        for w in WORKFLOW_TEMPLATES.values()
    ]


def get_workflow(name: str) -> WorkflowTemplate | None:
    """Get a specific workflow template by name."""
    return WORKFLOW_TEMPLATES.get(name)
