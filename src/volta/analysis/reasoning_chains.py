"""Analysis-layer database for reasoning chains.

Wraps the spatial reasoning chain synthesis from volta.spatial.reasoning_chains
with query, storage, and retrieval capabilities for analysis workflows.

Provides ReasoningChainDB for:
- Storing synthesized reasoning chains by violation type and severity
- Looking up historical chains for similar violations
- Searching chains by coordinate proximity or step content
"""

from __future__ import annotations

from volta.spatial.reasoning_chains import (
    ReasoningChain,
    ReasoningStep,
    synthesize_chains,
)


class ReasoningChainDB:
    """In-memory database of reasoning chains for analysis workflows.

    Stores chains indexed by violation type and severity, enabling
    lookup of historical reasoning patterns for similar violations.
    """

    def __init__(self) -> None:
        self._chains: dict[str, list[ReasoningChain]] = {}

    @property
    def chain_count(self) -> int:
        """Total number of stored chains."""
        return sum(len(v) for v in self._chains.values())

    def add(self, chain: ReasoningChain) -> None:
        """Store a reasoning chain, indexed by violation type."""
        key = chain.violation_type
        if key not in self._chains:
            self._chains[key] = []
        self._chains[key].append(chain)

    def add_many(self, chains: list[ReasoningChain]) -> None:
        """Store multiple reasoning chains at once."""
        for chain in chains:
            self.add(chain)

    def get_by_type(self, violation_type: str) -> tuple[ReasoningChain, ...]:
        """Retrieve all chains for a given violation type."""
        return tuple(self._chains.get(violation_type, []))

    def get_by_severity(self, severity: str) -> tuple[ReasoningChain, ...]:
        """Retrieve all chains matching a severity level."""
        results: list[ReasoningChain] = []
        for chains in self._chains.values():
            results.extend(c for c in chains if c.severity == severity)
        return tuple(results)

    def search_by_content(self, keyword: str) -> tuple[ReasoningChain, ...]:
        """Search chain step content for a keyword substring."""
        results: list[ReasoningChain] = []
        for chains in self._chains.values():
            for chain in chains:
                for step in chain.steps:
                    if keyword.lower() in step.content.lower():
                        results.append(chain)
                        break
        return tuple(results)

    def get_unique_violation_types(self) -> tuple[str, ...]:
        """Return all distinct violation types in the database."""
        return tuple(sorted(self._chains.keys()))

    def clear(self) -> None:
        """Remove all stored chains."""
        self._chains.clear()

    def synthesize_and_store(
        self,
        drc_result: object | None = None,
        erc_result: object | None = None,
        pcb_primitives: list | None = None,
    ) -> tuple[ReasoningChain, ...]:
        """Synthesize chains from DRC/ERC results and store them.

        Convenience method that combines synthesize_chains() with add_many().

        Args:
            drc_result: Optional DRC result with violations.
            erc_result: Optional ERC result with violations.
            pcb_primitives: Optional spatial primitives for context.

        Returns:
            Tuple of newly synthesized and stored chains.
        """
        chains = synthesize_chains(drc_result, erc_result, pcb_primitives)
        self.add_many(chains)
        return tuple(chains)
