"""GRPO Spatial Reasoning Training pipeline.

Phase 9: DeepSeek-style RL training with coordinate-grounded reward signals
on synthetic PCB maze data.

Submodules:

- `dataset`: MazeSample, MazeDataset, generate_dataset()
- `real_dataset`: RealBoardSample, RealBoardDataset, run_pipeline()
- `generator`: parallel generation, adversarial samples
- `chains`: MazeReasoningChain, chain synthesis from maze samples
- `chain_builder`: DFS exploration and chain construction
- `chain_writer`: batch chain writing to JSONL
- `reward`: RewardSignal, ChainReward, score_chain()
- `reward_hacking`: anomaly detection, smooth penalties
- `reward_model`: neural reward model (PyTorch)
- `grpo`: AdvantageWeightedTrainer, AdvantageWeightedConfig (aliases: GRPOTrainer, GRPOConfig)
- `evaluation`: EvalResult, EvaluationHarness
- `pipeline`: TrainingPipelineConfig, run_pipeline()
"""

from kicad_agent.training.real_dataset import (
    RealBoardDataset,
    RealBoardSample,
    run_pipeline,
)
