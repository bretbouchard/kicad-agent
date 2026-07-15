"""End-to-end validation pipeline for KiCad file mutations.

VAL-03: Net consistency verification between schematic and PCB.
VAL-06: Automated error recovery with rollback on validation failure.

The pipeline enforces: "no invalid file ever reaches disk."

Stages:
  1. Pre-mutation structural validation (fast, no file changes)
  2. Mutation within Transaction context (file-level snapshot)
  3. Post-mutation UUID uniqueness check (fast, in-memory)
  4. Post-mutation ERC/DRC check (slow, calls kicad-cli)
  5. Commit or rollback based on results

If any stage fails, the Transaction auto-rollback restores the original file.

Usage:
    from volta.validation.pipeline import ValidationPipeline

    pipeline = ValidationPipeline()
    result = pipeline.validate_and_apply(
        operation=op,
        ir=schematic_ir,
        mutation_fn=lambda op, ir: None,
        run_erc_check=True,
        run_drc_check=False,
    )
    if result.passed:
        print("Mutation applied and validated")
    else:
        print(f"Rolled back: {result.failure_stage}")
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from volta.validation.erc_drc import run_erc, run_drc, ErcResult, DrcResult
from volta.validation.structural import (
    validate_structural,
    validate_uuid_uniqueness,
    StructuralResult,
)
from volta.ir.base import BaseIR
from volta.ir.transaction import Transaction, TransactionResult
from volta.ops.schema import Operation
from volta.serializer import (
    serialize_schematic,
    serialize_pcb,
    serialize_symbol_lib,
    serialize_footprint,
)
from volta.serializer.normalizer import normalize_kicad_output

logger = logging.getLogger(__name__)


class PipelineStage(str, Enum):
    """Stages in the validation pipeline."""

    STRUCTURAL_PRE = "structural_pre"
    MUTATION = "mutation"
    UUID_UNIQUENESS = "uuid_uniqueness"
    ERC = "erc"
    DRC = "drc"
    COMMIT = "commit"


@dataclass(frozen=True)
class StageResult:
    """Result of a single pipeline stage."""

    stage: PipelineStage
    passed: bool
    detail: str = ""  # Human-readable description of what happened


@dataclass(frozen=True)
class PipelineResult:
    """Result of the full validation pipeline.

    VAL-06: If any stage fails, rollback is automatic and this result
    captures which stage failed and why.
    """

    passed: bool
    stages: tuple[StageResult, ...] = ()
    structural_result: Optional[StructuralResult] = None
    uuid_uniqueness_result: Optional[StructuralResult] = None
    erc_result: Optional[ErcResult] = None
    drc_result: Optional[DrcResult] = None
    transaction_result: Optional[TransactionResult] = None
    failure_stage: Optional[PipelineStage] = None
    rolled_back: bool = False
    target_file: Optional[Path] = None

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    @property
    def failure_reason(self) -> str:
        """Human-readable description of why the pipeline failed."""
        if self.passed:
            return ""
        if self.failure_stage:
            for s in self.stages:
                if s.stage == self.failure_stage and not s.passed:
                    return s.detail
        return "Unknown failure"


class ValidationPipeline:
    """End-to-end validation pipeline for KiCad mutations.

    VAL-06: Automatic error recovery via Transaction rollback.

    The pipeline executes stages in order:
    1. Structural pre-check (validate operation against IR state)
    2. Mutation (applied within Transaction context)
    3. UUID uniqueness check (post-mutation)
    4. Serialize mutated IR to disk (so ERC/DRC sees post-mutation state)
    5. ERC check (if run_erc=True, post-mutation)
    6. DRC check (if run_drc=True, post-mutation)
    7. Commit (if all checks pass)

    Any failure triggers Transaction rollback.
    """

    def __init__(
        self,
        *,
        erc_timeout: int = 120,
        drc_timeout: int = 300,
        check_schematic_parity: bool = True,
    ):
        self._erc_timeout = erc_timeout
        self._drc_timeout = drc_timeout
        self._check_schematic_parity = check_schematic_parity

    @staticmethod
    def _serialize_ir_to_disk(ir: BaseIR, file_path: Path) -> None:
        """Serialize mutated IR to disk so ERC/DRC validates post-mutation state.

        Council H-1 fix: Before running ERC/DRC via kicad-cli, the mutated IR
        must be written to disk. The Transaction snapshot preserves the original
        for rollback if validation fails.
        """
        serializer_map = {
            "schematic": serialize_schematic,
            "pcb": serialize_pcb,
            "symbol_lib": serialize_symbol_lib,
            "footprint": serialize_footprint,
        }
        serializer = serializer_map.get(ir.file_type)
        if serializer is None:
            raise ValueError(f"No serializer for file_type={ir.file_type!r}")

        serializer(ir._parse_result, file_path)
        # Normalize the written file in-place
        content = file_path.read_text(encoding="utf-8")
        normalized = normalize_kicad_output(content)
        file_path.write_text(normalized, encoding="utf-8")

    def _fail(
        self,
        stages: list[StageResult],
        stage: PipelineStage,
        detail: str,
        *,
        structural_result: Optional[StructuralResult] = None,
        uuid_uniqueness_result: Optional[StructuralResult] = None,
        erc_result: Optional[ErcResult] = None,
        drc_result: Optional[DrcResult] = None,
        rolled_back: bool = False,
        target_file: Optional[Path] = None,
    ) -> PipelineResult:
        """Build a failed PipelineResult with a stage failure entry."""
        stages.append(StageResult(stage=stage, passed=False, detail=detail))
        return PipelineResult(
            passed=False,
            stages=tuple(stages),
            structural_result=structural_result,
            uuid_uniqueness_result=uuid_uniqueness_result,
            erc_result=erc_result,
            drc_result=drc_result,
            failure_stage=stage,
            rolled_back=rolled_back,
            target_file=target_file,
        )

    def validate_and_apply(
        self,
        operation: Operation,
        ir: BaseIR,
        *,
        mutation_fn: Callable[[Operation, BaseIR], None],
        run_erc_check: bool = False,
        run_drc_check: bool = False,
    ) -> PipelineResult:
        """Run the full validation pipeline: structural -> mutate -> validate -> commit/rollback.

        Args:
            operation: The validated operation intent.
            ir: The current IR state for the target file.
            mutation_fn: Function that applies the mutation to the IR.
                Receives (operation, ir). Must NOT write to disk (Transaction handles that).
            run_erc_check: Whether to run ERC after mutation (.kicad_sch only).
            run_drc_check: Whether to run DRC after mutation (.kicad_pcb only).

        Returns:
            PipelineResult with pass/fail status and all stage results.
            If failed, rollback is automatic and rolled_back=True.
        """
        stages: list[StageResult] = []
        structural_result: Optional[StructuralResult] = None
        uuid_result: Optional[StructuralResult] = None
        erc_result: Optional[ErcResult] = None
        drc_result: Optional[DrcResult] = None
        txn_result: Optional[TransactionResult] = None
        target_file = Path(ir.file_path) if ir.file_path else None

        # Stage 1: Structural pre-check
        structural_result = validate_structural(operation, ir)
        if not structural_result.passed:
            return self._fail(
                stages,
                PipelineStage.STRUCTURAL_PRE,
                f"Structural validation failed: {structural_result.error_count} violation(s)",
                structural_result=structural_result,
                target_file=target_file,
            )
        stages.append(
            StageResult(stage=PipelineStage.STRUCTURAL_PRE, passed=True, detail="Structural pre-check passed")
        )

        # Stage 2: Mutation within Transaction
        file_path = Path(ir.file_path)
        try:
            with Transaction(file_path) as txn:
                # Apply mutation (modifies IR in-memory)
                mutation_fn(operation, ir)

                # Serialize mutated IR to disk so UUID check and kicad-cli
                # validate post-mutation state (Council H-1)
                self._serialize_ir_to_disk(ir, file_path)

                # Stage 3: UUID uniqueness check (post-mutation, post-serialize)
                uuid_result = validate_uuid_uniqueness(ir)
                if not uuid_result.passed:
                    return self._fail(
                        stages,
                        PipelineStage.UUID_UNIQUENESS,
                        f"UUID uniqueness violated: {uuid_result.error_count} duplicate(s)",
                        structural_result=structural_result,
                        uuid_uniqueness_result=uuid_result,
                        rolled_back=True,
                        target_file=target_file,
                    )
                stages.append(
                    StageResult(stage=PipelineStage.UUID_UNIQUENESS, passed=True, detail="UUID uniqueness verified")
                )

                # Stage 4: ERC check (schematic only)
                if run_erc_check and ir.file_type == "schematic":
                    erc_result = run_erc(file_path, timeout=self._erc_timeout)
                    if not erc_result.passed:
                        return self._fail(
                            stages,
                            PipelineStage.ERC,
                            f"ERC failed: {erc_result.error_count} error(s), {erc_result.warning_count} warning(s)",
                            structural_result=structural_result,
                            uuid_uniqueness_result=uuid_result,
                            erc_result=erc_result,
                            rolled_back=True,
                            target_file=target_file,
                        )
                    stages.append(
                        StageResult(stage=PipelineStage.ERC, passed=True, detail=f"ERC passed ({erc_result.warning_count} warnings)")
                    )

                # Stage 5: DRC check (PCB only)
                if run_drc_check and ir.file_type == "pcb":
                    drc_result = run_drc(
                        file_path,
                        timeout=self._drc_timeout,
                        check_schematic_parity=self._check_schematic_parity,
                    )
                    if not drc_result.passed:
                        return self._fail(
                            stages,
                            PipelineStage.DRC,
                            f"DRC failed: {drc_result.error_count} error(s), {len(drc_result.unconnected_items)} unconnected",
                            structural_result=structural_result,
                            uuid_uniqueness_result=uuid_result,
                            drc_result=drc_result,
                            rolled_back=True,
                            target_file=target_file,
                        )
                    stages.append(
                        StageResult(stage=PipelineStage.DRC, passed=True, detail=f"DRC passed ({drc_result.warning_count} warnings)")
                    )

                # Stage 6: Commit
                txn_result = txn.commit()
                stages.append(
                    StageResult(stage=PipelineStage.COMMIT, passed=True, detail="Transaction committed")
                )

        except Exception as e:
            logger.error("Pipeline exception: %s", e)
            return self._fail(
                stages,
                PipelineStage.MUTATION,
                f"Mutation failed: {e}",
                rolled_back=True,
                target_file=target_file,
            )

        return PipelineResult(
            passed=True,
            stages=tuple(stages),
            structural_result=structural_result,
            uuid_uniqueness_result=uuid_result,
            erc_result=erc_result,
            drc_result=drc_result,
            transaction_result=txn_result,
            target_file=target_file,
        )

    def verify_net_consistency(
        self, pcb_path: Path,
        schematic_path: Optional[Path] = None,
    ) -> DrcResult:
        """Verify net consistency between schematic and PCB (VAL-03).

        Runs DRC with --schematic-parity flag. kicad-cli discovers the
        schematic from the project context automatically; schematic_path
        is accepted for API clarity but not passed to kicad-cli.

        Args:
            pcb_path: Path to the .kicad_pcb file.
            schematic_path: Path to the .kicad_sch file (unused, for API clarity).

        Returns:
            DrcResult with schematic_parity field populated.
            If schematic_parity is empty, nets are consistent.
        """
        return run_drc(
            pcb_path,
            check_schematic_parity=True,
            timeout=self._drc_timeout,
        )
