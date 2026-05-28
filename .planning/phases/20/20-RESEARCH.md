# Phase 20: SFT Data Preparation + Training Infrastructure - Research

**Researched:** 2026-05-27
**Domain:** LLM supervised fine-tuning (SFT) with LoRA on Apple MPS
**Confidence:** HIGH

## Summary

This phase converts the existing 200K synthetic maze reasoning chains (and ~16K real-world samples) into ChatML instruction-following format, quality-filters them using the Phase 9 reward model, and trains a supervised baseline using LoRA on Qwen2.5-1.5B-Instruct. All required libraries (transformers 5.9.0, peft 0.15.2, trl 1.5.0, torch 2.12.0) are already installed and verified working on Apple MPS.

A critical discovery during research: **bitsandbytes is NOT installed**, so 4-bit QLoRA quantization is not available on MPS. However, the 1.5B model is only ~2.9GB in fp16, which fits comfortably on Apple MPS. The phase should use **standard LoRA with fp16** (no quantization) rather than the originally planned QLoRA. This is actually simpler and produces better results than quantized training since no precision is lost.

The smoke test confirmed that `trl.SFTTrainer` + `peft.LoraConfig` works end-to-end on MPS with `fp16=False, bf16=False` (model loaded natively in fp16). Training speed is approximately 20 seconds per step with batch size 1, meaning a full 3-epoch run on 11K samples with batch size 4 should take roughly 2-4 hours.

**Primary recommendation:** Use LoRA (fp16, no quantization) with TRL SFTTrainer on MPS. Load Qwen2.5-1.5B-Instruct in fp16, apply LoRA adapters to attention projection layers (q/k/v/o), train with standard cross-entropy loss on ChatML-formatted data.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Chain-to-ChatML conversion | Python module | - | Pure data transformation, no external services |
| Reward model quality filtering | Python module | - | Uses existing Phase 9 reward model locally |
| HuggingFace LoRA training | Python + MPS | - | Local training on Apple Metal GPU |
| SFT evaluation | Python module | - | Uses existing EvaluationHarness + reward model |
| Training artifact storage | Filesystem | - | JSONL datasets, adapter weights, training config |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| transformers | 5.9.0 | Model loading, tokenization, training infrastructure | HuggingFace standard for LLM fine-tuning [VERIFIED: pip list] |
| peft | 0.15.2 | LoRA adapter configuration and application | Standard parameter-efficient fine-tuning library [VERIFIED: pip list] |
| trl | 1.5.0 | SFTTrainer for supervised fine-tuning | HuggingFace's recommended trainer for SFT [VERIFIED: pip list] |
| torch | 2.12.0 | Tensor operations, MPS backend | PyTorch with Metal Performance Shaders [VERIFIED: pip list] |
| datasets | 4.8.5 | HuggingFace Dataset for efficient data loading | Standard data loading for transformers training [VERIFIED: pip list] |
| accelerate | 1.10.0 | Device management, distributed training | Required by transformers Trainer [VERIFIED: pip list] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sentence-transformers | 5.1.1 | Embedding similarity (optional) | If semantic dedup is needed |
| Qwen2.5-1.5B-Instruct | Auto-downloaded | Base model for fine-tuning | Loaded via transformers AutoModel |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| QLoRA (4-bit) | LoRA (fp16) | No bitsandbytes on MPS; fp16 LoRA is simpler and more accurate for 1.5B model |
| SFTTrainer (TRL) | raw Trainer + DataCollator | SFTTrainer handles ChatML packing, padding, and loss masking automatically |
| MPS training | CPU-only | MPS is 5-10x faster than CPU for training; model fits in fp16 on MPS |

**Installation:**
All libraries are already installed. The `[training]` optional dependency in pyproject.toml needs updating:
```bash
# Current: only torch>=2.0
# Should be:
pip install torch>=2.0 transformers>=4.40 peft>=0.10 trl>=0.10 datasets accelerate
```

**Version verification (already confirmed):**
```
torch==2.12.0, transformers==5.9.0, peft==0.15.2, trl==1.5.0, datasets==4.8.5, accelerate==1.10.0
```

## Architecture Patterns

### System Architecture Diagram

