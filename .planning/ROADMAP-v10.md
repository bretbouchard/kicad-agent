# Volta PCB v10.0 — Swift Port + iOS Expansion (Council-Reviewed)

## Strategic Goal
Port Python functionality to native Swift, eliminate daemon, add iOS support.

## Council-Corrected Scoping

### Scoped Parity (not full 50K LOC)
Port only the critical path for a functional iOS app:
- S-expression parser ✅ (Phase 221, done)
- Schematic IR + topology ✅ (Phase 221, done)
- ERC/DRC engine (Phase 222, in progress)
- ~30 critical ops: add/remove/modify component, wire, label, query, validate
- Leave remaining ~130 ops daemon-backed on Mac only

### Geometry Strategy
Implement 4 operations natively in Swift (~2000 LOC):
- LineString.buffer(width) → polygon
- Polygon.intersection(other).area
- Point/Box distance queries
- Simple spatial hash (replaces STRtree for <10K items)

### Training Corpus Reality
- On disk: 168 training pairs, 84 schematics, 5 PCBs
- Phase 227 precondition: run crawler to materialize corpus
- Until then: cloud model as default for iOS

### Parity Gate (C-04)
Batch validation (Phase 228) MUST complete before daemon removal (Phase 225).
Daemon stays wired and functional as fallback through transition.

## Corrected Dependency Graph
```
221 → 222 → 223 → 224 → 228 → 225 → 226 → 229
                                 ↑
                227 (parallel) ──┘
```

## Phases

### Phase 221: Swift Parser + IR ✅ COMPLETE
- SExpression.swift — recursive descent parser
- SchematicParser.swift — .kicad_sch → typed structs
- TopologyBuilder.swift — union-find net resolution

### Phase 222: Swift ERC/DRC (IN PROGRESS)
Port 18 checks using the Swift parser instead of Python.
- NativeERC.swift — pin conflicts, power, NC, dangling
- NativeDRC.swift — copper, width, courtyard, holes, annular
- Swift geometry layer (buffer, intersection, distance)

### Phase 223: Swift PCB Parser
Port .kicad_pcb parser + PCB IR types.

### Phase 224: Swift Operation Executor (Scoped)
Port ~30 critical ops. Leave 130 ops daemon-backed on Mac.

### Phase 228: Batch Parity Validation
Swift vs Python vs kicad-cli on all fixtures.
Must reach ≥99% agreement before Phase 225.

### Phase 225: Remove Daemon (Mac)
Gate on Phase 228 parity proof. Feature flag transition.

### Phase 226: iOS Target
iPad/iPhone build target with shared core.

### Phase 227: Gemma 3 4B Training (Parallel)
Train smaller model. Requires corpus materialization first.

### Phase 229: App Store Polish
Privacy manifest, screenshots, reviewer notes.
