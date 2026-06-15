"""InferenceWrapper -- GRPO model loading, chain generation, board parsing.

Loads the fine-tuned model via LocalLLMClient and the reward model via
RewardModel.load_trained(). Generates N chains per request and returns
the best-scoring one via best_of_n_select.

Chain generation uses ThreadPoolExecutor for concurrent execution (T-22-04:
MPS memory safety -- threads share read-only model weights with per-thread
activations).
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kicad_agent.inference.best_of_n import ScoredChain, best_of_n_select

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
_MAX_N_BEST = 16


@dataclass(frozen=True)
class BoardStats:
    """Extracted board statistics for prompt construction."""

    board_name: str
    n_components: int
    n_nets: int
    n_layers: int
    width_mm: float
    height_mm: float
    file_path: str


class InferenceWrapper:
    """Inference wrapper loading GRPO model + reward model for PCB reasoning.

    Loads the fine-tuned model via LocalLLMClient (GRPO > SFT > HF Hub adapter)
    and the reward model via RewardModel.load_trained(). Generates N chains per
    request and returns the best-scoring one.

    Args:
        model: Base model HuggingFace ID (default: Qwen/Qwen2.5-0.5B-Instruct).
        adapter_dir: LoRA adapter directory (default: auto-detect GRPO > SFT).
        reward_model_dir: Reward model directory (default: training_output/unified).
        n_best: Number of chains to generate for best-of-N selection (default: 4).
        max_tokens: Max generation tokens per chain (default: 1024).
        temperature: Sampling temperature (default: 0.7).
        device: Device for reward model ("auto", "cpu", "mps", "cuda").
    """

    _SYSTEM_PROMPT = (
        "You are a PCB design expert specializing in spatial reasoning. "
        "Analyze boards using coordinate-grounded reasoning with <point x,y> tags. "
        "Provide structured analysis: observation, component analysis, connectivity, "
        "spatial analysis, and routing assessment."
    )

    def __init__(
        self,
        model: str | None = None,
        adapter_dir: str | Path | None = None,
        reward_model_dir: str | Path | None = None,
        n_best: int = 4,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        device: str = "auto",
        max_workers: int | None = None,
        knowledge_manager: Any = None,
    ) -> None:
        if n_best < 1 or n_best > _MAX_N_BEST:
            raise ValueError(f"n_best must be between 1 and {_MAX_N_BEST}, got {n_best}")

        self._model_name = model or os.environ.get(
            "KICAD_LOCAL_MODEL", _DEFAULT_MODEL,
        )
        self._adapter_dir = adapter_dir
        self._reward_model_dir = Path(
            reward_model_dir
            or os.environ.get("KICAD_REWARD_MODEL_DIR", "training_output/unified"),
        )
        self._n_best = n_best
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._device = device
        self._max_workers = max_workers if max_workers is not None else min(n_best, 4)

        # Lazy-loaded on first use
        self._llm_client: Any = None
        self._reward_model: Any = None
        self._models_loaded = False
        self._knowledge_manager = knowledge_manager

    def _load_models(self) -> None:
        """Lazy-load LLM client and reward model on first use."""
        if self._models_loaded:
            return

        from kicad_agent.llm.local_client import LocalLLMClient

        self._llm_client = LocalLLMClient(
            model=self._model_name,
            adapter_dir=self._adapter_dir,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )

        self._reward_model = self._load_reward_model()
        self._models_loaded = True

    def _load_reward_model(self) -> Any:
        """Load reward model from disk. Returns None if not found."""
        try:
            from kicad_agent.training.reward_model import RewardModel

            model_dir = self._reward_model_dir
            if (model_dir / "reward_model.pt").exists():
                return RewardModel.load_trained(model_dir, device=self._device)
        except Exception as exc:
            logger.debug("Reward model not loaded: %s", exc)
        return None

    @staticmethod
    def extract_board_stats(file_path: str | Path) -> BoardStats:
        """Parse a .kicad_pcb or .kicad_sch file and extract board stats.

        Public API for extracting component/net counts and board dimensions
        from a KiCad file without running inference.

        Args:
            file_path: Path to KiCad file.

        Returns:
            BoardStats with component/net counts and dimensions.

        Raises:
            FileNotFoundError: If file_path does not exist.
            ValueError: If file extension is not .kicad_pcb or .kicad_sch.
        """
        return InferenceWrapper._extract_board_stats_impl(file_path)

    @staticmethod
    def _extract_board_stats(file_path: str | Path) -> BoardStats:
        """Parse a .kicad_pcb or .kicad_sch file and extract board stats.

        .. deprecated::
            Use :meth:`extract_board_stats` instead. This private alias is
            kept for backward compatibility.

        Args:
            file_path: Path to KiCad file.

        Returns:
            BoardStats with component/net counts and dimensions.

        Raises:
            FileNotFoundError: If file_path does not exist.
            ValueError: If file extension is not .kicad_pcb or .kicad_sch.
        """
        return InferenceWrapper._extract_board_stats_impl(file_path)

    @staticmethod
    def _extract_board_stats_impl(file_path: str | Path) -> BoardStats:
        """Implementation for board stats extraction.

        Args:
            file_path: Path to KiCad file.

        Returns:
            BoardStats with component/net counts and dimensions.

        Raises:
            FileNotFoundError: If file_path does not exist.
            ValueError: If file extension is not .kicad_pcb or .kicad_sch.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        suffix = path.suffix.lower()
        board_name = path.stem
        n_components = 0
        n_nets = 0
        n_layers = 4
        width_mm = 0.0
        height_mm = 0.0

        if suffix == ".kicad_pcb":
            from kicad_agent.parser.pcb_parser import parse_pcb

            result = parse_pcb(path)
            board = result.kiutils_obj
            n_components = len(board.footprints)
            n_nets = len(board.nets)

            # Try to extract board dimensions from Edge.Cuts
            try:
                from kicad_agent.ir.pcb_ir import PcbIR
                from kicad_agent.parser.uuid_extractor import extract_uuids

                uuid_map = extract_uuids(result.raw_content, "pcb")
                ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
                bounds = ir.get_board_bounds()
                if bounds:
                    width_mm = bounds[2] - bounds[0]
                    height_mm = bounds[3] - bounds[1]
            except Exception:
                pass

        elif suffix == ".kicad_sch":
            from kicad_agent.parser.schematic_parser import parse_schematic

            result = parse_schematic(path)
            sch = result.kiutils_obj
            n_components = len(sch.get_components())
            n_nets = len(sch.get_nets())

        else:
            raise ValueError(
                f"Unsupported file extension: {suffix}. "
                "Expected .kicad_pcb or .kicad_sch"
            )

        return BoardStats(
            board_name=board_name,
            n_components=n_components,
            n_nets=n_nets,
            n_layers=n_layers,
            width_mm=width_mm,
            height_mm=height_mm,
            file_path=str(path),
        )

    def _build_prompt(
        self, stats: BoardStats, knowledge_context: str = ""
    ) -> list[dict[str, str]]:
        """Build chat messages for the fine-tuned model.

        Returns list of {"role": ..., "content": ...} dicts.
        """
        system_content = self._SYSTEM_PROMPT
        if knowledge_context:
            system_content += f"\n\n## KiCad Reference Knowledge\n{knowledge_context}"

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
        ]
        user_content = (
            f"Analyze this PCB board:\n"
            f"Board: {stats.board_name}\n"
            f"Components: {stats.n_components}, Nets: {stats.n_nets}, "
            f"Layers: {stats.n_layers}\n"
            f"Board size: {stats.width_mm:.1f} x {stats.height_mm:.1f} mm\n"
            f"Source: {stats.file_path}\n\n"
            f"Provide a complete spatial reasoning analysis."
        )
        messages.append({"role": "user", "content": user_content})
        return messages

    def _generate_chain(self, messages: list[dict[str, str]]) -> tuple[str, float]:
        """Generate a single chain and return (text, time_seconds).

        Args:
            messages: Chat messages to send to the model.

        Returns:
            Tuple of (generated_text, elapsed_seconds).
        """
        self._load_models()

        start = time.monotonic()
        text = self._llm_client.chat(
            messages,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        elapsed = time.monotonic() - start

        return text, elapsed

    def analyze(self, file_path: str | Path) -> ScoredChain:
        """Analyze a PCB file: parse, generate N chains, score, return best.

        Args:
            file_path: Path to .kicad_pcb or .kicad_sch file.

        Returns:
            ScoredChain with highest reward score.

        Raises:
            FileNotFoundError: If file_path does not exist.
            ValueError: If file is not a valid KiCad file.
        """
        # 1. Extract board stats (validates file existence and extension)
        stats = self._extract_board_stats(file_path)

        # 2. Build prompt (with knowledge context if available)
        knowledge_context = ""
        if self._knowledge_manager is not None:
            knowledge_context = self._knowledge_manager.get_context_for_op("analyze")
        messages = self._build_prompt(stats, knowledge_context=knowledge_context)

        # 3. Generate N chains concurrently via ThreadPoolExecutor
        #    (T-22-04: MPS memory safety -- threads share read-only model weights
        #    with per-thread activations)
        chains: list[str] = [None] * self._n_best  # type: ignore[list-item]
        gen_times: list[float] = [0.0] * self._n_best
        total_start = time.monotonic()

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(self._generate_chain, messages): i
                for i in range(self._n_best)
            }
            for future in as_completed(futures):
                idx = futures[future]
                chain_text, gen_time = future.result()
                chains[idx] = chain_text
                gen_times[idx] = gen_time

        total_elapsed = time.monotonic() - total_start

        # 4. Load models if not already loaded (needed for reward model)
        self._load_models()

        # 5. Score all chains and compute confidence
        from kicad_agent.inference.confidence_scorer import compute_confidence

        all_composite_scores: list[float] = []
        if self._reward_model is not None:
            from kicad_agent.training.reward_model import predict_reward

            for chain_text in chains:
                pred = predict_reward(self._reward_model, chain_text)
                composite = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
                all_composite_scores.append(composite)

        confidence = compute_confidence(all_composite_scores) if all_composite_scores else None

        # 6. Score and select best
        best = best_of_n_select(chains, self._reward_model)

        # Attach generation time and confidence of the winning chain
        winning_idx = chains.index(best.chain_text)
        result = ScoredChain(
            chain_text=best.chain_text,
            format_score=best.format_score,
            quality_score=best.quality_score,
            accuracy_score=best.accuracy_score,
            composite_score=best.composite_score,
            generation_time_s=gen_times[winning_idx],
            confidence=confidence,
        )

        logger.info(
            "Analysis complete: %d chains in %.1fs, best score=%.3f, confidence=%.2f",
            self._n_best,
            total_elapsed,
            result.composite_score,
            result.confidence.overall if result.confidence else 0.0,
        )

        return result