```
training_output/chains_100k.jsonl (200K chains)
training_data_*/train.jsonl (16K multi-source samples)
        |
        v
[1. Chain Converter] -- MazeReasoningChain/BoardData -> ChatML messages
        |                 Applies task-specific prompt templates
        |                 system: "You are a PCB spatial reasoning assistant..."
        |                 user: task prompt (board analysis, routing, etc.)
        |                 assistant: chain_text / content
        |
        v
[2. Quality Filter] -- Load trained reward model from Phase 9
        |                 Score each ChatML sample with predict_reward()
        |                 Sort by composite score (fmt+qual+acc)/3
        |                 Remove bottom 25% -> retain ~11K high-quality
        |
        v
[3. Dataset Builder] -- Split: 80% train / 10% val / 10% test
        |                 HuggingFace Dataset from JSONL
        |                 Tokenize with Qwen2.5 tokenizer
        |
        v
[4. SFT Trainer] ----- Load Qwen2.5-1.5B-Instruct (fp16, device_map=mps)
        |                 Apply LoRA: r=16, alpha=32, targets=[q,k,v,o]_proj
        |                 Train: 3 epochs, lr=2e-4, cosine schedule
        |                 fp16=False, bf16=False (model already fp16)
        |
        v
[5. Evaluator] ------- Generate chains for held-out test samples
        |                 Score with reward model
        |                 Compare SFT vs base model
        |                 Report: avg_reward, discrimination_gap
        |
        v
training_output/sft/
  adapter_config.json
  adapter_model.safetensors
  training_args.json
  eval_report.json
```

### Recommended Project Structure
```
src/kicad_agent/training/
  sft/                     # NEW: SFT training module
    __init__.py            # Module exports
    converter.py           # Chain -> ChatML conversion
    templates.py           # Task-specific prompt templates
    quality_filter.py      # Reward model quality filtering
    trainer.py             # SFTTrainer wrapper + config
    evaluator.py           # SFT evaluation vs baseline
  ...existing modules...   # dataset.py, chains.py, reward_model.py, etc.

training_output/sft/       # Training artifacts
  train.jsonl              # ChatML-formatted training split
  val.jsonl                # ChatML-formatted validation split
  test.jsonl               # ChatML-formatted test split
  adapter_config.json      # LoRA adapter configuration
  adapter_model.safetensors # Trained LoRA weights
  training_args.json       # Reproducible training config
  eval_report.json         # Evaluation metrics

tests/
  test_sft_converter.py    # Conversion tests
  test_sft_templates.py    # Template tests
  test_sft_trainer.py      # Training infrastructure tests
```

### Pattern 1: Chain-to-ChatML Conversion
**What:** Convert MazeReasoningChain objects to ChatML messages format
**When to use:** Every chain that will be used for SFT training
**Example:**
```python
# Source: Verified via transformers AutoTokenizer.apply_chat_template
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct")

messages = [
    {"role": "system", "content": "You are a PCB spatial reasoning assistant. Analyze board layouts using coordinate-grounded reasoning with precise <point x,y> references."},
    {"role": "user", "content": "Analyze the PCB routing problem: Board is 30x30mm with 15 obstacles. Source via at <point 7.5,7.5>, target via at <point 22.5,22.5>."},
    {"role": "assistant", "content": chain.chain_text},
]

# Produces ChatML format:
# <|im_start|>system\n{content}<|im_end|>\n<|im_start|>user\n{content}<|im_end|>\n<|im_start|>assistant\n{content}<|im_end|>
formatted_text = tokenizer.apply_chat_template(messages, tokenize=False)
```

### Pattern 2: LoRA Configuration for Qwen2.5 on MPS
**What:** Standard LoRA config for Qwen2.5-1.5B attention layers
**When to use:** All SFT training runs
**Example:**
```python
# Source: Verified via smoke test on MPS
from peft import LoraConfig, TaskType

lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,                          # Low rank for 1.5B model
    lora_alpha=32,                 # 2x rank (standard scaling)
    lora_dropout=0.05,             # Small dropout for regularization
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],  # Attention only
)
# Result: ~4.4M trainable params (0.28% of total 1.55B)
# Trainable params size: ~8.3 MB in fp16
```

### Pattern 3: MPS-Compatible SFT Training Config
**What:** SFTConfig that works on Apple MPS without errors
**When to use:** All training runs on M-series Macs
**Example:**
```python
# Source: Verified via smoke test -- bf16/fp16 mixed precision flags cause errors on MPS
from trl import SFTConfig

training_args = SFTConfig(
    output_dir="training_output/sft",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.1,
    max_length=512,              # Max token length for chains (~292 tokens typical)
    packing=False,               # Don't pack multiple chains into one sequence
    fp16=False,                  # CRITICAL: Must be False on MPS
    bf16=False,                  # CRITICAL: Must be False on MPS
    logging_steps=10,
    save_strategy="epoch",
    eval_strategy="epoch",
    report_to="none",            # Or "wandb" if tracking
    dataloader_pin_memory=False, # MPS doesn't support pinned memory
)
```

