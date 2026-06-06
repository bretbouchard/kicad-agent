# Phase 63: Training Integrity — Token Handling, Seeding, Reproducibility

## Goal

Fix 4 HIGH-severity training pipeline integrity issues: GitHub token parameter handling (H-11), parallel seed offset race condition (H-12), unseeded random in train_step (H-13), and self-referential best-of-N evaluation (H-14).

## Root Cause Analysis

- **H-11:** GitHub token is passed as a bare string through `run_pipeline()` with minimal validation. It should be validated as a proper GitHub token format and handled via environment variable or secret store.
- **H-12:** All parallel workers receive the same `seed_offset=seed_base`, producing identical or overlapping random sequences. Each worker needs a unique seed offset.
- **H-13:** `train_step()` creates `random.Random()` without a seed, making GRPO training non-reproducible across runs with the same data.
- **H-14:** `RewardModel.generate()` scores its own output using `predict_reward(self, ...)` — the model evaluates its own quality, leading to reward hacking.

## Findings Covered

| ID | Finding | File | Line |
|----|---------|------|------|
| H-11 | GitHub token parameter handling | training/real_dataset.py | 367 |
| H-12 | Parallel seed offset race condition | training/generator.py | 56 |
| H-13 | Unseeded random in train_step | training/grpo.py | 258 |
| H-14 | Self-referential best-of-N picking | training/reward_model.py | 292 |

---

## Plan 63-01: Fix GitHub Token Handling (H-11)

**Target:** `src/kicad_agent/training/real_dataset.py:367-390`

### Step 1: Accept token from environment variable

```python
import os
import re

_GITHUB_TOKEN_RE = re.compile(r"^(ghp_|gho_|github_pat_|ghs_|ghu_)[a-zA-Z0-9]{36,}$")

def _resolve_github_token(token: str | None = None) -> str:
    """Resolve and validate GitHub token.

    Priority: explicit parameter > GITHUB_TOKEN env var.
    """
    resolved = token or os.environ.get("GITHUB_TOKEN")
    if not resolved or not resolved.strip():
        raise ValueError(
            "GitHub token required. Pass as parameter or set GITHUB_TOKEN env var."
        )
    resolved = resolved.strip()
    if not _GITHUB_TOKEN_RE.match(resolved):
        raise ValueError(
            f"Invalid GitHub token format. Expected ghp_/gho_/github_pat_ prefix "
            f"followed by 36+ alphanumeric characters."
        )
    return resolved
```

### Step 2: Update run_pipeline to use resolver

```python
def run_pipeline(
    token: str | None = None,  # Now optional
    staging_dir: Path,
    max_repos: int = 500,
    output_dir: Path | None = None,
) -> RealBoardDataset:
    """End-to-end pipeline: discover -> fetch -> parse -> dedup -> filter."""
    validated_token = _resolve_github_token(token)
    discovery = GithubDiscovery(validated_token)
    ...
```

### Tests

- Test valid `ghp_` token passes validation
- Test invalid token format raises ValueError
- Test missing token + no env var raises ValueError
- Test env var fallback works
- Test whitespace-stripped token validates

---

## Plan 63-02: Fix Parallel Seed Offset (H-12)

**Target:** `src/kicad_agent/training/generator.py:107-151`

### Step 1: Calculate unique seed per worker

Current code:
```python
futures.append(
    executor.submit(
        _generate_chunk,
        chunk_id=worker_id,
        n_samples=actual_chunk_size,
        seed_offset=seed_base,  # BUG: same for all workers
        board_configs=board_configs,
    )
)
```

Fix:
```python
# Each worker gets a non-overlapping seed range
seed_offset = seed_base + worker_id * 1_000_000  # 1M seed space per worker

futures.append(
    executor.submit(
        _generate_chunk,
        chunk_id=worker_id,
        n_samples=actual_chunk_size,
        seed_offset=seed_offset,
        board_configs=board_configs,
    )
)
```

### Step 2: Verify seed uniqueness

Add assertion:
```python
# Before submit loop, verify no overlapping seed ranges
seed_offsets = [seed_base + i * 1_000_000 for i in range(n_workers)]
for i in range(len(seed_offsets)):
    for j in range(i + 1, len(seed_offsets)):
        assert seed_offsets[i] + chunk_size < seed_offsets[j], (
            f"Seed ranges overlap for workers {i} and {j}"
        )
```

### Tests

- Test 4 workers produce 4 different datasets (no duplicates)
- Test reproducibility: same seed_base produces identical results
- Test seed uniqueness assertion passes
- Test 1 worker still works (backward compat)

