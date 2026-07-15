# Plan: Hard Negatives + 10K Crawl

## Context

Reward model trained on 1,407 real PCB samples achieves 0.22 discrimination gap. The bottleneck is **easy negatives** — all 3 current corruption types are trivially detectable (10-30mm coordinate shifts, 2-step chains with no detail, vague "various components" text). The model learns format discrimination, not PCB reasoning.

We also need more data. Current 1,509 repos yielded 1,407 samples. Targeting 10K discovered repos should yield ~3,000-4,000 samples after pre-filter + parse.

---

## Part 1: Hard Negatives

**File:** `src/volta/training/board_chains.py`

### 5 new corruption functions (after line 381)

1. **`_corrupt_subtle_coord_drift(sample, rng)`** — Shift coordinates 1-3mm toward nearest neighbor's position. Chain looks perfect but coordinates fail the 5mm tolerance check against correct component positions. Tests spatial precision.

2. **`_corrupt_swapped_components(sample, rng)`** — Generate correct chain, swap 2 random components' coordinates. Everything else correct. Tests component identity vs position reasoning.

3. **`_corrupt_wrong_net_count(sample, rng)`** — Full correct chain but perturb net/connection counts by ±20%. Tests factual numerical accuracy.

4. **`_corrupt_plausible_wrong_analysis(sample, rng)`** — Correct coordinates and structure, but swap densest quadrant (Q1→Q3), reverse complexity assessment, demote high-fanout component. Tests analytical reasoning.

5. **`_corrupt_layer_confusion(sample, rng)`** — Correct chain but change layer count to adjacent plausible value (2↔4, 4↔6, 6↔8). Tests PCB domain knowledge.

### Updates to existing functions

- **`synthesize_corrupted_board_chain()`** (line 258): Add 5 new types to dispatch. Weighted random: 60% easy (original 3), 40% hard (new 5).
- **`synthesize_board_chains()`** (line 389): Add `hard_negative_weight: float = 0.4` param, use weighted selection.
- **`_compute_chain_labels()`** (line 427): Extend accuracy scoring with factual checks — parse claimed component/net/layer counts from text and penalize mismatches. Add `_extract_count()` helper using regex.

### CLI

**File:** `scripts/train_real_pcbs.py`
- Add `--corruption-weight` arg (default 0.4), thread to `synthesize_board_chains()`

---

## Part 2: 10K Crawl

**File:** `src/volta/crawler/github_discovery.py`

### Expand curated orgs (line 57)

Add 15+ hardware orgs: `arduino`, `raspberrypi`, `Adafruit`, `SparkFun`, `SeeedStudio`, `foostan`, `ai03-2725`, `perigoso`, `tachyon-da`, `tinkerforge`, `greatscottgadgets`, `mossmann`, `secworks`, `sunzhengwu-kicad`, `XBain`

Uses core API (5000/hr) — basically free in rate-limit terms.

### New: `discover_from_code_search()` method

Uses `self._client.search_code()` with path-based queries (`path:.kicad_pcb`, `filename:kicad_sch`, etc.). Extracts `repository.full_name` from code results. Shares search API rate limit (30/hr). 8 queries = ~16 min.

### New: `discover_from_forks()` method

For popular repos (stars ≥ 10), scan their fork networks via `repo.get_forks()`. Uses core API. Amplification: 100 popular repos × 50 forks = 5,000 additional repos.

### Update `discover_all()` (line 372)

Add new strategies. Reorder for rate-limit efficiency:
1. `curated` (core API, fast)
2. `search` (search API, 30/hr)
3. `topics` (search API)
4. `code_search` (search API)
5. `forks` (core API, amplifies earlier results)

### Bug fix

Line 332: `seen: dict[str, RepoInfo] = []` → `seen: list[RepoInfo] = []` (type hint mismatch)

### CLI

**File:** `scripts/collect_training_data.py`
- Add `"code_search"` and `"forks"` to `--strategy` choices
- Keep `"all"` running everything

---

## Verification

1. Retrain with hard negatives on existing 1,407 samples:
   ```
   python scripts/train_real_pcbs.py --data-dir training_data_v2 \
     --output-dir training_output/reward_hard_neg --n-epochs 20
   ```
   Expected: gap 0.22 → 0.35+

2. Run 10K crawl:
   ```
   python scripts/collect_training_data.py --strategy all --max-repos 10000 \
     --bulk --skip-existing --output-dir training_data_v3
   ```
   Expected: 3,000-4,000 new samples

3. Retrain on combined dataset (~4,500 samples)

4. Per-corruption analysis: model should show differentiated scores on hard negatives