### Anti-Patterns to Avoid
- **Using fp16=True or bf16=True with SFTTrainer on MPS:** The Accelerate library raises ValueError for both on MPS. Load model in fp16 dtype directly instead.
- **Using bitsandbytes for 4-bit quantization on MPS:** bitsandbytes is not installed and only supports CUDA. Use standard LoRA with fp16 instead.
- **Training on all 200K chains:** Most chains are synthetic maze data. Quality-filter first, then use a subset. The 200K chains are ~68% correct, 32% incorrect -- only correct chains should be used for SFT.
- **Tokenizing with the existing ChainTokenizer:** The Phase 9 ChainTokenizer is a custom word-level tokenizer for the reward model. SFT must use the Qwen2.5 BPE tokenizer from transformers.
- **Using device_map="auto" on MPS:** This can cause issues. Use `device_map="mps"` explicitly.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ChatML formatting | Custom string templates | `tokenizer.apply_chat_template()` | Handles special tokens, EOS, BOS correctly per model |
| LoRA training loop | Manual backward + optimizer step | `trl.SFTTrainer` | Handles gradient accumulation, logging, checkpointing, LR scheduling |
| Data collation for CausalLM | Custom collator | `trl.SFTTrainer` default | Correctly handles padding, labels, and loss masking for ChatML |
| Model saving | Manual state_dict save | `trainer.save_model()` | Saves adapter weights + config correctly for peft |
| Train/val split | Custom splitting logic | HuggingFace `Dataset.train_test_split()` | Reproducible, seeded splits |

**Key insight:** TRL's SFTTrainer handles all the complexity of ChatML-based SFT training out of the box. The entire training infrastructure is ~50 lines of config, not a custom training loop.

## Runtime State Inventory

> This is a greenfield phase (new code, no renames). No runtime state inventory needed.

## Common Pitfalls

### Pitfall 1: MPS Mixed Precision Incompatibility
**What goes wrong:** Setting `fp16=True` or `bf16=True` in SFTConfig causes `ValueError: fp16 mixed precision requires a GPU (not 'mps')` or `bf16 mixed precision requires PyTorch >= 1.10 and a supported device.`
**Why it happens:** HuggingFace Accelerate checks for CUDA specifically for mixed precision. MPS is not recognized as a valid device for AMP.
**How to avoid:** Set both `fp16=False` and `bf16=False` in SFTConfig. Load the model with `dtype=torch.float16` via `AutoModelForCausalLM.from_pretrained()`. The model runs in fp16 natively without mixed precision wrappers.
**Warning signs:** Training crashes immediately on `trainer = SFTTrainer(...)` or `trainer.train()`.

### Pitfall 2: Chains Not Filtered by Correctness
**What goes wrong:** Including incorrect chains (32% of chains_100k.jsonl) in SFT training teaches the model to produce invalid reasoning.
**Why it happens:** The chains_100k.jsonl contains both correct and corrupted chains from GRPO contrast generation.
**How to avoid:** Filter chains to `is_correct=True` before conversion. Only correct chains should become assistant responses in ChatML format.
**Warning signs:** SFT model generates incomplete or scrambled reasoning chains.

### Pitfall 3: Data Collator Missing pad_token
**What goes wrong:** Training fails with " pad_token_id is not set" or produces NaN loss.
**Why it happens:** Qwen2.5 models may not have a default pad_token set.
**How to avoid:** Set `tokenizer.pad_token = tokenizer.eos_token` before training.
**Warning signs:** Error during first training step or NaN in loss.

### Pitfall 4: MPS Pinned Memory Warning
**What goes wrong:** `UserWarning: 'pin_memory' argument is set as true but not supported on MPS now`
**Why it happens:** DataLoader defaults to pin_memory=True, which MPS does not support.
**How to avoid:** Set `dataloader_pin_memory=False` in SFTConfig. This is cosmetic (warning only) but clutters logs.
**Warning signs:** Warning message during training, no functional impact.

