"""Synthetic circuit generator: template + seed -> valid GenerationIntent.

Converts parameterized circuit templates into concrete GenerationIntent
instances suitable for the generate_design() pipeline. Each generated
circuit is validated to ensure correctness.

Usage::

    from kicad_agent.training.synthetic_generator import SyntheticGenerator
    from kicad_agent.training.circuit_templates import get_all_templates

    gen = SyntheticGenerator()
    templates = get_all_templates()
    for t in templates:
        intent = gen.create_intent(t, seed=42)
        print(f"{t.name}: {len(intent.components)} components")
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from kicad_agent.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PositionSpec,
    PowerSpec,
)
from kicad_agent.training.circuit_templates import (
    CircuitTemplate,
    instantiate_template,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SI prefix formatting
# ---------------------------------------------------------------------------


def _format_value(value: float, unit: str = "") -> str:
    """Format a component value with SI prefix.

    Args:
        value: Numeric value (ohms, farads, etc.).
        unit: Unit suffix (e.g. "R" for ohms, "F" for farads).

    Returns:
        Formatted string like "4.7k" or "100nF".
    """
    if value >= 1e6:
        return f"{value / 1e6:.1f}M{unit}"
    elif value >= 1e3:
        return f"{value / 1e3:.1f}k{unit}"
    elif value >= 1:
        return f"{value:.1f}{unit}"
    elif value >= 1e-3:
        return f"{value * 1e3:.1f}m{unit}"
    elif value >= 1e-6:
        return f"{value * 1e6:.1f}u{unit}"
    elif value >= 1e-9:
        return f"{value * 1e9:.1f}n{unit}"
    else:
        return f"{value * 1e12:.1f}p{unit}"


@dataclass(frozen=True)
class GenerationAttempt:
    """Result of a single synthetic circuit generation attempt.

    Attributes:
        intent: The generated GenerationIntent (None if failed).
        template_name: Source template name.
        seed: Random seed used.
        erc_pass: Whether the generated circuit passed ERC (None if not validated).
        circuit_hash: SHA256 hash of the intent for deduplication.
        error: Error message if generation failed.
    """

    intent: GenerationIntent | None
    template_name: str
    seed: int
    erc_pass: bool | None = None
    circuit_hash: str = ""
    error: str = ""


class SyntheticGenerator:
    """Generates valid circuits from parameterized templates.

    Converts CircuitTemplate + seed -> GenerationIntent with:
    1. Parameter sampling from template ranges
    2. Component value formatting with SI prefixes
    3. Net connectivity from template net definitions
    4. Optional ERC validation via generate_design()
    """

    def __init__(
        self,
        board_spec: BoardSpec | None = None,
        power_spec: PowerSpec | None = None,
    ) -> None:
        self._board = board_spec or BoardSpec(
            width_mm=100.0, height_mm=80.0, layer_count=2
        )
        self._power = power_spec or PowerSpec(nets=["GND", "VCC"])

    def create_intent(
        self,
        template: CircuitTemplate,
        seed: int,
    ) -> GenerationIntent:
        """Create a GenerationIntent from a template and seed.

        Args:
            template: Circuit template with parameter ranges.
            seed: Deterministic random seed.

        Returns:
            Validated GenerationIntent ready for generate_design().

        Raises:
            ValueError: If no valid parameter set found for this seed.
        """
        params = instantiate_template(template, seed)

        components = []
        for ct in template.component_templates:
            # Only format numeric params; leave fixed values (like "2N3904") as-is
            try:
                value = ct.value_template.format(**params)
            except KeyError:
                # Template value doesn't use parameters
                value = ct.value_template

            components.append(
                ComponentSpec(
                    library_id=ct.library_id,
                    reference=ct.reference,
                    value=value,
                    position=PositionSpec(
                        x=ct.position_hint[0],
                        y=ct.position_hint[1],
                    ),
                )
            )

        nets = []
        for nt in template.net_templates:
            try:
                name = nt.name.format(**params)
            except KeyError:
                name = nt.name
            nets.append(
                NetSpec(
                    name=name,
                    pins=list(nt.pins),
                )
            )

        return GenerationIntent(
            name=f"synth_{template.name}_s{seed}",
            description=f"Synthetic {template.category}: {template.description}",
            board=self._board,
            components=components,
            nets=nets,
            power=self._power,
        )

    @staticmethod
    def hash_intent(intent: GenerationIntent) -> str:
        """Compute deterministic hash of a GenerationIntent for dedup.

        Uses model_dump_json() for stable serialization.
        """
        data = intent.model_dump_json()
        return hashlib.sha256(data.encode()).hexdigest()

    def generate_batch(
        self,
        template: CircuitTemplate,
        n_samples: int,
        seed_start: int = 0,
        validate: bool = False,
        output_dir: Path | None = None,
    ) -> list[GenerationAttempt]:
        """Generate a batch of circuits from a single template.

        Args:
            template: Circuit template.
            n_samples: Target number of valid circuits.
            seed_start: Starting seed (sequential seeds from here).
            validate: Whether to run ERC validation (slow).
            output_dir: Directory for validation output (required if validate=True).

        Returns:
            List of GenerationAttempt results (includes failures for logging).
        """
        from kicad_agent.generation.pipeline import generate_design

        results: list[GenerationAttempt] = []
        seen_hashes: set[str] = set()
        seed = seed_start
        failures = 0

        while len([r for r in results if r.intent is not None]) < n_samples:
            if failures > n_samples * 2:
                logger.warning(
                    f"Too many failures ({failures}) for template "
                    f"'{template.name}', stopping."
                )
                break

            try:
                intent = self.create_intent(template, seed)
                circuit_hash = self.hash_intent(intent)

                if circuit_hash in seen_hashes:
                    failures += 1
                    seed += 1
                    continue

                erc_pass = None
                if validate and output_dir:
                    result = generate_design(
                        intent,
                        output_dir=output_dir / intent.name,
                        run_validation=True,
                        run_export=False,
                    )
                    erc_pass = result.erc_pass

                    if not result.success:
                        failures += 1
                        seed += 1
                        results.append(
                            GenerationAttempt(
                                intent=None,
                                template_name=template.name,
                                seed=seed,
                                circuit_hash=circuit_hash,
                                error="; ".join(result.errors),
                            )
                        )
                        continue

                seen_hashes.add(circuit_hash)
                results.append(
                    GenerationAttempt(
                        intent=intent,
                        template_name=template.name,
                        seed=seed,
                        erc_pass=erc_pass,
                        circuit_hash=circuit_hash,
                    )
                )

            except (ValueError, Exception) as e:
                failures += 1
                results.append(
                    GenerationAttempt(
                        intent=None,
                        template_name=template.name,
                        seed=seed,
                        error=str(e),
                    )
                )

            seed += 1

        return results


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def attempt_to_dict(attempt: GenerationAttempt) -> dict:
    """Convert GenerationAttempt to JSON-serializable dict.

    Uses model_dump() for the intent field (Pydantic model).
    """
    d: dict = {
        "template_name": attempt.template_name,
        "seed": attempt.seed,
        "erc_pass": attempt.erc_pass,
        "circuit_hash": attempt.circuit_hash,
        "error": attempt.error,
    }
    if attempt.intent is not None:
        d["intent"] = attempt.intent.model_dump()
    else:
        d["intent"] = None
    return d


def dict_to_attempt(d: dict) -> GenerationAttempt:
    """Convert dict back to GenerationAttempt."""
    intent = None
    if d.get("intent") is not None:
        intent = GenerationIntent.model_validate(d["intent"])
    return GenerationAttempt(
        intent=intent,
        template_name=d["template_name"],
        seed=d["seed"],
        erc_pass=d.get("erc_pass"),
        circuit_hash=d.get("circuit_hash", ""),
        error=d.get("error", ""),
    )
