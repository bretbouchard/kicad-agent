# Volta PCB v11.0 — Better, Faster, Stronger

## 7 Epics (Phase 230-236)

### Phase 230: Train Both Models
- Re-train 12B adapter on full 108K corpus (Vast.ai, ~$3)
- Train 4B iOS adapter (Vast.ai, ~$2)
- Upload both to HuggingFace
- Update ModelDownloader to select model by device capability

### Phase 231: Wire Swift ERC as Primary Validation
- ValidationPanel calls NativeERC.run() directly (no IPC)
- Python native_check stays as macOS-only fallback
- ValidationManager updated to call Swift engine first

### Phase 232: Spatial Index for DRC Performance
- Wire SpatialHash into NativeDRC.checkCopperSpacing()
- Replace O(n²) pairwise with O(n log n) spatial query
- Benchmark on large boards (1000+ segments)

### Phase 233: Swift Schematic SVG Renderer
- New SwiftSVGRenderer conforming to PreviewRenderer
- Render wires, pins, labels, symbols as SVG from SchematicIR
- Works on iOS (no daemon needed)
- Wire into LiquidGlassShell previewRenderer

### Phase 234: 1000-Schematic Swift ERC Batch Test
- Run NativeERC.run() on 1000 schematics from the 28K corpus
- Compare against Python native_erc results
- Generate parity report: pass rate, false positive/negative counts
- Fix any discrepancies

### Phase 235: Complex Op Implementations
- Fully implement the 78 scaffold ops in VoltaEngineRemaining.swift
- Priority: safe_sync_pcb_from_schematic, auto_route, fill_zones,
  match_lengths, place_components_sch
- Each op gets real algorithm implementation

### Phase 236: Vision Input (Camera → Schematic)
- Photo picker for schematic/breadboard images
- Wire KCAttachment images into MLX vision pipeline
- "Snap photo → generate SKiDL" feature
- The adapter was trained multimodal — this activates that capability