### Pitfall 5: Reward Model Not Trained
**What goes wrong:** Quality filtering produces near-random scores because the reward model weights are from an untrained state.
**Why it happens:** The Phase 9 pipeline may not have produced a saved reward model, or `load_trained()` is called on an empty directory.
**How to avoid:** Verify reward model files exist at the expected path before filtering. If no trained model exists, the pipeline config has `run_pipeline()` to train one first. Alternatively, use rule-based `score_chain()` as fallback filter.
**Warning signs:** All chains get similar quality scores; bottom-quartile removal is essentially random.

### Pitfall 6: Training Data Format Mismatch
**What goes wrong:** The 7 different training_data_* directories have 4 different schemas (chain format, board graph, component catalog, textbook content). Converting all to ChatML requires different templates per source.
**Why it happens:** Each data source was collected independently with its own schema.
**How to avoid:** Define a separate converter function for each source type. Chain-format data uses spatial reasoning template; board graph data uses board analysis template; component data uses component knowledge template; textbook data uses PCB knowledge Q&A template.
**Warning signs:** Some ChatML entries have malformed user prompts or empty assistant responses.

## Code Examples

### Chain-to-ChatML Conversion (Correct Chains Only)
```python
# Source: Verified via transformers apply_chat_template on Qwen2.5-1.5B-Instruct
from dataclasses import dataclass
from typing import Any
import json

@dataclass(frozen=True)
class ChatMLSample:
    """A single ChatML-formatted training sample."""
    messages: tuple[dict[str, str], ...]
    source: str
    source_id: int
    quality_score: float | None = None

    def to_text(self, tokenizer) -> str:
        """Format using the model's native ChatML template."""
        return tokenizer.apply_chat_template(
            list(self.messages), tokenize=False
        )

SYSTEM_PROMPT_SPATIAL = (
    "You are a PCB spatial reasoning assistant. Analyze board layouts "
    "using coordinate-grounded reasoning. Reference precise positions "
    "using <point x,y> format. Provide structured analysis with "
    "observation, spatial context, coordinate references, diagnosis, "
    "and routing recommendations."
)

TASK_TEMPLATES = {
    "spatial_reasoning": "Perform a spatial analysis of this PCB routing problem:\n{context}",
    "board_analysis": "Analyze the PCB board layout and provide spatial reasoning:\n{context}",
    "routing_assessment": "Assess the routing requirements for this PCB design:\n{context}",
}

def convert_chain_to_chatml(chain_dict: dict[str, Any]) -> ChatMLSample | None:
    """Convert a chain JSON dict to ChatML format.

    Only converts correct chains (is_correct=True).
    Returns None for incorrect chains.
    """
    if not chain_dict.get("is_correct", False):
        return None

    # Build user prompt from chain metadata
    context = chain_dict.get("chain_text", "").split("\n")[0]  # First line = observation
    user_content = TASK_TEMPLATES["spatial_reasoning"].format(context=context)

    return ChatMLSample(
        messages=(
            {"role": "system", "content": SYSTEM_PROMPT_SPATIAL},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": chain_dict["chain_text"]},
        ),
        source="maze_chain",
        source_id=chain_dict["sample_id"],
    )
```

### Quality Filter with Reward Model
```python
# Source: Based on existing reward_model.predict_reward() API [VERIFIED: code read]
from kicad_agent.training.reward_model import RewardModel, predict_reward

def quality_filter_chains(
    chain_texts: list[str],
    model_dir: str,
    keep_fraction: float = 0.75,
) -> list[int]:
    """Score chains with reward model, return indices of top fraction.

    Args:
        chain_texts: List of chain text strings to score.
        model_dir: Path to trained reward model directory.
        keep_fraction: Fraction of chains to keep (0.75 = remove bottom quartile).

    Returns:
        Indices of chains to keep, sorted by quality descending.
    """
    reward_model = RewardModel.load_trained(model_dir, device="auto")

    scores: list[tuple[int, float]] = []
    for i, text in enumerate(chain_texts):
        pred = predict_reward(reward_model, text)
        composite = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
        scores.append((i, composite))

    # Sort by score descending
    scores.sort(key=lambda x: x[1], reverse=True)

    # Keep top fraction
    n_keep = max(1, int(len(scores) * keep_fraction))
    return [idx for idx, _ in scores[:n_keep]]
```

