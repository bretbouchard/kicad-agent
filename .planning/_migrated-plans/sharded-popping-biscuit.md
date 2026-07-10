# Plan: Build Unified Vision Dataset from ALL Training Sources

## Context

We're preparing for Gemma 4 12B LoRA training on Kaggle T4 GPUs. The current vision dataset only contains **10,498 synth sweep records** (one JSONL source). There are massive untapped sources:

| Source | Records | Audio? | Current Format | Conversion Needed |
|--------|---------|--------|----------------|-------------------|
| **Synth sweeps** (current) | 10,498 | Generated WAV | Chat JSONL → vision dataset | Already done |
| **Real DSP sweeps** | 14,884 | Synth params (can render) | Raw sweep JSONL (no messages) | Convert to chat, render audio |
| **Mixer FX (synth)** | 40,392 | Synth params (ground_truth) | Chat JSONL, no audio_path | Render from ground_truth |
| **Mixer FX (plugin)** | 1,620 | None (text-only) | Chat JSONL, no audio | Skip — no audio to render |
| **Audio features (voice)** | 50 | Real WAV files on disk | Chat JSONL with audio_path | Already has audio — render spectrogram |
| **Voice/singer audio** | ~690K+ WAVs | Real WAV/FLAC | Raw audio files (no training data) | Full pipeline: analyze → reason → render |
| **Drum/sample audio** | ~11K WAVs | Real WAV | Raw audio files (no training data) | Full pipeline: analyze → reason → render |

**Key insight:** A vision training sample needs TWO things: (1) a spectrogram PNG image, and (2) a reasoning chain response. The existing `build_vision_dataset()` already handles this — it reads chat JSONL, resolves audio files, renders spectrograms, and outputs HuggingFace Dataset.

The bottleneck is: most sources need to go through **sweep → chat JSONL → vision dataset**. Real DSP sweeps and mixer FX data need the `prepare_training_data.py` chat format conversion first. Voice/drum raw audio needs the full `generate_audio_training.py` pipeline.

## Approach: Three-stage pipeline

### Stage 1: Convert raw sources to chat JSONL format

**1A. Real DSP sweeps → chat JSONL** (~14,884 records)
- Use existing `prepare_training_data.py:convert_sample()` which already handles raw sweep records with `reasoning_chain` field
- Records already have `instrument_id`, `params`, `reasoning_chain` — the exact format `convert_sample()` expects
- Run `process_sweep_files([real_dsp_sweep_data], ...)` to produce chat JSONL
- Audio: render from synth params via ScipySynthBackend (same as current synth data)

**1B. Mixer FX synth records → chat JSONL** (~40,392 records)
- These ALREADY have chat format (`messages`, `metadata`, `ground_truth`)
- Audio: render from `ground_truth` params via ScipySynthBackend (same pipeline)
- Filter out the 1,620 non-synth mixer FX records (no audio possible)

**1C. Audio feature records → already in chat JSONL** (50 records)
- Already done in `audio_training_data/train.jsonl`
- Audio: real WAV files at `/Volumes/Storage/voice_data/raw/ChoralSingingDataset/`

### Stage 2: Generate audio training data from real audio files

**2A. Voice/singer data** — massive potential (~690K files)
- Use existing `generate_audio_training.py` pipeline
- Sources: ChoralSingingDataset, cantoria, M4Singer, hifi_tts, vctk, openpop
- Pipeline: WAV → AudioAnalysisService → AudioFeatureSerializer → procedural reasoning chain → chat JSONL
- **Cap at ~5,000-10,000 samples** (train on Kaggle budget, ~50 GPU-hours)
- Mix across singers for diversity

**2B. Drum/sample hits** (~11K files from /Volumes/Storage/samples/)
- Same `generate_audio_training.py` pipeline
- Sources: retro drum-machine, Amen Breaks, the_breaks, mars, packs, etc.
- **Cap at ~3,000-5,000 samples**
- Focus on percussive/transient content the model doesn't see in synth sweeps

### Stage 3: Build unified vision dataset

**3A. Merge all chat JSONL into single file**
- Use existing `prepare_training_data.py:merge_synth_and_audio()` pattern
- Sources: synth_sweep + real_dsp + mixer_fx + audio_feature + voice + drums
- Dedup on assistant content
- N-gram diversity validation

**3B. Build vision dataset from merged JSONL**
- Use existing `vision_data_builder.build_vision_dataset()`
- For synth-based records: render audio from `ground_truth` params (existing `_generate_synth_audio()`)
- For real audio records: render from `audio_path` (existing Strategy 1)
- Output: single HuggingFace Dataset at `output/vision_dataset_full/`

## Implementation

### Files to modify

1. **`scripts/build_full_vision_dataset.py`** (NEW) — orchestrator script that:
   - Converts real DSP sweeps to chat JSONL (calls `prepare_training_data.convert_sample()`)
   - Filters mixer FX synth records, converts non-synth ones where possible
   - Generates audio training from voice data (calls `generate_audio_training` pipeline)
   - Generates audio training from drum/sample data
   - Merges all sources into single chat JSONL
   - Calls `build_vision_dataset()` on the merged JSONL
   - Reports final dataset stats

2. **`src/training/vision_data_builder.py`** (MODIFY) — add support for:
   - Multiple input JSONL files (merge before processing)
   - Mixer FX records where `ground_truth` has synth params but no `audio_path`
   - A source_tag field in output rows so we can track provenance
   - Configurable `max_samples` per source for balanced dataset

3. **`src/training/vision_dataset_config.py`** (NEW) — `FullVisionDatasetConfig` frozen Pydantic model:
   - Per-source paths, caps, and enable flags
   - Audio rendering config (duration, sample rate)
   - Output directory
   - Total dataset size target

### Files to reuse (no changes needed)

- `scripts/prepare_training_data.py` — `convert_sample()` for raw sweep → chat format
- `scripts/generate_audio_training.py` — `convert_sample_to_jsonl()` for audio → chat format
- `src/training/vision_data_builder.py` — `build_vision_dataset()` for JSONL → HuggingFace Dataset
- `src/renderers/linear_spectrogram.py` — `render_linear_spectrogram_png()` for audio → PNG
- `src/synth/backend.py` — `ScipySynthBackend.render()` for params → WAV
- `src/sourcing/audio_feature_prompts.py` — procedural reasoning chain generation

## Dataset size estimates

| Source | Cap | Est. Vision Dataset Size |
|--------|-----|--------------------------|
| Synth sweeps (existing) | 10,498 | ~4.2 GB (current) |
| Real DSP sweeps | 10,000 | ~4 GB |
| Mixer FX synth | 10,000 | ~4 GB |
| Voice/singer | 5,000 | ~2 GB |
| Drum hits | 3,000 | ~1.2 GB |
| Audio features (existing) | 50 | ~20 MB |
| **Total** | **~38,548** | **~15 GB** |

**Kaggle limit is 20GB per dataset.** Caps above ensure we stay under.

## Verification

1. Run `python3 scripts/build_full_vision_dataset.py --dry-run` to verify all sources are reachable
2. Run full build: `python3 scripts/build_full_vision_dataset.py`
3. Verify dataset: `python3 -c "from datasets import load_from_disk; ds = load_from_disk('output/vision_dataset_full'); print(len(ds)); print(ds[0])"`
4. Run existing tests: `python3 -m pytest tests/training/test_vision_data_builder.py -v`
5. Check total size: `du -sh output/vision_dataset_full/`
6. Compress for Kaggle: `zip -r vision_dataset_full.zip output/vision_dataset_full/`
