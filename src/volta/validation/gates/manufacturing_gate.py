"""Manufacturing readiness gate — final gate before fabrication.

ManufacturingReadinessGate validates all manufacturing prerequisites:
1. Clean DRC (no errors)
2. DFM profile pass (zero CRITICAL findings; WARNING/INFO are warnings only)
3. Required export artifacts (Gerbers, drill, BOM, CPL)
4. Layer completeness for fab profile (2-layer vs 4-layer)
5. BOM completeness (MPN/vendor on non-DNP rows)

On pass, generates a ManufacturingManifest with SHA256-hashed artifacts.
On failure, cleans up any partial export directory.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from volta.validation.gate_runner import register_gate
from volta.validation.gate_types import DesignStage, GateDefinition, GateResult
from volta.validation.gates.manufacturing_manifest import (
    ManufacturingArtifact,
    ManufacturingManifest,
    generate_manifest,
)

logger = logging.getLogger(__name__)

# Required layers per fab profile
_2LAYER_LAYERS: frozenset[str] = frozenset({
    "F.Cu", "B.Cu", "F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "Edge.Cuts",
})
_4LAYER_LAYERS: frozenset[str] = _2LAYER_LAYERS | frozenset({"In1.Cu", "In2.Cu"})


class ManufacturingReadinessGate:
    """Validates manufacturing readiness before fabrication.

    Gate context dict requires:
        - "pcb_ir": PcbIR instance
        - "drc_result": DrcResult instance (or None if not yet run)
        - "dfm_report": DfmReport instance (or None if not yet run)
        - "export_artifacts": list of ManufacturingArtifact
        - "export_layers": list[str] — layer names present in Gerber output
        - "fab_profile": str — "2-layer" or "4-layer"
        - "bom_data": list[dict] — BOM rows with MPN/vendor fields
        - "has_mechanical_constraints": bool — whether STEP export is required
    """

    def run(self, context: dict[str, Any]) -> GateResult:
        blockers: list[str] = []
        warnings: list[str] = []
        artifacts_list: list[str] = []

        # Check 1: DRC clean
        drc_blockers = self._check_drc_clean(context)
        blockers.extend(drc_blockers)

        # Check 2: DFM pass
        dfm_blockers, dfm_warnings = self._check_dfm_pass(context)
        blockers.extend(dfm_blockers)
        warnings.extend(dfm_warnings)

        # Check 3: Required exports
        export_blockers = self._check_required_exports(context)
        blockers.extend(export_blockers)

        # Check 4: Layer completeness
        layer_blockers = self._check_layer_completeness(context)
        blockers.extend(layer_blockers)

        # Check 5: BOM completeness
        bom_blockers, bom_warnings = self._check_bom_completeness(context)
        blockers.extend(bom_blockers)
        warnings.extend(bom_warnings)

        # If any blocker, cleanup partial exports and fail
        if blockers:
            export_dir = context.get("export_dir")
            if export_dir:
                self._cleanup_partial_exports(str(export_dir))
            return GateResult(
                pass_=False,
                gate_name="manufacturing_readiness",
                stage=DesignStage.MANUFACTURING,
                blockers=blockers,
                warnings=warnings,
                next_actions=["Fix manufacturing issues and re-run gate"],
            )

        # Generate manifest on pass
        manifest = self._generate_manifest(context)
        manifest_artifacts = [
            f"manifest: {manifest.project_name}/{manifest.board_name}",
            f"artifacts: {len(manifest.artifacts)} files",
            f"bom_rows: {manifest.bom_rows}",
            f"fab_profile: {manifest.fab_profile}",
        ]

        return GateResult(
            pass_=True,
            gate_name="manufacturing_readiness",
            stage=DesignStage.MANUFACTURING,
            artifacts=manifest_artifacts,
            warnings=warnings,
            next_actions=["Proceed to fabrication"],
        )

    @staticmethod
    def _check_drc_clean(context: dict[str, Any]) -> list[str]:
        """Requires clean DRC (no errors)."""
        drc_result = context.get("drc_result")
        if drc_result is None:
            return ["No DRC result in context. Run DRC before manufacturing gate."]
        if not getattr(drc_result, "passed", False):
            return [
                f"DRC failed: {getattr(drc_result, 'error_message', 'unknown error')}"
            ]
        # Check for error-severity violations
        violations = getattr(drc_result, "violations", [])
        error_violations = [
            v for v in violations
            if getattr(getattr(v, "severity", None), "value", "") == "error"
        ]
        if error_violations:
            return [
                f"DRC has {len(error_violations)} error-severity violation(s)"
            ]
        return []

    @staticmethod
    def _check_dfm_pass(context: dict[str, Any]) -> tuple[list[str], list[str]]:
        """DFM pass = zero CRITICAL findings. WARNING/INFO are warnings only."""
        dfm_report = context.get("dfm_report")
        if dfm_report is None:
            return (["No DFM report in context. Run DFM check before manufacturing gate."], [])

        blockers: list[str] = []
        warnings: list[str] = []

        for finding in getattr(dfm_report, "findings", []):
            severity = getattr(finding, "severity", None)
            severity_str = getattr(severity, "value", str(severity))
            description = getattr(finding, "description", "")

            if severity_str == "CRITICAL":
                blockers.append(f"DFM CRITICAL: {description}")
            elif severity_str == "WARNING":
                warnings.append(f"DFM warning: {description}")
            elif severity_str == "INFO":
                warnings.append(f"DFM info: {description}")

        return blockers, warnings

    @staticmethod
    def _check_required_exports(context: dict[str, Any]) -> list[str]:
        """Check required export artifacts exist."""
        artifacts = context.get("export_artifacts", [])
        artifact_names = {a.name if hasattr(a, "name") else str(a) for a in artifacts}

        blockers: list[str] = []
        required = {"gerbers", "drill", "bom", "cpl"}
        for name in sorted(required - artifact_names):
            blockers.append(f"Missing required export artifact: {name}")

        # STEP required only for boards with mechanical constraints
        has_mech = context.get("has_mechanical_constraints", False)
        if has_mech and "step" not in artifact_names:
            blockers.append(
                "Missing required STEP export for board with mechanical constraints"
            )
        elif not has_mech and "step" not in artifact_names:
            # Non-blocking: just note it
            pass

        return blockers

    @staticmethod
    def _check_layer_completeness(context: dict[str, Any]) -> list[str]:
        """Check required layers for fab profile."""
        export_layers = set(context.get("export_layers", []))
        fab_profile = context.get("fab_profile", "2-layer")

        if fab_profile == "4-layer":
            required = _4LAYER_LAYERS
        else:
            required = _2LAYER_LAYERS

        missing = sorted(required - export_layers)
        if missing:
            return [f"Missing layers for {fab_profile} profile: {', '.join(missing)}"]
        return []

    @staticmethod
    def _check_bom_completeness(context: dict[str, Any]) -> tuple[list[str], list[str]]:
        """BOM rows must have MPN/vendor unless DNP/excluded."""
        bom_data = context.get("bom_data", [])
        if not bom_data:
            return ([], [])

        blockers: list[str] = []
        for row in bom_data:
            ref = row.get("Reference", "?")
            value = row.get("Value", "?")
            dnp = str(row.get("DNP", "")).strip().lower()
            excluded = str(row.get("Excluded", "")).strip().lower()

            if dnp in ("yes", "true", "1") or excluded in ("yes", "true", "1"):
                continue

            mpn = str(row.get("MPN", "")).strip()
            vendor = str(row.get("Vendor", "")).strip()
            if not mpn and not vendor:
                blockers.append(
                    f"BOM row {ref} ({value}): missing MPN and Vendor"
                )

        return blockers, []

    @staticmethod
    def _generate_manifest(context: dict[str, Any]) -> ManufacturingManifest:
        """Generate ManufacturingManifest from context."""
        artifacts = context.get("export_artifacts", [])
        fab_profile = context.get("fab_profile", "2-layer")
        bom_data = context.get("bom_data", [])
        board_name = context.get("board_name", "unknown")
        project_name = context.get("project_name", "unknown")

        non_dnp_rows = [
            r for r in bom_data
            if str(r.get("DNP", "")).strip().lower() not in ("yes", "true", "1")
            and str(r.get("Excluded", "")).strip().lower() not in ("yes", "true", "1")
        ]

        return generate_manifest(
            project_name=project_name,
            board_name=board_name,
            fab_profile=fab_profile,
            artifacts=list(artifacts),
            bom_rows=len(non_dnp_rows),
            total_components=len(bom_data),
        )

    @staticmethod
    def _cleanup_partial_exports(export_dir: str) -> None:
        """Delete partial export directory on gate failure."""
        try:
            p = Path(export_dir)
            if p.exists():
                shutil.rmtree(p)
                logger.info("Cleaned up partial export directory: %s", export_dir)
        except Exception as exc:
            logger.warning("Failed to cleanup export directory %s: %s", export_dir, exc)


# ---------------------------------------------------------------------------
# Module-level gate registration
# ---------------------------------------------------------------------------

_gate = ManufacturingReadinessGate()

register_gate(
    GateDefinition(
        name="manufacturing_readiness",
        from_stage=DesignStage.ROUTING,
        to_stage=DesignStage.MANUFACTURING,
        check_fn_name="manufacturing_readiness_gate",
    ),
    check_fn=_gate.run,
)