### SFT Training on MPS
```python
# Source: Verified via smoke test on Apple M-series Mac [VERIFIED: executed successfully]
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, TaskType, get_peft_model
from trl import SFTTrainer, SFTConfig
from datasets import Dataset
import torch

# Load model in fp16 directly on MPS (no mixed precision wrapper)
model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen2.5-1.5B-Instruct",
    dtype=torch.float16,
    device_map="mps",
)

tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-1.5B-Instruct")
tokenizer.pad_token = tokenizer.eos_token

# LoRA config: attention projection layers only
lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
)

# Training config for MPS
training_args = SFTConfig(
    output_dir="training_output/sft",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.1,
    max_length=512,
    packing=False,
    fp16=False,  # CRITICAL for MPS
    bf16=False,  # CRITICAL for MPS
    logging_steps=10,
    save_strategy="epoch",
    eval_strategy="epoch",
    report_to="none",
    dataloader_pin_memory=False,
)

# Load ChatML-formatted dataset
dataset = Dataset.from_json("training_output/sft/train.jsonl")
eval_dataset = Dataset.from_json("training_output/sft/val.jsonl")

trainer = SFTTrainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
    eval_dataset=eval_dataset,
    peft_config=lora_config,
)

result = trainer.train()
trainer.save_model("training_output/sft")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| QLoRA (4-bit + LoRA) | Standard LoRA (fp16) for MPS | 2026-05-27 | No bitsandbytes on MPS; fp16 LoRA simpler and more accurate for 1.5B model |
| HuggingFace Trainer + custom DataCollator | TRL SFTTrainer | trl >= 0.7 | SFTTrainer handles ChatML packing, loss masking, padding automatically |
| max_seq_length parameter | max_length parameter | trl >= 1.0 | Parameter renamed in SFTConfig; old name raises TypeError |
| bf16 mixed precision | No mixed precision on MPS | PyTorch MPS backend | MPS doesn't support AMP wrappers; load model in fp16 dtype directly |

**Deprecated/outdated:**
- `SFTConfig(max_seq_length=...)`: Removed in TRL 1.0+, use `max_length` instead [VERIFIED: TypeError in smoke test]
- `device_map="auto"` on single-MPS system: Can cause unexpected device placement; use `device_map="mps"` explicitly

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The 200K chains in chains_100k.jsonl are the primary data source; the 16K samples in training_data_* dirs are supplementary and may use different templates | Architecture | Some samples may not convert cleanly to ChatML; need per-source converters |
| A2 | Only `is_correct=True` chains should be used for SFT (68% = ~136K chains) | Data Prep | Including incorrect chains would teach bad reasoning |
| A3 | The reward model from Phase 9 is either already trained or can be trained using `run_pipeline()` with existing data | Quality Filter | If no trained reward model exists, need to train one first or use rule-based `score_chain()` as fallback |
| A4 | 3 epochs at batch_size=4 on 11K samples will take 2-4 hours on Apple MPS | Training | May be slower on older M-series chips; training speed verified at ~20s/step for batch=1 |
| A5 | Qwen2.5-1.5B-Instruct model is cached locally from previous downloads | Environment | First download is ~3GB; subsequent runs use HF cache |

## Open Questions

1. **Which chains to use for SFT?**
   - What we know: chains_100k.jsonl has 200K entries (136K correct). training_data_* dirs have 16K entries in 4 different formats.
   - What's unclear: Should SFT use only the chain-format data, or also convert board graph / component catalog / textbook data to ChatML?
   - Recommendation: Primary SFT data = correct chains from chains_100k.jsonl (~136K). Secondary enrichment from training_data_* if templates are designed. The 16K samples provide domain diversity but need careful template design per source type.

2. **Is the Phase 9 reward model trained?**
   - What we know: The training pipeline exists and `run_pipeline()` can train it. The training_output/ directory has multiple training runs but no clear "final" reward_model.pt at a known path.
   - What's unclear: Which specific training run produced the best reward model, and where it's saved.
   - Recommendation: Plan should include a step to verify reward model availability. If no trained model exists at a known path, train one using `run_pipeline()` before quality filtering. Fallback: use rule-based `score_chain()` for quality filtering.

3. **Training data volume: how much is enough?**
   - What we know: 136K correct chains available, but quality filtering removes 25% = ~102K. The requirement says "15K chains converted" with "retain ~11K".
   - What's unclear: Whether to use all 102K filtered chains or subsample to ~11K as the roadmap implies.
   - Recommendation: Convert all correct chains, quality-filter, and train on the full filtered set. The "15K" in the roadmap may be a rough estimate. Using more data is better for SFT.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11 | All | Yes | 3.11.11 | - |
| PyTorch (MPS) | Training | Yes | 2.12.0 | CPU (5-10x slower) |
| transformers | Model loading | Yes | 5.9.0 | - |
| peft | LoRA adapters | Yes | 0.15.2 | - |
| trl | SFTTrainer | Yes | 1.5.0 | - |
| datasets | Data loading | Yes | 4.8.5 | - |
| accelerate | Device management | Yes | 1.10.0 | - |
| bitsandbytes | 4-bit quantization | No | - | Use fp16 LoRA instead |
| Qwen2.5-1.5B-Instruct | Base model | Yes (HF cache) | Auto | Downloads on first use (~3GB) |

**Missing dependencies with no fallback:**
- None -- all required libraries are installed and verified.

**Missing dependencies with fallback:**
- bitsandbytes: Not available on MPS. Fallback: use standard LoRA with fp16 (no quantization). This is actually preferred for 1.5B models on MPS since fp16 (~2.9GB) fits in unified memory.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `pytest tests/test_sft_*.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LLM-01 | Chains converted to ChatML with correct format | unit | `pytest tests/test_sft_converter.py -x` | No -- Wave 0 |
| LLM-01 | Task-specific templates applied correctly | unit | `pytest tests/test_sft_templates.py -x` | No -- Wave 0 |
| LLM-02 | Bottom quartile filtered by reward model scores | unit | `pytest tests/test_sft_converter.py::test_quality_filter -x` | No -- Wave 0 |
| LLM-03 | LoRA config valid for Qwen2.5-1.5B on MPS | unit | `pytest tests/test_sft_trainer.py::test_lora_config -x` | No -- Wave 0 |
| LLM-04 | SFT model generates valid chains on test set | integration | `pytest tests/test_sft_trainer.py::test_sft_inference -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_sft_*.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_sft_converter.py` -- covers LLM-01, LLM-02
- [ ] `tests/test_sft_templates.py` -- covers LLM-01 template validation
- [ ] `tests/test_sft_trainer.py` -- covers LLM-03, LLM-04
- [ ] pyproject.toml `[training]` dependency update -- add transformers, peft, trl, datasets, accelerate

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No user auth in training pipeline |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | No multi-user access |
| V5 Input Validation | Yes | Pydantic validation on chain data, JSONL parsing with error handling |
| V6 Cryptography | No | No crypto operations |

