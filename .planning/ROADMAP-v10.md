# Volta PCB v10.0 — Swift Port + iOS Expansion Roadmap

## Strategic Goal

Port all Python-dependent functionality to native Swift, eliminating the
daemon entirely. This unlocks:
- iOS/iPadOS support (no subprocess allowed)
- Faster Mac execution (no IPC overhead)
- Smaller app bundle (no 141MB Python runtime)
- True single-codebase cross-platform app

## Model Strategy

### For iPhone/iPad

The Gemma 4 12B adapter cannot run on iPhone (needs 7GB VRAM). Instead:

1. Gemma 3 4B MLX (~2.5 GB) — runs on iPhone 15 Pro+ / iPad Pro M-series
2. Cloud fallback — BYOK providers for devices that can't run local models
3. Apple Intelligence — FoundationModels as zero-cost fallback

### Training Plan (Gemma 3 4B adapter)

- Base: mlx-community/gemma-3-4b-it-4bit
- Training data: existing 47K SKiDL pairs
- LoRA rank: 32, 2000 steps
- Hardware: Vast.ai RTX 4090, ~3 hours, ~$2
- Output: ~50 MB adapter

## Phases

### Phase 221: Swift S-Expression Parser + Schematic IR
Port KiCad file parser from Python to Swift.
- SExpression.swift — recursive descent parser
- SchematicParser.swift — .kicad_sch parser
- SchematicIR.swift — typed schematic model
- SchematicGraph.swift — connectivity graph
- TopologyBuilder.swift — union-find net resolution
- NetClassifier.swift — power/signal classification

### Phase 222: Swift Native ERC/DRC Engine
Port the 18-check validation engine.
- NativeERC.swift — pin conflicts, power, NC, dangling
- NativeDRC.swift — copper, width, courtyard, holes, annular
- NativeDRCAdvanced.swift — net-tie, thermal, diff pair, teardrops
- NativeDRCRunner.swift — unified runner

### Phase 223: Swift PCB Parser + Geometry
Port PCB parser and geometry layer.
- PCBParser.swift — .kicad_pcb parser
- PCBTypes.swift — board data model
- Geometry layer (CGPath or Turf/GEOSwift)

### Phase 224: Swift Operation Registry + Executor
Port the 160-op executor.
- OperationRegistry.swift — op metadata
- OperationExecutor.swift — dispatch + execute
- Raw S-expression writer

### Phase 225: Remove Daemon Dependency
Wire Swift engine in, remove Python daemon.
- Replace ProcessManager with VoltaEngine
- Remove PyInstaller bundle
- App drops from ~150MB to ~15MB

### Phase 226: iPad/iPhone Target
Add iOS build target.
- Shared VoltaPCBCore package
- iPad layout (NavigationSplitView)
- iPhone adaptive layout
- CloudKit sync

### Phase 227: Gemma 3 4B Adapter Training
Train smaller model for iOS.
- Adapt training script for gemma-3-4b
- Rank-32 LoRA, 2000 steps
- MLX conversion + HuggingFace upload

### Phase 228: Batch ERC/DRC Validation Suite
Automated testing against 28K corpus.
- Swift test harness
- Comparison reports
- Regression suite with golden boards

### Phase 229: App Store Submission Polish
Final hardening.
- Privacy manifest
- Screenshots (Mac + iPad)
- Reviewer notes
- Final TestFlight

## Dependency Graph
221 → 222 → 225
221 → 223 → 224 → 225
225 → 226
225 → 227
222 → 228
All → 229