def generate_analysis(
    file_path: str | Path,
    model: str | None = None,
    adapter_dir: str | Path | None = None,
    reward_model_dir: str | Path | None = None,
    n_best: int = 4,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    device: str = "auto",
    knowledge_manager: Any = None,
) -> ScoredChain:
    """One-shot API: analyze a PCB file and return best-scored reasoning chain.

    Convenience function wrapping InferenceWrapper.analyze().

    Args:
        file_path: Path to .kicad_pcb or .kicad_sch file.
        model: Base model (default: auto).
        adapter_dir: LoRA adapter (default: auto-detect).
        reward_model_dir: Reward model dir (default: training_output/unified).
        n_best: Number of chains for best-of-N (default: 4).
        max_tokens: Max tokens per chain (default: 1024).
        temperature: Sampling temperature (default: 0.7).
        device: Device for reward model.
        knowledge_manager: Optional KnowledgeManager for injecting KiCad
            reference knowledge into prompts.

    Returns:
        ScoredChain with highest reward score.

    Usage:
        result = generate_analysis("board.kicad_pcb")
        print(result.chain_text)
        print(f"Score: {result.composite_score:.3f}")
    """
    wrapper = InferenceWrapper(
        model=model,
        adapter_dir=adapter_dir,
        reward_model_dir=reward_model_dir,
        n_best=n_best,
        max_tokens=max_tokens,
        temperature=temperature,
        device=device,
        knowledge_manager=knowledge_manager,
    )
    return wrapper.analyze(file_path)