### Known Threat Patterns for SFT Training

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Data poisoning (malicious chains) | Tampering | Quality filter + reward model scoring removes anomalous chains |
| Model weight corruption | Tampering | Checksum verification on saved adapters |
| Training data leakage | Information Disclosure | Train/val/test split prevents leakage; JSONL files in .gitignore |

## Sources

### Primary (HIGH confidence)
- transformers 5.9.0 (installed) -- AutoModelForCausalLM, AutoTokenizer, apply_chat_template [VERIFIED: pip list + code execution]
- peft 0.15.2 (installed) -- LoraConfig, TaskType, get_peft_model [VERIFIED: pip list + smoke test]
- trl 1.5.0 (installed) -- SFTTrainer, SFTConfig [VERIFIED: pip list + smoke test]
- torch 2.12.0 (installed) -- MPS backend, float16 support [VERIFIED: pip list + device test]
- Qwen2.5-1.5B-Instruct tokenizer -- ChatML template verified via apply_chat_template [VERIFIED: code execution]
- kicad-agent training module source code -- all existing types and APIs [VERIFIED: file reads]

### Secondary (MEDIUM confidence)
- Smoke test results -- SFTTrainer + LoRA on MPS produces training loss 5.1 over 2 steps [VERIFIED: code execution]
- LoRA parameter count -- 4.36M trainable / 1.55B total = 0.28% [VERIFIED: code execution]
- Chain format from chains_100k.jsonl -- {sample_id, difficulty, chain_text, steps, coordinates_referenced, is_correct, exploration_branches} [VERIFIED: data inspection]

### Tertiary (LOW confidence)
- Training time estimate (2-4 hours) -- extrapolated from 20s/step * batch=1; batch=4 should be faster per sample but exact timing unknown [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries installed and verified working via smoke test
- Architecture: HIGH -- patterns verified by executing code on MPS hardware
- Pitfalls: HIGH -- pitfalls discovered through actual error messages during smoke testing
- Data format: HIGH -- chain JSONL format inspected directly from files

**Research date:** 2026-05-27
**Valid until:** 2026-06-27 (stable -- all dependencies are installed and verified)