---

## Plan 63-03: Fix Unseeded Random in train_step (H-13)

**Target:** `src/kicad_agent/training/grpo.py:251-258`

### Step 1: Accept and propagate step seed

```python
class GRPOTrainer:
    def __init__(self, config: GRPOConfig):
        self.config = config
        self._step_counter = 0  # Track step for deterministic seeding

    def train_step(self, batch: list, optimizer: Any = None) -> dict:
        """Execute a single GRPO training step with gradient updates."""
        import random

        # Deterministic seed: global seed + step counter
        step_seed = self.config.seed + self._step_counter
        rng = random.Random(step_seed)
        self._step_counter += 1

        ...  # rest unchanged, uses rng
```

### Step 2: Add seed to GRPOConfig

```python
class GRPOConfig:
    seed: int = 42  # Global seed for reproducibility
    ...
```

### Tests

- Test same seed + same step produces identical rng output
- Test different steps produce different rng output
- Test GRPOConfig defaults seed to 42
- Test step counter increments correctly

---

## Plan 63-04: Fix Self-Referential Best-of-N (H-14)

**Target:** `src/kicad_agent/training/reward_model.py:292-328`

### Step 1: Separate scoring from generation

The fundamental issue: the reward model scores its own output. Fix by using a reference scoring function that doesn't depend on the model being trained:

```python
def generate(self, sample) -> Any:
    """Generate a chain for a sample using best-of-N selection."""
    from kicad_agent.training.chains import (
        synthesize_maze_chain,
        synthesize_corrupted_chain,
    )

    candidates = [synthesize_maze_chain(sample)]
    candidates += [
        synthesize_corrupted_chain(sample, "wrong_coords", rng_seed=sample.seed),
        synthesize_corrupted_chain(sample, "missing_steps", rng_seed=sample.seed + 1),
        synthesize_corrupted_chain(sample, "wrong_order", rng_seed=sample.seed + 2),
        synthesize_corrupted_chain(sample, "vague_reasoning", rng_seed=sample.seed + 3),
    ]

    # Use independent scoring, NOT predict_reward(self, ...)
    best_chain = candidates[0]
    best_score = _independent_score(candidates[0])

    for chain in candidates[1:]:
        score = _independent_score(chain)
        if score > best_score:
            best_score = score
            best_chain = chain

    return best_chain


def _independent_score(chain) -> float:
    """Score a chain using ground-truth metrics, not the model itself.

    Uses format validation + step counting + coordinate accuracy,
    not the reward model's own predictions.
    """
    score = 0.0

    # Format correctness (0-1)
    if hasattr(chain, "chain_text") and chain.chain_text:
        lines = chain.chain_text.strip().split("\n")
        score += min(1.0, len(lines) / 10) * 0.3  # 30% weight: sufficient steps

    # Coordinate accuracy against sample ground truth (0-1)
    # ... (ground truth comparison logic)

    # Reasoning quality heuristic
    score += 0.3  # Base score for valid format

    return score
```

### Step 2: Add option to use frozen reference model

For training runs that want model-based scoring:

```python
def generate(self, sample, reference_model=None) -> Any:
    """Generate chain using best-of-N with external scoring."""
    ...
    scorer = reference_model or _independent_score
    for chain in candidates:
        if reference_model:
            pred = predict_reward(reference_model, chain.chain_text)
            score = (pred.format_score + pred.quality_score + pred.accuracy_score) / 3.0
        else:
            score = _independent_score(chain)
        ...
```

### Tests

- Test `generate()` never calls `predict_reward(self, ...)`
- Test independent scoring produces deterministic results
- Test ground-truth chain scores higher than corrupted chains
- Test reference_model path works when provided
- Test no self-reference even when reference_model=None

---

## Acceptance Criteria

1. GitHub token validated format and accepted from env var
2. Parallel workers receive unique, non-overlapping seed offsets
3. `train_step` uses deterministic seed (global + step counter)
4. Best-of-N scoring uses independent metrics, not self-evaluation
5. All training tests pass
6. Reproducibility test: same seed produces identical output across 2 runs

## Files Modified

- `src/kicad_agent/training/real_dataset.py` — token handling (H-11)
- `src/kicad_agent/training/generator.py` — seed offsets (H-12)
- `src/kicad_agent/training/grpo.py` — deterministic seed (H-13)
- `src/kicad_agent/training/reward_model.py` — independent scoring (H-14)
- New test files per finding

## Dependencies

- None

---
*Plan created: 2026-06-01*
