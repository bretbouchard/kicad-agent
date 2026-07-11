"""Manufacturer handoff package orchestrator (Phase 208).

One call (:func:`export_handoff`) produces a complete zip bundle with all
manufacturing artifacts, a readme, and a manifest with DRC/ERC proof of
manufacturability. A pre-handoff validation gate blocks incomplete bundles
(no zip is created on DRC/ERC/vendor-DRC failure).

Threat model mitigations implemented in this module:
  TM-1: ``project_dir`` traversal is rejected by the caller (build.py handler)
        via ``".." in Path(op.project_dir).parts`` before this function is called.
        The build dir is created strictly under ``project_dir / "builds"``.
  TM-2: Zip arcnames are ALWAYS the basename (``artifact_file.name``), never a
        path — prevents zip-slip extraction. See :func:`export_handoff` step 9.
  TM-3: The ``vendor`` field is validated by the Pydantic schema
        (``pattern=r"^[a-z0-9_]+$"``) before reaching here; ``load_profile``
        rejects unknown keys.
  TM-4: The readme is plain markdown built from plain-text values. It is data,
        never a trusted executable context. See :func:`_generate_readme`.
  TM-5: BOM formula injection is handled in ``export_bom_profile`` via
        ``_sanitize_csv_cell``.
  TM-6: The build dir is created with ``mkdir(parents=True, exist_ok=False)``
        under the resolved ``project_dir``; all wrappers receive absolute paths.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kicad_agent.dfm.profiles import ManufacturerProfile, load_profile
from kicad_agent.export.bom import BomResult, export_bom_profile
from kicad_agent.export.general import (
    export_netlist,
    export_position,
    export_schematic_pdf,
    export_step,
    get_board_statistics,
)
from kicad_agent.export.gerber import ExportResult, export_drill, export_gerber
from kicad_agent.export.render import export_pcb_pdf
from kicad_agent.io.atomic_write import atomic_write
from kicad_agent.manufacturing.build import Build
from kicad_agent.manufacturing.board_spec import BoardSpec, load_board_spec
from kicad_agent.validation.gates.manufacturing_manifest import (
    ManufacturingArtifact,
    ManufacturingManifest,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses (PATTERNS FILE 1c)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandoffValidation:
    """Pre-handoff DRC/ERC/vendor DRC results.

    Each ``*_passed`` field is tri-state:
      - ``True``: the check ran and passed.
      - ``False``: the check ran and failed (blocks the handoff).
      - ``None``: inconclusive (kicad-cli absent, no schematic, no vendor).
    """

    drc_passed: bool | None
    erc_passed: bool | None
    vendor_drc_passed: bool | None
    drc_violations: int
    erc_violations: int
    vendor_drc_violations: int


@dataclass(frozen=True)
class HandoffResult:
    """Result of :func:`export_handoff`.

    Attributes:
        success: Whether the handoff zip was produced.
        zip_path: Path to ``handoff.zip`` relative to project_dir (empty on failure).
        manifest: The manufacturing manifest (may be partially populated on failure).
        build: Associated Build record, if any (always None in Phase 208 v1).
        validation: Pre-handoff validation results.
        error_message: Human-readable error detail (empty on success).
    """

    success: bool
    zip_path: str
    manifest: ManufacturingManifest
    build: Build | None
    validation: HandoffValidation
    error_message: str = ""


# ---------------------------------------------------------------------------
# Tri-state mapping helpers (RESEARCH RQ4)
# ---------------------------------------------------------------------------


def _tri_state(passed: bool, error_message: str | None) -> bool | None:
    """Map a result's (passed, error_message) to a tri-state bool.

    - ``error_message`` set -> ``None`` (inconclusive, kicad-cli absent).
    - ``error_message`` is None and ``passed`` -> ``True``.
    - ``error_message`` is None and ``not passed`` -> ``False`` (blocks handoff).
    """
    if error_message is not None:
        return None
    return passed


# ---------------------------------------------------------------------------
# readme.md generation (HANDOFF-04, Task 4)
# ---------------------------------------------------------------------------


def _generate_readme(
    title_block: Any,
    board_spec: BoardSpec | None,
    board_stats: dict,
    validation: HandoffValidation,
    vendor: str | None,
    generated_at: str,
    board_name: str,
    artifacts_for_table: list[tuple[str, int]] | None = None,
) -> str:
    """Build the manufacturing handoff readme as plain markdown.

    TM-4: All values are plain text interpolated into markdown. The readme is
    data, not a trusted executable context — never render it as unescaped HTML.

    Args:
        title_block: NativeTitleBlock (may be None).
        board_spec: BoardSpec sidecar (may be None).
        board_stats: dict from ``get_board_statistics``.
        validation: Pre-handoff validation results.
        vendor: Vendor key or None.
        generated_at: ISO timestamp.
        board_name: Fallback board name (stem) if title_block has no title.
        artifacts_for_table: Optional list of (name, size_bytes) for the
            artifacts table; if None the section is omitted.

    Returns:
        Markdown string.
    """
    title = ""
    rev = ""
    date_str = ""
    company = ""
    if title_block is not None:
        title = getattr(title_block, "title", "") or ""
        rev = getattr(title_block, "rev", "") or ""
        date_str = getattr(title_block, "date", "") or ""
        company = getattr(title_block, "company", "") or ""
    display_name = title or board_name

    def _spec_value(val: Any, label: str) -> str:
        if board_spec is None:
            return "not specified"
        v = getattr(board_spec, label, None)
        if v is None:
            return "not specified"
        # Enum -> value string
        return getattr(v, "value", str(v))

    surface_finish = _spec_value(board_spec, "surface_finish") if board_spec else "not specified"
    copper_outer = f"{board_spec.copper_weight_outer_oz}oz" if board_spec else "not specified"
    copper_inner = f"{board_spec.copper_weight_inner_oz}oz" if board_spec else "not specified"
    soldermask = _spec_value(board_spec, "soldermask_color") if board_spec else "not specified"
    silkscreen = _spec_value(board_spec, "silkscreen_color") if board_spec else "not specified"

    layer_count = board_stats.get("layer_count", "?")
    width = board_stats.get("board_width_mm", 0.0)
    height = board_stats.get("board_height_mm", 0.0)

    def _result_label(val: bool | None) -> str:
        if val is True:
            return "passed"
        if val is False:
            return "failed"
        return "inconclusive"

    lines: list[str] = []
    lines.append(f"# Manufacturing Handoff: {display_name}")
    lines.append("")
    lines.append(f"**Revision:** {rev or 'not specified'}")
    lines.append(f"**Date:** {date_str or 'not specified'}")
    lines.append(f"**Company:** {company or 'not specified'}")
    lines.append(f"**Generated:** {generated_at}")
    lines.append("")

    lines.append("## Board Specifications")
    lines.append(f"- Surface Finish: {surface_finish}")
    lines.append(f"- Copper Weight: {copper_outer} outer / {copper_inner} inner")
    lines.append(f"- Soldermask: {soldermask}")
    lines.append(f"- Silkscreen: {silkscreen}")
    lines.append(f"- Layer Count: {layer_count}")
    lines.append(f"- Dimensions: {width}mm x {height}mm")
    lines.append("")

    # Impedance requirements (omit section if none)
    if board_spec is not None and board_spec.impedance_requirements:
        lines.append("## Impedance Requirements")
        lines.append("")
        lines.append("| Net | Target (ohms) | Reference Layer |")
        lines.append("|-----|---------------|-----------------|")
        for req in board_spec.impedance_requirements:
            lines.append(f"| {req.net_name} | {req.target_ohms} | {req.reference_layer} |")
        lines.append("")

    lines.append("## Validation Results")
    lines.append(
        f"- DRC: {_result_label(validation.drc_passed)} "
        f"({validation.drc_violations} violations)"
    )
    erc_violations_str = str(validation.erc_violations) if validation.erc_passed is not None else "N/A"
    lines.append(
        f"- ERC: {_result_label(validation.erc_passed)} ({erc_violations_str} violations)"
    )
    vendor_label = vendor if vendor else "none"
    lines.append(
        f"- Vendor DRC ({vendor_label}): {_result_label(validation.vendor_drc_passed)}"
    )
    lines.append("")

    # Artifacts table (optional)
    if artifacts_for_table:
        lines.append("## Artifacts")
        lines.append("")
        lines.append("| File | Size (bytes) |")
        lines.append("|------|--------------|")
        for name, size in artifacts_for_table:
            lines.append(f"| {name} | {size} |")
        lines.append("")

    lines.append(f"## Contact")
    lines.append(f"Designed by: {company or 'not specified'}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestrator (HANDOFF-01 through HANDOFF-09)
# ---------------------------------------------------------------------------


def export_handoff(
    pcb_path: Path,
    sch_path: Path | None,
    project_dir: Path,
    vendor: str | None = None,
    include_step: bool = True,
    include_render: bool = False,
    skip_validation: bool = False,
) -> HandoffResult:
    """Produce a complete manufacturer handoff zip bundle.

    Pipeline (11 steps):
      1. Schematic discovery (PCB-only mode if absent).
      2. Parse PCB via NativeParser -> NativeBoard (title_block + vendor DRC).
      3. Pre-handoff validation gate (DRC/ERC/vendor DRC) — NO zip on failure.
      4. Create build directory ``builds/handoff_{timestamp}/``.
      5. Run exports (critical failures block; non-critical tolerated).
      6. Build ManufacturingArtifact records.
      7. Generate readme.md via atomic_write.
      8. Construct + save ManufacturingManifest with validation proof.
      9. Streaming zip (ZIP_DEFLATED, basename-only arcnames — TM-2).
     10. try/except -> rmtree on any failure (no partial state).
     11. Return HandoffResult.

    Args:
        pcb_path: Absolute path to the .kicad_pcb file.
        sch_path: Optional .kicad_sch path; None triggers stem-based discovery.
        project_dir: Project root (build dir created under ``project_dir/builds``).
        vendor: Optional vendor key (jlcpcb, pcbway, etc.) for profile output.
        include_step: Include STEP 3D model (default True).
        include_render: Include PCB render image (default False — slow).
        skip_validation: Skip the pre-handoff DRC/ERC gate.

    Returns:
        HandoffResult. On validation failure, ``success=False`` and NO zip is
        created (HANDOFF-06, Pitfall 5).
    """
    # Lazy imports (kept here so tests can monkeypatch the module-level imports).
    from kicad_agent.parser.pcb_native_parser import NativeParser
    from kicad_agent.validation.erc_drc import run_drc, run_erc
    from kicad_agent.manufacturing.vendor_drc import run_vendor_drc

    stem = pcb_path.stem

    # Step 1: Schematic discovery.
    resolved_sch: Path | None = sch_path
    if resolved_sch is None:
        candidate = pcb_path.with_suffix(".kicad_sch")
        if candidate.is_file():
            resolved_sch = candidate
        else:
            resolved_sch = None  # PCB-only mode

    # Step 2: Parse PCB -> NativeBoard (title_block + vendor DRC geometry).
    board = NativeParser.parse_pcb(pcb_path)
    title_block = getattr(board, "title_block", None)

    # Step 3: Pre-handoff validation gate.
    profile: ManufacturerProfile | None = None
    if vendor:
        try:
            profile = load_profile(vendor)
        except ValueError as exc:
            return HandoffResult(
                success=False,
                zip_path="",
                manifest=_empty_manifest(stem, vendor or "generic"),
                build=None,
                validation=HandoffValidation(None, None, None, 0, 0, 0),
                error_message=f"pre-handoff validation failed: unknown vendor '{vendor}': {exc}",
            )

    drc_passed: bool | None = None
    erc_passed: bool | None = None
    vendor_drc_passed: bool | None = None
    drc_violations = 0
    erc_violations = 0
    vendor_drc_violations = 0

    if not skip_validation:
        # DRC
        drc_result = run_drc(pcb_path)
        drc_passed = _tri_state(drc_result.passed, drc_result.error_message)
        drc_violations = drc_result.error_count if drc_passed is not None else 0

        # ERC (only if schematic present)
        if resolved_sch is not None:
            erc_result = run_erc(resolved_sch)
            erc_passed = _tri_state(erc_result.passed, erc_result.error_message)
            erc_violations = erc_result.error_count if erc_passed is not None else 0
        else:
            erc_passed = None

        # Vendor DRC (only if vendor specified)
        if profile is not None:
            vendor_result = run_vendor_drc(board, profile)
            vendor_drc_passed = _tri_state(
                vendor_result.passed, vendor_result.error_message
            )
            vendor_drc_violations = (
                len(vendor_result.errors) if vendor_drc_passed is not None else 0
            )
        else:
            vendor_drc_passed = None

    validation = HandoffValidation(
        drc_passed=drc_passed,
        erc_passed=erc_passed,
        vendor_drc_passed=vendor_drc_passed,
        drc_violations=drc_violations,
        erc_violations=erc_violations,
        vendor_drc_violations=vendor_drc_violations,
    )

    # Block on any hard False (Pitfall 5). None (inconclusive) does NOT block.
    blockers: list[str] = []
    if drc_passed is False:
        blockers.append("DRC")
    if erc_passed is False:
        blockers.append("ERC")
    if vendor_drc_passed is False:
        blockers.append("vendor DRC")
    if blockers:
        return HandoffResult(
            success=False,
            zip_path="",
            manifest=_empty_manifest(stem, vendor or "generic"),
            build=None,
            validation=validation,
            error_message=f"pre-handoff validation failed: {', '.join(blockers)}",
        )

    # Step 4: Create build dir (handle sub-second timestamp collision).
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    dir_timestamp = now.strftime("%Y%m%d_%H%M%S")
    builds_root = project_dir / "builds"
    builds_root.mkdir(parents=True, exist_ok=True)
    build_dir_name = f"handoff_{dir_timestamp}"
    build_dir = builds_root / build_dir_name
    try:
        build_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        import uuid

        build_dir = builds_root / f"{build_dir_name}_{uuid.uuid4().hex[:8]}"
        build_dir.mkdir(parents=True, exist_ok=False)

    try:
        # Step 5: Run exports.
        artifacts: list[ManufacturingArtifact] = []
        produced_files: list[Path] = []

        def _record_export(
            category: str, result: ExportResult, critical: bool
        ) -> bool:
            """Record an ExportResult. Returns False if a critical export failed."""
            if not result.success:
                msg = f"{category} export failed: {result.stderr}"
                if critical:
                    logger.error(msg)
                    return False
                logger.warning(msg)
                return True
            for f in result.files:
                if f.exists():
                    produced_files.append(f)
                    artifacts.append(
                        ManufacturingArtifact.from_file(
                            name=category, path=str(f), generated_by=result.command
                        )
                    )
            return True

        # Gerbers (critical) — output_dir
        gerber_result = export_gerber(pcb_path, output_dir=build_dir)
        if not _record_export("gerbers", gerber_result, critical=True):
            return _fail_with_cleanup(
                build_dir, stem, vendor or "generic", validation,
                f"critical export failed: gerbers ({gerber_result.stderr})",
            )

        # Drill (critical) — output_dir
        drill_result = export_drill(pcb_path, output_dir=build_dir)
        if not _record_export("drill", drill_result, critical=True):
            return _fail_with_cleanup(
                build_dir, stem, vendor or "generic", validation,
                f"critical export failed: drill ({drill_result.stderr})",
            )

        # Pick-and-place (critical) — output_dir
        cpl_result = export_position(pcb_path, output_dir=build_dir)
        if not _record_export("cpl", cpl_result, critical=True):
            return _fail_with_cleanup(
                build_dir, stem, vendor or "generic", validation,
                f"critical export failed: cpl ({cpl_result.stderr})",
            )

        # BOM (critical if schematic present) — output_dir
        bom_rows = 0
        total_components = 0
        if resolved_sch is not None:
            bom_result = export_bom_profile(resolved_sch, build_dir, profile)
            if not bom_result.success:
                return _fail_with_cleanup(
                    build_dir, stem, vendor or "generic", validation,
                    f"critical export failed: bom ({bom_result.stderr})",
                )
            if bom_result.output_path.exists():
                produced_files.append(bom_result.output_path)
                artifacts.append(
                    ManufacturingArtifact.from_file(
                        name="bom",
                        path=str(bom_result.output_path),
                        generated_by=bom_result.command,
                    )
                )
                bom_rows = bom_result.unique_components
                total_components = bom_result.component_count

        # Netlist (non-critical) — output_dir
        try:
            netlist_result = export_netlist(pcb_path, output_dir=build_dir)
            _record_export("netlist", netlist_result, critical=False)
        except Exception as exc:
            logger.warning("netlist export tolerated failure: %s", exc)

        # STEP (non-critical, optional) — output_path
        if include_step:
            step_output = build_dir / f"{stem}.step"
            try:
                step_result = export_step(pcb_path, output_path=step_output)
                _record_export("step", step_result, critical=False)
            except Exception as exc:
                logger.warning("step export tolerated failure: %s", exc)

        # Schematic PDF (non-critical, if sch) — output_path
        if resolved_sch is not None:
            sch_pdf_output = build_dir / f"{stem}_schematic.pdf"
            try:
                sch_pdf_result = export_schematic_pdf(
                    resolved_sch, output_path=sch_pdf_output
                )
                _record_export("schematic_pdf", sch_pdf_result, critical=False)
            except Exception as exc:
                logger.warning("schematic pdf export tolerated failure: %s", exc)

        # PCB PDF (non-critical) — output_path
        pcb_pdf_output = build_dir / f"{stem}.pdf"
        try:
            pcb_pdf_result = export_pcb_pdf(pcb_path, output_path=pcb_pdf_output)
            _record_export("pcb_pdf", pcb_pdf_result, critical=False)
        except Exception as exc:
            logger.warning("pcb pdf export tolerated failure: %s", exc)

        # Render (non-critical, optional) — not exported in v1 (no render wrapper
        # in the handoff path; include_render reserved for future use).
        # TM-6: all wrappers received absolute build_dir paths.

        # Step 6: (artifacts already built in _record_export).

        # Step 7: Generate readme.md.
        board_spec = load_board_spec(pcb_path)
        try:
            board_stats = get_board_statistics(pcb_path)
        except Exception as exc:
            logger.warning("board statistics unavailable: %s", exc)
            board_stats = {
                "layer_count": "?",
                "board_width_mm": 0.0,
                "board_height_mm": 0.0,
                "component_count": 0,
                "net_count": 0,
            }

        artifact_table = [(a.name, a.size_bytes) for a in artifacts]
        readme_content = _generate_readme(
            title_block=title_block,
            board_spec=board_spec,
            board_stats=board_stats,
            validation=validation,
            vendor=vendor,
            generated_at=generated_at,
            board_name=stem,
            artifacts_for_table=artifact_table,
        )
        readme_path = build_dir / "readme.md"
        atomic_write(readme_path, readme_content)
        produced_files.append(readme_path)

        # Step 8: Construct + save ManufacturingManifest.
        manifest = ManufacturingManifest(
            project_name=stem,
            board_name=(title_block.title if title_block and title_block.title else stem),
            fab_profile=vendor or "generic",
            artifacts=tuple(artifacts),
            bom_rows=bom_rows,
            total_components=total_components,
            generated_at=generated_at,
            drc_passed=drc_passed,
            erc_passed=erc_passed,
            vendor_drc_passed=vendor_drc_passed,
            drc_violation_count=drc_violations,
            erc_violation_count=erc_violations,
        )
        manifest.save(build_dir / "manifest.json")
        produced_files.append(build_dir / "manifest.json")

        # Step 9: Streaming zip (Pitfall 7, TM-2).
        zip_path = build_dir / "handoff.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Arcname is ALWAYS the basename (TM-2 — no path, no zip-slip).
            for artifact_file in build_dir.iterdir():
                if artifact_file.is_file() and artifact_file.name != "handoff.zip":
                    zf.write(artifact_file, arcname=artifact_file.name)

        # Step 11: Return success.
        return HandoffResult(
            success=True,
            zip_path=str(zip_path.relative_to(project_dir)),
            manifest=manifest,
            build=None,
            validation=validation,
            error_message="",
        )
    except Exception as exc:
        # Step 10: no partial state — rmtree the build dir on any failure.
        shutil.rmtree(build_dir, ignore_errors=True)
        logger.warning("export_handoff failed: %s", exc)
        return HandoffResult(
            success=False,
            zip_path="",
            manifest=_empty_manifest(stem, vendor or "generic"),
            build=None,
            validation=validation,
            error_message=f"export_handoff failed: {exc}",
        )


def _empty_manifest(stem: str, fab_profile: str) -> ManufacturingManifest:
    """Build a minimal manifest for early-failure results."""
    return ManufacturingManifest(
        project_name=stem,
        board_name=stem,
        fab_profile=fab_profile,
    )


def _fail_with_cleanup(
    build_dir: Path,
    stem: str,
    fab_profile: str,
    validation: HandoffValidation,
    error_message: str,
) -> HandoffResult:
    """Clean up the build dir and return a failure result (no partial state)."""
    shutil.rmtree(build_dir, ignore_errors=True)
    return HandoffResult(
        success=False,
        zip_path="",
        manifest=_empty_manifest(stem, fab_profile),
        build=None,
        validation=validation,
        error_message=error_message,
    )
