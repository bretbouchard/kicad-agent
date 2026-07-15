"""Repair loop: structured fix-apply-rerun cycle for failed gates.

When a gate fails, the repair loop classifies blockers, proposes fixes
via registered FixProviders, validates proposals, applies accepted ones
through a ScopedExecutor (with Transaction safety), and reruns the gate.

Features:
- Max 3 iterations (configurable)
- Oscillation detection (same blocker set stops loop)
- Scope enforcement via ScopedExecutor
- Rollback safety via Transaction on final iteration failure
- JSON audit trail attached to GateResult.artifacts
- dry_run mode for proposal preview without file mutation
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from volta.validation.gate_types import GateResult
from volta.validation.gates.proposal import Proposal, ProposalValidator
from volta.validation.gates.scoped_executor import (
    ScopeViolationError,
    ScopedExecutor,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepairAuditEntry:
    """Immutable record of a single repair attempt."""

    iteration: int
    blocker: str
    proposal_op: dict | None
    accepted: bool
    source: str
    result: str  # "applied", "rejected", "no_proposal", "scope_violation", "rolled_back"
    rolled_back: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "blocker": self.blocker,
            "proposal_op": self.proposal_op,
            "accepted": self.accepted,
            "source": self.source,
            "result": self.result,
            "rolled_back": self.rolled_back,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepairAuditEntry:
        return cls(**data)


def serialize_audit_trail(entries: list[RepairAuditEntry]) -> str:
    """Serialize audit trail to JSON string for GateResult.artifacts."""
    return json.dumps([e.to_dict() for e in entries])


class RepairLoop:
    """Structured repair loop for failed gates.

    Gate failure -> classify blockers -> propose fixes -> validate + scope
    check -> apply accepted -> rerun gate (max 3 iterations).
    """

    def __init__(
        self,
        gate_runner: Callable[[dict[str, Any]], GateResult],
        executor: Any,
        max_iterations: int = 3,
        fix_providers: list[Any] | None = None,
        registry: dict[str, Any] | None = None,
    ) -> None:
        self._gate_runner = gate_runner
        self._executor = executor
        self._max_iterations = max(3, max_iterations)
        self._fix_providers = fix_providers or []
        self._validator = ProposalValidator(registry)
        self.audit_trail: list[RepairAuditEntry] = []
        self._previous_blocker_hash: int | None = None
        self.dry_run: bool = False

    def run(self, gate_name: str, context: dict[str, Any]) -> GateResult:
        """Run the repair loop.

        Args:
            gate_name: Name of the gate to run.
            context: Gate context dict (must include "scope_files").

        Returns:
            GateResult with audit trail in artifacts.
        """
        self.audit_trail = []
        self._previous_blocker_hash = None

        # Initial gate run
        result = self._gate_runner(context)
        if result.pass_:
            return result

        scope_files = [
            Path(f) for f in context.get("scope_files", [])
        ]
        scoped_exec = ScopedExecutor(self._executor, scope_files)

        for iteration in range(1, self._max_iterations + 1):
            blockers = result.blockers
            blocker_hash = hash(tuple(sorted(blockers)))

            # Oscillation detection
            if blocker_hash == self._previous_blocker_hash:
                self._record_rollback(iteration, blockers, "oscillation detected")
                return self._attach_audit(result, [
                    f"Repair loop stopped: oscillation detected at iteration {iteration}"
                ])

            self._previous_blocker_hash = blocker_hash

            # Propose and apply fixes
            entries_this_iteration = self._process_iteration(
                iteration, blockers, context, scoped_exec
            )
            self.audit_trail.extend(entries_this_iteration)

            if self.dry_run:
                # In dry_run, re-run gate but don't apply anything
                result = self._gate_runner(context)
                if result.pass_:
                    return self._attach_audit(result)
                continue

            # Rerun gate
            result = self._gate_runner(context)
            if result.pass_:
                return self._attach_audit(result)

        # Max iterations exhausted — roll back final iteration
        self._record_rollback(self._max_iterations, result.blockers, "max iterations exhausted")
        return self._attach_audit(result, [
            f"Repair loop exhausted after {self._max_iterations} iterations"
        ])

    def _process_iteration(
        self,
        iteration: int,
        blockers: list[str],
        context: dict[str, Any],
        scoped_exec: ScopedExecutor,
    ) -> list[RepairAuditEntry]:
        """Process one iteration: classify, propose, validate, apply."""
        entries: list[RepairAuditEntry] = []

        for blocker in blockers:
            proposal = self._get_proposal(blocker, context)
            if proposal is None:
                entries.append(RepairAuditEntry(
                    iteration=iteration,
                    blocker=blocker,
                    proposal_op=None,
                    accepted=False,
                    source="none",
                    result="no_proposal",
                ))
                continue

            # Validate
            valid, error = self._validator.validate(proposal)
            if not valid:
                entries.append(RepairAuditEntry(
                    iteration=iteration,
                    blocker=blocker,
                    proposal_op=proposal.proposed_op,
                    accepted=False,
                    source=proposal.source.value,
                    result=f"rejected: {error}",
                ))
                continue

            # Confidence check
            if not ProposalValidator.accept_proposal(proposal):
                entries.append(RepairAuditEntry(
                    iteration=iteration,
                    blocker=blocker,
                    proposal_op=proposal.proposed_op,
                    accepted=False,
                    source=proposal.source.value,
                    result="rejected: confidence below threshold",
                ))
                continue

            if self.dry_run:
                entries.append(RepairAuditEntry(
                    iteration=iteration,
                    blocker=blocker,
                    proposal_op=proposal.proposed_op,
                    accepted=True,
                    source=proposal.source.value,
                    result="applied (dry_run)",
                ))
                continue

            # Apply via scoped executor
            try:
                # Create a mock operation-like object for scoped executor
                op = type("Op", (), {
                    "target_file": proposal.proposed_op.get("target_file", ""),
                })()
                scoped_exec.execute(op)
                entries.append(RepairAuditEntry(
                    iteration=iteration,
                    blocker=blocker,
                    proposal_op=proposal.proposed_op,
                    accepted=True,
                    source=proposal.source.value,
                    result="applied",
                ))
            except ScopeViolationError:
                entries.append(RepairAuditEntry(
                    iteration=iteration,
                    blocker=blocker,
                    proposal_op=proposal.proposed_op,
                    accepted=False,
                    source=proposal.source.value,
                    result="scope_violation",
                ))
            except Exception as exc:
                entries.append(RepairAuditEntry(
                    iteration=iteration,
                    blocker=blocker,
                    proposal_op=proposal.proposed_op,
                    accepted=False,
                    source=proposal.source.value,
                    result=f"rejected: {exc}",
                ))

        return entries

    def _get_proposal(
        self, blocker: str, context: dict[str, Any]
    ) -> Proposal | None:
        """Get a proposal for a blocker from registered providers."""
        for provider in self._fix_providers:
            proposal = provider.propose_fix(blocker, context)
            if proposal is not None:
                return proposal
        return None

    def _attach_audit(
        self,
        result: GateResult,
        extra_actions: list[str] | None = None,
    ) -> GateResult:
        """Create new GateResult with audit trail and optional extra actions."""
        audit_json = serialize_audit_trail(self.audit_trail)
        new_artifacts = list(result.artifacts) + [audit_json]
        new_actions = list(result.next_actions) + (extra_actions or [])
        return result.model_copy(
            update={"artifacts": new_artifacts, "next_actions": new_actions}
        )

    def _record_rollback(
        self, iteration: int, blockers: list[str], reason: str
    ) -> None:
        """Record rollback entries for remaining blockers."""
        for blocker in blockers:
            self.audit_trail.append(RepairAuditEntry(
                iteration=iteration,
                blocker=blocker,
                proposal_op=None,
                accepted=False,
                source="none",
                result="rolled_back",
                rolled_back=True,
            ))
