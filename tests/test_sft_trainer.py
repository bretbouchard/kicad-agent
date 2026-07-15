"""Tests for SFT trainer configuration and evaluator.

Covers:
- LoRA config creation (r=16, alpha=32, target modules)
- SFTConfig MPS compatibility (fp16=False, bf16=False, max_length=512)
- Device auto-detection
- Evaluator returns expected score structure
- Comparison returns delta metrics
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test 1: LoRA config
# ---------------------------------------------------------------------------

def test_lora_config():
    """SFTTrainingConfig creates valid LoraConfig with correct parameters."""
    from volta.training.sft.trainer import SFTTrainingConfig, _build_lora_config

    config = SFTTrainingConfig()
    lora = _build_lora_config(config)

    assert lora.r == 16, f"Expected r=16, got {lora.r}"
    assert lora.lora_alpha == 32, f"Expected alpha=32, got {lora.lora_alpha}"
    assert lora.lora_dropout == 0.05

    target_names = set(lora.target_modules)
    expected = {"q_proj", "k_proj", "v_proj", "o_proj"}
    assert expected == target_names, f"Expected {expected}, got {target_names}"

    from peft import TaskType
    assert lora.task_type == TaskType.CAUSAL_LM


# ---------------------------------------------------------------------------
# Test 2: SFTConfig MPS compatibility
# ---------------------------------------------------------------------------

def test_sft_config_mps_compatible():
    """SFTConfig has fp16=False, bf16=False, dataloader_pin_memory=False, max_length=512."""
    from volta.training.sft.trainer import SFTTrainingConfig, _build_sft_config

    config = SFTTrainingConfig()
    sft_config = _build_sft_config(config)

    assert sft_config.fp16 is False, "fp16 must be False for MPS compatibility"
    assert sft_config.bf16 is False, "bf16 must be False for MPS compatibility"
    assert sft_config.dataloader_pin_memory is False, "pin_memory must be False for MPS"
    assert sft_config.max_length == 512, f"Expected max_length=512, got {sft_config.max_length}"


# ---------------------------------------------------------------------------
# Test 3: Device auto-detection
# ---------------------------------------------------------------------------

def test_device_auto_detection():
    """_get_device returns 'mps' when MPS is available."""
    import torch

    from volta.training.sft.trainer import _get_device, SFTTrainingConfig

    config = SFTTrainingConfig(device="auto")

    # Patch torch methods directly (torch is a real import, not a module-level name)
    with patch.object(torch.cuda, "is_available", return_value=False), \
         patch.object(torch.backends.mps, "is_available", return_value=True):
        device = _get_device(config)
        assert device == "mps"

    # Test CPU fallback
    with patch.object(torch.cuda, "is_available", return_value=False), \
         patch.object(torch.backends.mps, "is_available", return_value=False):
        device = _get_device(config)
        assert device == "cpu"


# ---------------------------------------------------------------------------
# Test 4: evaluate_sft_model returns scores
# ---------------------------------------------------------------------------

def test_evaluate_returns_scores():
    """evaluate_sft_model returns dict with avg_reward and other metrics."""
    from volta.training.sft.evaluator import evaluate_sft_model

    mock_model = MagicMock()
    mock_tokenizer = MagicMock()
    mock_tokenizer.apply_chat_template.return_value = "<|im_start|>system\n<|im_end|><|im_start|>user\ntest<|im_end|><|im_start|>assistant\ngenerated text<|im_end|>"
    mock_tokenizer.return_value = {"input_ids": MagicMock(), "attention_mask": MagicMock()}
    mock_tokenizer.decode.return_value = "Generated PCB analysis with coordinates <point 5.0,10.0>."
    mock_tokenizer.eos_token_id = 2
    mock_tokenizer.pad_token_id = 0

    test_samples = [
        {
            "messages": [
                {"role": "system", "content": "PCB assistant"},
                {"role": "user", "content": "Analyze board"},
                {"role": "assistant", "content": "Board analysis"},
            ],
        },
    ]

    import torch

    with patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=mock_model), \
         patch("transformers.AutoTokenizer.from_pretrained", return_value=mock_tokenizer), \
         patch("peft.PeftModel.from_pretrained", return_value=mock_model), \
         patch("volta.training.sft.evaluator.predict_reward") as mock_pred, \
         patch("volta.training.sft.evaluator.RewardModel") as MockRM, \
         patch("volta.training.sft.evaluator.generate_chain", return_value="Generated PCB text"):

        from volta.training.reward_model import PredictedReward
        mock_pred.return_value = PredictedReward(format_score=0.8, quality_score=0.7, accuracy_score=0.9)
        MockRM.load_trained.return_value = MagicMock()

        result = evaluate_sft_model(
            adapter_path="/fake/adapter",
            test_samples=test_samples,
            reward_model_dir="/fake/reward",
            n_samples=1,
        )

    assert "avg_reward" in result
    assert "avg_format" in result
    assert "avg_quality" in result
    assert "avg_accuracy" in result
    assert "n_samples" in result


# ---------------------------------------------------------------------------
# Test 5: compare_base_vs_sft returns delta
# ---------------------------------------------------------------------------

def test_compare_returns_delta():
    """compare_base_vs_sft returns dict with delta_reward."""
    import tempfile
    from volta.training.sft.evaluator import compare_base_vs_sft

    base_result = {
        "avg_reward": 0.5,
        "avg_format": 0.5,
        "avg_quality": 0.5,
        "avg_accuracy": 0.5,
        "n_samples": 10,
        "sample_outputs": [],
    }
    sft_result = {
        "avg_reward": 0.7,
        "avg_format": 0.7,
        "avg_quality": 0.7,
        "avg_accuracy": 0.7,
        "n_samples": 10,
        "sample_outputs": [],
    }

    # Create a temporary test JSONL file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({
            "messages": [
                {"role": "system", "content": "PCB assistant"},
                {"role": "user", "content": "Analyze board"},
                {"role": "assistant", "content": "Board analysis"},
            ],
        }) + "\n")
        test_path = f.name

    try:
        with patch("volta.training.sft.evaluator.evaluate_sft_model") as mock_eval:
            mock_eval.side_effect = [sft_result, base_result]

            result = compare_base_vs_sft(
                adapter_path="/fake/adapter",
                test_data_path=test_path,
                reward_model_dir="/fake/reward",
                n_samples=10,
            )
    finally:
        Path(test_path).unlink(missing_ok=True)

    assert "delta_reward" in result
    assert result["delta_reward"] > 0, "SFT should improve over base"
    assert "delta_format" in result
    assert "delta_quality" in result
    assert "delta_accuracy" in result
    assert "base_results" in result
    assert "sft_results" in result
