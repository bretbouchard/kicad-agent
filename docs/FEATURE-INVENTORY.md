# volta — Feature & Ability Inventory

**v6.0 · 2026-07-14**

This is the exhaustive, honest list. Every row cites a file path and a representative line range so you can verify the claim. Status codes:

- ✅ **Shipped** — wired in production code path
- 🟡 **Partial** — exists but stub / mock / known limitations
- 🟠 **Scaffolded** — types/views exist, real implementation missing
- ⏸ **Planned** — on the roadmap, not yet built
- ❌ **Not in scope** — explicitly out of scope for v6

---

## 1. macOS App — SwiftUI Views

### 1.1 Top-level navigation

| View | Path | Status | Purpose | Wired in? |
|------|------|--------|---------|-----------|
| AppRootView | `macos-app/Sources/Volta/Views/AppRootView.swift:1-140` | ✅ | Root NavigationSplitView, project sidebar + main detail | App entry point |
| ProjectSidebar | `macos-app/Sources/Volta/Views/ProjectSidebar.swift:1-86` | ✅ | List + create + delete projects | Sidebar in AppRootView |
| ChatPlaceholderView | `macos-app/Sources/Volta/Views/ChatPlaceholderView.swift` | ✅ | Empty state when no project selected | In AppRootView |
| LiquidGlassShell | `macos-app/Sources/Volta/Views/LiquidGlassShell.swift:1-562` | ✅ | Main chat window (header, content, compose, validation) | Detail view in AppRootView |
| ProviderBanner | `macos-app/Sources/Volta/Views/ProviderBanner.swift` | ✅ | Shows current LLM provider + model | In AppRootView header |
| KiCadInstallView | `macos-app/Sources/Volta/Views/Onboarding/KiCadInstallView.swift` | 🟠 | KiCad install prompt | **Orphaned** (Phase 220 removed the install path; file still on disk) |

### 1.2 Chat pipeline

| View | Path | Status | Purpose | Wired in? |
|------|------|--------|---------|-----------|
| ChatView | `macos-app/Sources/Volta/Views/Chat/ChatView.swift` | ✅ | Streaming chat with message list + compose | In LiquidGlassShell |
| MessageBubbleView | `macos-app/Sources/Volta/Views/Chat/MessageBubbleView.swift` | ✅ | Single message render (user / assistant / system) | In ChatView |
| ConversationListView | `macos-app/Sources/Volta/Views/Chat/ConversationListView.swift` | 🟡 | Lists conversations for a project | Available via view dependency |
| ImageAttachmentView | `macos-app/Sources/Volta/Views/Chat/ImageAttachmentView.swift` | 🟡 | Displays attached image thumbnails | **UI wire-up pending** (Phase 196) |
| RouterStreamProvider | `macos-app/Sources/Volta/Views/Chat/RouterStreamProvider.swift:1-184` | ✅ | Bridges router → ChatView (echo stripping, chunking) | Production stream provider |
| OperationExecutor | `macos-app/Sources/Volta/Views/Chat/OperationExecutor.swift` | ✅ | Runs LLM-emitted JSON op sequences | In LiquidGlassShell |

### 1.3 Validation & inline preview

| View | Path | Status | Purpose | Wired in? |
|------|------|--------|---------|-----------|
| ValidationPanel | `macos-app/Sources/Volta/Views/ValidationPanel.swift` | ✅ | ERC + DRC run + display | Conditional in LiquidGlassShell |
| ValidationResultsPanel | (inline in LiquidGlassShell) | ✅ | Renders violation list | In ValidationPanel |
| SchematicPreviewView | `macos-app/Sources/Volta/Views/InlineRendering/SchematicPreviewView.swift` | 🟠 | Schematic render from IR | Mock-only |
| PCBPreviewView | `macos-app/Sources/Volta/Views/InlineRendering/PCBPreviewView.swift` | 🟠 | PCB render from IR | Mock-only |
| SwiftSVGRenderer | `macos-app/Sources/Volta/Views/InlineRendering/SwiftSVGRenderer.swift:1-150` | ✅ | SVG → NSImage rendering | Powers SchematicPreviewView |
| FullScreenInspector | `macos-app/Sources/Volta/Views/InlineRendering/FullScreenInspector.swift` | 🟠 | Full-screen canvas | Not wired |
| MockPreviewRenderer | `macos-app/Sources/Volta/Views/InlineRendering/MockPreviewRenderer.swift` | ✅ | Test renderer (previews/tests) | For previews |

### 1.4 Settings

| View | Path | Status | Purpose | Wired in? |
|------|------|--------|---------|-----------|
| SettingsSheet (root) | `LiquidGlassShell.swift:630-682` | 🟡 | Tabbed settings UI | In toolbar |
| ProviderRoutingSettingsView | `macos-app/Sources/Volta/Views/Settings/ProviderRoutingSettingsView.swift` | ✅ | Configure LLM provider fallback chain | SettingsTab.providers |
| BYOKSettingsView | `macos-app/Sources/Volta/Views/Settings/BYOKSettingsView.swift` | ✅ | API key storage (Keychain) | SettingsTab.pending |
| ExternalMCPSettingsView | `macos-app/Sources/Volta/Views/Settings/ExternalMCPSettingsView.swift` | ✅ | External MCP server config | SettingsTab.externalMCP |
| MemorySettingsTab | `LiquidGlassShell.swift:684-702` | 🟠 | Memory / time-travel settings | SettingsTab.memory |
| CollaborationSettingsTab | `LiquidGlassShell.swift:704-731` | 🟠 | Collaboration settings | SettingsTab.collaboration |

### 1.5 Memory & collaboration (scaffolds)

| View | Path | Status | Purpose | Wired in? |
|------|------|--------|---------|-----------|
| TimeTravelView | `macos-app/Sources/Volta/Views/Memory/TimeTravelView.swift` | 🟠 | Back/forward time navigation | Placeholder text |
| DecisionTimelineView | `macos-app/Sources/Volta/Views/Memory/DecisionTimelineView.swift` | 🟠 | Decision history | Placeholder |
| ChapterSegmentationView | `macos-app/Sources/Volta/Views/Memory/ChapterSegmentationView.swift` | 🟠 | Chapter markers in timeline | Not wired |
| ProjectGenealogyView | `macos-app/Sources/Volta/Views/Collaboration/ProjectGenealogyView.swift` | 🟠 | Version history | Placeholder text |
| CollaborationActivityFeed | `macos-app/Sources/Volta/Views/Collaboration/CollaborationActivityFeed.swift` | 🟠 | Real-time activity feed | Placeholder |

### 1.6 User actions (per view)

**AppRootView**
- ✅ Create new project (button + cmd+N)
- ✅ Delete project (context menu)
- ✅ Recover from daemon failure (Retry button)

**LiquidGlassShell**
- ✅ Send chat message (TextField + return)
- ✅ Attach KiCad file (Toolbar → Open)
- ✅ Run ERC (Validation → Run ERC)
- ✅ Run DRC (Validation → Run DRC)
- ✅ Copy conversation to clipboard (toolbar)
- ✅ Open Settings (toolbar)
- ✅ Share project (toolbar)

---

## 2. Volta Ops — Schematic + PCB Operations

**Total: 268 atomic operations** across 3 Swift files + Python daemon parity.

### 2.1 Schematic operations (read)

| Op | ReadOnly | File | What it does |
|---|---|---|---|
| `list_components` | Yes | `VoltaEngine.swift` | List all components in schematic |
| `list_nets` | Yes | `VoltaEngine.swift` | List all nets in schematic |
| `get_component` | Yes | `VoltaEngine.swift` | Get single component (ref/lib_id/pos) |
| `get_properties` | Yes | `VoltaEngine.swift` | Get all properties of a component |
| `count_components` | Yes | `VoltaEngine.swift` | Count components |
| `get_schematic_info` | Yes | `VoltaEngine.swift` | Schematic metadata |
| `get_pcb_info` | Yes | `VoltaEngine.swift` | PCB metadata |
| `list_pads` | Yes | `VoltaEngine.swift` | All pads with positions |
| `list_vias` | Yes | `VoltaEngine.swift` | All vias |
| `list_segments` | Yes | `VoltaEngine.swift` | All wire segments |
| `list_net_classes` | Yes | `VoltaEngine.swift` | PCB net classes |
| `extract_nets` | Yes | `VoltaEngineGenerated.swift` | Net extraction from schematic |
| `infer_connectivity` | Yes | `VoltaEngineGenerated.swift` | Connectivity graph |
| `detect_net_conflicts` | Yes | `VoltaEngineGenerated.swift` | Net conflicts |
| `detect_net_shorts` | Yes | `VoltaEngineGenerated.swift` | Net shorts |
| `detect_routing_collisions` | Yes | `VoltaEngineGenerated.swift` | Routing collisions |
| `detect_pin_overlaps` | Yes | `VoltaEngineGenerated.swift` | Pin overlaps |
| `suggest_net_names` | Yes | `VoltaEngineGenerated.swift` | Net name suggestions |
| `classify_violations` | Yes | `VoltaEngineGenerated.swift` | Classify violations |
| `diagnose_violations` | Yes | `VoltaEngineGenerated.swift` | Diagnose violations |
| `navigate_hierarchy` | Yes | `VoltaEngineGenerated.swift` | Sheet hierarchy navigation |
| `trace_net_from_label` | Yes | `VoltaEngineGenerated.swift` | Trace net from label |
| `query_connectivity` | Yes | `VoltaEngineGenerated.swift` | Connectivity query |
| `list_design_rules` | Yes | `VoltaEngineRemaining.swift` | All design rules |
| `list_lib_entries` | Yes | `VoltaEngineRemaining.swift` | Lib table entries |
| `analyze_gaps` | Yes | `VoltaEngineRemaining.swift` | Routing gaps |
| `analyze_ground_topology` | Yes | `VoltaEngineRemaining.swift` | Ground net analysis |
| `analyze_split_plane` | Yes | `VoltaEngineRemaining.swift` | Split plane analysis |
| `read_board_metadata` | Yes | `VoltaEngineRemaining.swift` | Board title-block |
| `list_vendor_drc_profiles` | Yes | `VoltaEngineRemaining.swift` | Vendor profiles |
| `gate_status` | Yes | `VoltaEngineRemaining.swift` | Design stage gate status |
| `get_constraints` | Yes | `VoltaEngineRemaining.swift` | Design constraints |

### 2.2 Schematic operations (write)

| Op | File | What it does |
|---|---|---|
| `add_component` | `VoltaEngine.swift` | Add new component at position |
| `remove_component` | `VoltaEngine.swift` | Remove component by ref |
| `duplicate_component` | `VoltaEngine.swift` | Duplicate with offset + new ref |
| `modify_property` | `VoltaEngine.swift` | Change property value |
| `add_wire` | `VoltaEngine.swift` | Add wire between two points |
| `remove_wire` | `VoltaEngine.swift` | Remove wire by uuid |
| `add_label` | `VoltaEngine.swift` | Add net label at position |
| `add_junction` | `VoltaEngine.swift` | Add wire junction |
| `add_no_connect` | `VoltaEngine.swift` | Add no-connect flag |
| `add_power` | `VoltaEngine.swift` | Add power symbol (#PWR) |
| `create_schematic` | `VoltaEngine.swift` | Create empty `.kicad_sch` |
| `annotate` | `VoltaEngine.swift` | Renumber references |
| `add_sheet` | `VoltaEngine.swift` | Add hierarchical sheet |
| `move_component` | `VoltaEngineGenerated.swift` | Move component |
| `snap_components_to_grid` | `VoltaEngineGenerated.swift` | Snap to grid |
| `snap_to_grid` | `VoltaEngineGenerated.swift` | Snap one component |
| `renum_refs` | `VoltaEngineGenerated.swift` | Renumber references |
| `rebuild_root_sheet` | `VoltaEngineGenerated.swift` | Rebuild root sheet |
| `embed_symbol` | `VoltaEngineGenerated.swift` | Embed symbol from lib |
| `swap_symbol` | `VoltaEngineGenerated.swift` | Swap symbol |
| `propagate_symbol_change` | `VoltaEngineGenerated.swift` | Propagate symbol swap |
| `update_symbols_from_library` | `VoltaEngineGenerated.swift` | Update from lib |
| `update_footprint_from_library` | `VoltaEngineGenerated.swift` | Update footprint from lib |
| `assign_footprint` | `VoltaEngineGenerated.swift` | Assign footprint to component |
| `remove_label` | `VoltaEngineGenerated.swift` | Remove single label |
| `remove_labels` | `VoltaEngineGenerated.swift` | Remove multiple labels |
| `remove_junction` | `VoltaEngineGenerated.swift` | Remove junction |
| `remove_no_connect` | `VoltaEngineGenerated.swift` | Remove no-connect |
| `rename_net_label` | `VoltaEngineGenerated.swift` | Rename net label |
| `place_net_labels` | `VoltaEngineGenerated.swift` | Place net labels |
| `add_power_flag` | `VoltaEngineRemaining.swift` | Add power flag |
| `add_sheet_pin` | `VoltaEngineRemaining.swift` | Add sheet pin |
| `add_design_rule` | `VoltaEngineRemaining.swift` | Add design rule |
| `add_lib_entry` | `VoltaEngineRemaining.swift` | Add lib table entry |
| `add_net_class` | `VoltaEngineRemaining.swift` | Add net class |
| `modify_net_class` | `VoltaEngineRemaining.swift` | Modify net class |
| `remove_net_class` | `VoltaEngineRemaining.swift` | Remove net class |
| `modify_design_rule` | `VoltaEngineRemaining.swift` | Modify design rule |
| `remove_design_rule` | `VoltaEngineRemaining.swift` | Remove design rule |
| `remove_lib_entry` | `VoltaEngineRemaining.swift` | Remove lib entry |
| `connect_pins` | `VoltaEngineRemaining.swift` | Connect two pins |
| `batch_connect` | `VoltaEngineRemaining.swift` | Multi-pin connect |
| `place_component` | `VoltaEngineRemaining.swift` | Place at position |
| `place_components_sch` | `VoltaEngineRemaining.swift` | Place multiple (grid) |
| `place_missing_units` | `VoltaEngineRemaining.swift` | Place missing units |
| `array_replicate` | `VoltaEngineRemaining.swift` | Array replication |
| `repair_schematic` | `VoltaEngineGenerated.swift` | Auto-repair schematic |
| `review_schematic` | `VoltaEngineGenerated.swift` | LLM review |
| `critique_sch` | `VoltaEngineGenerated.swift` | LLM critique |
| `convert_to_skidl` | `VoltaEngineRemaining.swift` | Schematic → SKIDL code |
| `apply_labels_sch` | `VoltaEngineRemaining.swift` | Apply label rules |
| `apply_floor_plan` | `VoltaEngineRemaining.swift` | Apply floor plan |
| `safe_annotate` | `VoltaEngineRemaining.swift` | Safe annotation (preserves) |
| `create_symbol` | `VoltaEngineRemaining.swift` | Create new symbol |
| `create_project` | `VoltaEngineRemaining.swift` | Create new project |
| `create_footprint` | `VoltaEngineRemaining.swift` | Create new footprint |

### 2.3 PCB operations (read)

Same as schematic reads above where applicable (lists, gets). Plus:
| Op | File | What it does |
|---|---|---|
| `validate_footprint` | `VoltaEngineGenerated.swift` | Footprint validates against lib |
| `verify_pin_map` | `VoltaEngineGenerated.swift` | Pin map verification |
| `validate_power_nets` | `VoltaEngineGenerated.swift` | Power net validation |
| `validate_schematic` | `VoltaEngineGenerated.swift` | Full schematic validation |
| `validate_h_labels` | `VoltaEngineGenerated.swift` | Hierarchical labels |
| `parse_erc` | `VoltaEngineGenerated.swift` | Parse ERC report |
| `extract_violation_positions` | `VoltaEngineGenerated.swift` | Extract violation coords |
| `cross_ref_check` | `VoltaEngineGenerated.swift` | Cross-ref validation |
| `validate_refs` | `VoltaEngineGenerated.swift` | Reference validation |
| `drc_vendor` | `VoltaEngineRemaining.swift` | Vendor DRC profile run |
| `run_native_erc` | `VoltaEngine.swift` | Native ERC (Swift) |
| `run_native_drc` | `VoltaEngine.swift` | Native DRC (Swift) |
| `run_structural_check` | `VoltaEngine.swift` | File syntax validation |
| `run_gate_check` | `VoltaEngineRemaining.swift` | Design stage gate |
| `pre_pcb_schematic_gate` | `VoltaEngineRemaining.swift` | Pre-PCB gate |
| `set_constraints` | `VoltaEngineRemaining.swift` | Set design constraints |

### 2.4 PCB operations (write)

| Op | File | What it does |
|---|---|---|
| `add_track` | `VoltaEngineGenerated.swift` | Add track |
| `add_arc_track` | `VoltaEngineGenerated.swift` | Add arc track |
| `add_via` | `VoltaEngineGenerated.swift` | Add via |
| `delete_track` | `VoltaEngineGenerated.swift` | Delete track |
| `delete_via` | `VoltaEngineGenerated.swift` | Delete via |
| `move_track_endpoint` | `VoltaEngineGenerated.swift` | Move track endpoint |
| `lock_track` | `VoltaEngineGenerated.swift` | Lock track |
| `lock_via` | `VoltaEngineGenerated.swift` | Lock via |
| `move_footprint` | `VoltaEngineGenerated.swift` | Move footprint |
| `swap_footprint` | `VoltaEngineGenerated.swift` | Swap footprint |
| `add_net` | `VoltaEngineGenerated.swift` | Add net |
| `remove_net` | `VoltaEngineGenerated.swift` | Remove net |
| `rename_net` | `VoltaEngineGenerated.swift` | Rename net |
| `add_copper_zone` | `VoltaEngineGenerated.swift` | Add copper zone |
| `remove_copper_zone` | `VoltaEngineGenerated.swift` | Remove zone |
| `delete_copper_zone` | `VoltaEngineGenerated.swift` | Delete zone |
| `add_keepout_area` | `VoltaEngineGenerated.swift` | Add keepout |
| `add_zone_keepout` | `VoltaEngineGenerated.swift` | Zone keepout |
| `remove_keepout_area` | `VoltaEngineGenerated.swift` | Remove keepout |
| `assign_net_class` | `VoltaEngineGenerated.swift` | Assign net class |
| `set_board_outline` | `VoltaEngineGenerated.swift` | Set board outline |
| `set_board_metadata` | `VoltaEngineGenerated.swift` | Set board metadata |
| `set_board_revision` | `VoltaEngineGenerated.swift` | Set revision |
| `remove_dangling_tracks` | `VoltaEngineGenerated.swift` | Remove dangling tracks |
| `remove_dangling_wires` | `VoltaEngineGenerated.swift` | Remove dangling wires |
| `create_pcb` | `VoltaEngine.swift` | Create empty `.kicad_pcb` |
| `add_stitching_via_pattern` | `VoltaEngineRemaining.swift` | Stitching via grid |
| `auto_route` | `VoltaEngineRemaining.swift` | Basic Manhattan routing (star topology) |
| `auto_route_manhattan` | `VoltaEngineRemaining.swift` | Manhattan routing |
| `auto_route_freerouting` | `VoltaEngineRemaining.swift` | Freerouting integration |
| `auto_place` | `VoltaEngineRemaining.swift` | Auto-place components |
| `auto_place_zoned` | `VoltaEngineRemaining.swift` | Zoned auto-place |
| `auto_layout_sch` | `VoltaEngineRemaining.swift` | Auto-layout schematic |
| `fill_gaps` | `VoltaEngineRemaining.swift` | Fill routing gaps |
| `fill_zones` | `VoltaEngineRemaining.swift` | Fill copper zones |
| `refill_copper_zone` | `VoltaEngineRemaining.swift` | Refill one zone |
| `match_lengths` | `VoltaEngineRemaining.swift` | Match trace lengths (reports skew only) |
| `route_diff_pair` | `VoltaEngineRemaining.swift` | Diff pair routing |
| `route_wires_sch` | `VoltaEngineRemaining.swift` | Route schematic wires |
| `stitch_power_nets` | `VoltaEngineRemaining.swift` | Stitch power nets |
| `break_wire_shorts` | `VoltaEngineRemaining.swift` | Break shorts |
| `fix_net_short` | `VoltaEngineRemaining.swift` | **Returns message only** |
| `fix_pin_type_mismatches` | `VoltaEngineRemaining.swift` | **Returns message only** |
| `fix_shorted_nets` | `VoltaEngineRemaining.swift` | Fix shorted nets |
| `fix_silkscreen_over_copper` | `VoltaEngineRemaining.swift` | Silkscreen fix |
| `resolve_shorted_nets` | `VoltaEngineRemaining.swift` | Resolve shorts |
| `strip_shorts` | `VoltaEngineRemaining.swift` | Strip all shorts |
| `erc_auto_fix` | `VoltaEngineRemaining.swift` | ERC auto-fix |
| `erc_auto_fix_hierarchical` | `VoltaEngineRemaining.swift` | ERC auto-fix hierarchical |
| `safe_sync_pcb_from_schematic` | `VoltaEngineRemaining.swift` | **Stub** — returns placeholder |
| `update_pcb_from_schematic` | `VoltaEngineRemaining.swift` | Update PCB from schematic |
| `update_from_schematic` | `VoltaEngineRemaining.swift` | Update from schematic |
| `rebuild_pcb_nets` | `VoltaEngineRemaining.swift` | Rebuild PCB nets |
| `regenerate_wiring` | `VoltaEngineRemaining.swift` | Regenerate wiring |
| `repopulate_pcb_from_schematic` | `VoltaEngineRemaining.swift` | Repopulate PCB |
| `modify_copper_zone` | `VoltaEngineRemaining.swift` | Modify zone |
| `modify_zone_polygon` | `VoltaEngineRemaining.swift` | Modify zone polygon |
| `modify_project_settings` | `VoltaEngineRemaining.swift` | Modify project settings |
| `convert_from_skidl` | `VoltaEngineRemaining.swift` | SKIDL → schematic (requires Python) |
| `convert_kicad6_to_10` | `VoltaEngineRemaining.swift` | Version migration |
| `import_ses` | `VoltaEngineRemaining.swift` | Import SES (Spectra session) |
| `export_positions` | `VoltaEngineRemaining.swift` | Export P&P positions |
| `import_positions` | `VoltaEngineRemaining.swift` | Import P&P positions |
| `generate_bom` | `VoltaEngineRemaining.swift` | Generate BOM |
| `batch_expand_footprints` | `VoltaEngineRemaining.swift` | Batch expand footprints |

---

## 3. Validation Engines

### 3.1 ERC (Electrical Rules Check)

| Engine | File | Status | Checks | Latency |
|---|---|---|---|---|
| **NativeERC (Swift)** | `macos-app/Sources/Volta/Validation/NativeERC.swift` | ✅ Phase 231 | Pin-type compatibility (11x11 matrix), power net, no-connect, dangling wires | 10-20 ms / 100 parts |
| **NativeERC (Python)** | `volta-0.1.0/src/volta/validation/native_erc.py:1-363` | ✅ | Same checks as Swift | 50-100 ms / 100 parts |
| **kicad-cli ERC** | (external) | ✅ | Reference: ground truth, slower (process spawn) | 1-3 s / file |

**Swift and Python ERC passed 50/50 parity** against kicad-cli reference (`Phase 218` summary). Phase 231 wired Swift as the primary (instant, no daemon roundtrip).

### 3.2 DRC (Design Rules Check)

| Engine | File | Status | Checks | Latency |
|---|---|---|---|---|
| **NativeDRC (Swift)** | `macos-app/Sources/Volta/Validation/NativeDRC.swift` | 🟡 Partial | Track-to-track spacing, pad-to-track, track width | TBD |
| **NativeDRC (Python)** | `volta-0.1.0/src/volta/validation/native_drc.py:1-551` | ✅ Phase 232 | Copper spacing (O(n log n) via SpatialHash), netclass width, courtyard overlap, hole-to-hole, annular ring | 50-200 ms / 1000 traces |
| **kicad-cli DRC** | (external) | ✅ | Reference: ground truth | 1-5 s / file |

### 3.3 SpatialHash

| Component | File | Status | Purpose |
|---|---|---|---|
| `SpatialHash<(Int, ItemGeom)>` | `macos-app/Sources/Volta/Validation/SpatialHash.swift` (and Python twin) | ✅ Phase 232 | O(n log n) copper spacing queries, makes DRC scale to real boards |

### 3.4 Gate system

| Gate | File | Status | What it enforces |
|---|---|---|---|
| `pre_pcb_schematic_gate` | `VoltaEngineRemaining.swift` | ✅ | Schematic ready before PCB layout |
| `run_gate_check` | `VoltaEngineRemaining.swift` | ✅ | Generic extensible gate |
| `gate_status` | `VoltaEngineRemaining.swift` | ✅ | Query current gate state |

---

## 4. Chat Pipeline

### 4.1 Provider system

| Provider | File | Kind | Status | Notes |
|---|---|---|---|---|
| `AppleLocalProvider` | `Models/Providers/...` | local | ✅ | Apple Intelligence / MLX Swift |
| `MLXLocalProvider` | `Models/Providers/...` | local | ✅ | Configurable path to any MLX model |
| `AnthropicCloudProvider` | `Models/Providers/...` | cloud | ✅ | BYOK |
| `OpenAICompatibleCloudProvider` | `Models/Providers/...` | cloud | ✅ | Any OpenAI-protocol endpoint |
| `GeminiCloudProvider` | `Models/Providers/...` | cloud | ✅ | BYOK |
| `OllamaCloudProvider` | `Models/Providers/...` | cloud | ✅ | Ollama server |
| `MockProvider` | `Models/Providers/...` | local | ✅ | Testing |

Protocol: `KiCadModelProvider: Sendable` with `stream()`, `generateJSON()`, `availability`, `displayName`, `kind`.

### 4.2 Stream pipeline

| Component | File | Status | Notes |
|---|---|---|---|
| `ChatStreamProvider` protocol | `Views/Chat/ChatTypes.swift:166-170` | ✅ | Test-friendly protocol |
| `NoopChatStream` | `Views/Chat/ChatTypes.swift:173-192` | ✅ | Canned text for previews |
| `RouterStreamProvider` | `Views/Chat/RouterStreamProvider.swift:1-184` | ✅ | Production: echo strip + boundary chunking |
| `KiCadModelRouter` | `Models/Providers/KiCadModelRouter.swift` | ✅ | Provider selection + fallback |
| `ConversationExporter` | `Views/Chat/ChatTypes.swift:204-269` | ✅ | Plain-text + clipboard export |

### 4.3 Cost tracking

| Component | File | Status | Notes |
|---|---|---|---|
| `CostEstimate` | `Views/Chat/ChatTypes.swift:83-104` | ✅ | Per-message USD + tokens |
| `KCToken` | `Models/Providers/KCToken.swift` | ✅ | Token stream variant |
| `KCUsage` | `Models/Providers/KCUsage.swift` | ✅ | Usage callback type |
| `KCCostLedger` | `Models/Providers/KCCostLedger.swift` | ✅ | Persistent cost ledger (SwiftData) |

### 4.4 Image attachments

| Component | File | Status | Notes |
|---|---|---|---|
| `ImageAttachment` model | `Views/Chat/ChatTypes.swift:107-155` | ✅ | Up to 10MB, 2048px max, PNG/JPEG/HEIC |
| `ImageAttachmentValidator` | `Views/Chat/ChatTypes.swift:145-155` | ✅ | Accept / needs-compression checks |
| `ImageAttachmentView` | `Views/Chat/ImageAttachmentView.swift` | 🟡 | UI exists, full wire-up Phase 196 |
| `KCAttachment` | `Models/Providers/KCAttachment.swift` | ✅ | Provider-side attachment |

---

## 5. Python Daemon

### 5.1 CLI subcommands (`volta <subcommand>`)

| Subcommand | Status | What it does |
|---|---|---|
| `collect` | ✅ | Collect training data from GitHub |
| `erc` | ✅ | Run ERC on schematic |
| `drc` | ✅ | Run DRC on PCB |
| `export` | ✅ | Export (gerber, bom, pos, step) |
| `context` | ✅ | Project summary |
| `route` | ✅ | Auto-route nets |
| `analyze` | ✅ | Analyze PCB with local model |
| `component-search` | ✅ | Start MCP server (component search) |
| `ai-stats` | ✅ | AI intervention metrics |
| `design-rules` | ✅ | Run domain-specific rules |
| `review-schematic` | ✅ | Review for readability |
| `critique` | ✅ | AI legibility scoring |
| `pre-pcb-gate` | ✅ | Schematic readiness check |
| `gate` | ✅ | Design stage gates |
| `demo` | ✅ | Generate schematic in one command |
| `playground` | ✅ | Web UI |
| `dfm` | ✅ | DFM analysis |
| `undo` | ✅ | Undo last operation |
| `redo` | ✅ | Redo |
| `workflow` | ✅ | Named workflows |
| `check-conventions` | ✅ | IEEE 315 checks |
| `build` | ✅ | Build snapshots |
| `handoff` | ✅ | Manufacturer handoff package |
| `drc-vendor` | ✅ | Vendor-specific DRC profiles |
| `board-metadata` | ✅ | Read/set PCB title-block |

### 5.2 IPC handler

`volta-0.1.0/src/volta/handler.py:1-214`
- Validates operation JSON against Pydantic schema
- Dispatches to OperationExecutor
- Provides actionable error messages with line numbers
- Per-project mutex (concurrent ops serialized)

### 5.3 Training pipeline

| Script | Purpose |
|---|---|
| `train_sft.py` | Base SFT training (PyTorch + PEFT) |
| `train_gemma_sft_mlx.py` | Gemma SFT on MLX (Apple Silicon) |
| `train_lora_vastai.py` | Vast.ai LoRA training |
| `train_grpo_mlx.py` | GRPO RL fine-tuning on MLX |
| `train_unified.py` | Unified multi-task training |
| `train_board_reward.py` | Board-level reward model |
| `train_real_reward.py` | Production reward model |
| `convert_peft_to_mlx.py` | PEFT → MLX format conversion |
| `evaluate_models.py` | Multi-task evaluation |
| `collect_training_data.py` | GitHub corpus collection |
| `collect_gold_standard.py` | Manual gold-standard collection |
| `generate_diagnostic_training_data.py` | Training data for error corrections |
| `fetch_100k.py`, `discover_100k.py` | Large-corpus discovery |
| `corpus_curator.py` | Dedup + deep-normalize to canonical L1 |
| `schgen_to_skidl` | MS SchGen → SKIDL converter |
| `kicad_repo_to_skidl` | KiCad → SKIDL converter |

### 5.4 Routing

| Component | File | Status |
|---|---|---|
| A* pathfinding | `volta/routing/` | ✅ |
| Manhattan router | `VoltaEngineRemaining.swift` | ✅ Basic |
| Freerouting integration | `volta/routing/freerouting/` | ✅ DSN/SES |
| `auto_route` | `VoltaEngineRemaining.swift` | ✅ Star topology |
| `auto_route_manhattan` | `VoltaEngineRemaining.swift` | ✅ |
| `auto_route_freerouting` | `VoltaEngineRemaining.swift` | ✅ |

### 5.5 Netlist + SPICE

| Component | File | Status |
|---|---|---|
| KiCad netlist | `volta/circuit_ir/` | ✅ |
| SPICE netlist | `volta/spice/netlist_to_spice.py` | ✅ |
| ngspice bridge | `volta/spice/ngspice_bridge.py` | ✅ |
| Optuna GPSampler | `volta/spice/optuna_runner.py` | ✅ |
| LTspice integration | `volta/ltspice/` | ✅ |

---

## 6. Vendor DRC Profiles

| Vendor | Layer Counts | Status |
|---|---|---|
| JLCPCB | 2, 4, 6 | ✅ Phase 206 |
| PCBWay | 2, 4, 6, 8 | ✅ |
| AISLER | 2, 4 | ✅ |
| OSH Park | 2, 4 | ✅ |
| Advanced Circuits | 2, 4, 6 | ✅ |
| General | 1-8 | ✅ |

Each profile defines: minimum trace width, minimum clearance, annular ring, drill-to-copper, mask sliver, silk sliver, courtyard excess, edge clearance.

---

## 7. Manufacturer Handoff

`build_handoff_export(vendor="jlcpcb", project="...")` produces a zip with:

| File | Status | Format |
|---|---|---|
| Gerbers (each layer) | ✅ | RS-274X |
| Drill (Excellon) | ✅ | .drl + .zip |
| BOM (per-vendor) | ✅ | CSV, JLCPCB/PCBWay columns |
| Pick-and-place | ✅ | CSV, JLCPCB/PCBWay columns |
| STEP 3D model | ✅ | .step |
| Netlist | ✅ | KiCad .net |
| Schematic PDF | ✅ | .pdf |
| PCB render PNG | ✅ | .png |
| Manifest (JSON) | ✅ | All files + SHA256 |
| README | ✅ | Assembly + BOM notes |

---

## 8. Tests by Area

### 8.1 macOS app tests (`macos-app/Tests/VoltaTests/`)

| Category | Files | Coverage |
|---|---|---|
| Daemon | `DaemonMessengerTests.swift`, `StdioWatchdogTests.swift` | ✅ |
| KiCad detection | `KiCadCLIDetectorTests.swift` | ✅ |
| Providers | 8+ test files (Apple, MLX, Anthropic, Ollama, HF Hub, Router) | ✅ |
| UI | `ProviderBannerTests.swift` | 🟡 Only 1 view |
| Governance | 11 test files (state machine, gates, rollback, drift) | ✅ |
| **Validation (Swift)** | **None** | ❌ No tests for NativeERC, NativeDRC |
| **Op registry** | **None** | ❌ No tests for the 268 ops |
| **Visual regression** | **None** | ❌ No snapshot tests |

### 8.2 Python tests

| Category | Directories | Coverage |
|---|---|---|
| Operations | `tests/ops/` | High |
| Validation | `tests/validation/` | High |
| Parsing | `tests/circuit_ir/`, `tests/analysis/` | Medium |
| LLM/Adapters | `tests/llm/`, `tests/inference/` | Medium |
| MCP | `tests/mcp/` | Low |
| Generation | `tests/generation/` | Medium |
| Placement | `tests/floorplan/` | Medium |
| Routing | `tests/routing/` | Low |
| Integration | `tests/integration/` | Low (requires external tools) |
| Training | `tests/training/` | Medium |

**Total: 6,317 tests passing (last verified).** Major gaps:
- ❌ No tests for streaming chat pipeline
- ❌ No tests for image attachment end-to-end
- ❌ No tests for spatial hash (Phase 232) parity vs kicad-cli

---

## 9. Models & Adapters

| Adapter | Path | Framework | Status |
|---|---|---|---|
| v5 (47K multi-task) | `/Volumes/Storage/models/volta/adapters/v5/` | PEFT/MLX | ✅ Trained, loss 0.10 |
| v2 Volta 12B (in training) | `/Volumes/Storage/models/volta/adapters/volta-12b-v2/` (NOT YET DOWNLOADED) | PEFT | ⏳ Step 2773/3000 |
| Qwen 2.5 0.5B (bundled) | `macos-app/Resources/Models/` | MLX | ✅ Starter model |
| Gemma 4 12B V2 (when downloaded) | HuggingFace `bretbouchard/volta-pcb-adapter-v2` | MLX | ⏳ Pending |

Local model management: `volta/inference/model_downloader.py`

---

## 10. Honest "Can it do X?" — Full Q&A

### Schematic capture

| Q | A | Evidence |
|---|---|---|
| Generate schematic from natural language? | **Partial** — produces a schematic draft, not a finished board | RouterStreamProvider + 268 ops |
| Open existing KiCad 10 schematic? | ✅ | Parser + reader ops |
| Open KiCad 6/7/8/9 schematic? | 🟡 Version migration `convert_kicad6_to_10` exists; older versions unverified | VoltaEngineRemaining |
| Open Altium / Eagle schematic? | ❌ Not in scope | — |
| Edit schematic via UI? | 🟡 Wire-up pending for image attach; text-driven edits work | OperationExecutor |
| Add components? | ✅ `add_component` | VoltaEngine.swift |
| Wire components? | ✅ `add_wire` | VoltaEngine.swift |
| Annotate references? | ✅ `annotate`, `safe_annotate` | VoltaEngine* |
| Add hierarchy / sheets? | ✅ `add_sheet`, `add_sheet_pin` | VoltaEngine* |
| Detect pin-type conflicts? | ✅ NativeERC (Swift + Python) | NativeERC |
| Detect power net issues? | ✅ NativeERC | NativeERC |
| Detect dangling wires? | ✅ NativeERC | NativeERC |
| Run ERC in CI? | ✅ `volta erc <file>` | CLI |

### PCB layout

| Q | A | Evidence |
|---|---|---|
| Open existing KiCad 10 PCB? | ✅ | Parser |
| Auto-place components? | 🟡 Basic grid `auto_place`; no global optimization | VoltaEngineRemaining |
| Auto-route traces? | 🟡 Manhattan star-topology; Freerouting for serious jobs | VoltaEngineRemaining |
| Match length diff pairs? | 🟡 `match_lengths` reports skew, doesn't route | VoltaEngineRemaining |
| Compute impedance? | ❌ Not yet | See gap analysis |
| Run DRC offline? | ✅ NativeDRC (Python) — full checks; Swift — partial | NativeDRC |
| Run copper spacing check? | ✅ O(n log n) via SpatialHash | Phase 232 |
| Check courtyard overlap? | ✅ NativeDRC | NativeDRC |
| Check annular ring? | ✅ NativeDRC (0.15mm default) | NativeDRC |
| Fill copper zones? | ✅ `fill_zones`, `refill_copper_zone` | VoltaEngineRemaining |
| Add stitching vias? | ✅ `add_stitching_via_pattern` | VoltaEngineRemaining |
| Add keepout areas? | ✅ `add_keepout_area` | VoltaEngineGenerated |
| Sync PCB from schematic? | 🟡 `safe_sync_pcb_from_schematic` is a stub | VoltaEngineRemaining |
| Migrate KiCad 6 to 10? | ✅ `convert_kicad6_to_10` | VoltaEngineRemaining |

### Manufacturing

| Q | A | Evidence |
|---|---|---|
| Export Gerbers? | ✅ Per-layer RS-274X | `volta export` |
| Export drill files? | ✅ Excellon | `volta export` |
| Export BOM? | ✅ CSV, per-vendor columns | `generate_bom` |
| Export pick-and-place? | ✅ CSV | `export_positions` |
| Export STEP 3D? | ✅ | `volta export --format step` |
| Export netlist? | ✅ KiCad + SPICE | `volta/spice/` |
| Build complete handoff zip? | ✅ `build_handoff_export(vendor=...)` | Phase 208 |
| Validate against JLCPCB rules? | ✅ `drc_vendor --vendor jlcpcb` | Phase 206 |
| Validate against PCBWay rules? | ✅ `drc_vendor --vendor pcbway` | Phase 206 |
| Validate against AISLER rules? | ✅ | Phase 206 |
| Validate against OSH Park rules? | ✅ | Phase 206 |
| Live distributor pricing? | ❌ Phase 210 deferred | — |

### SPICE simulation

| Q | A | Evidence |
|---|---|---|
| Run AC analysis? | ✅ | `ngspice_bridge.py` |
| Run transient analysis? | ✅ | `ngspice_bridge.py` |
| Run noise analysis? | ✅ | `ngspice_bridge.py` |
| Run THD analysis? | ✅ | `ngspice_bridge.py` |
| Optimize component values (Optuna)? | ✅ | `optuna_runner.py` |
| Generate Bode plot? | ✅ | Closed-box demo (Phase 204) |
| Verify gain / bandwidth / noise specs? | ✅ | Phase 204 canonical pattern |

### AI / ML

| Q | A | Evidence |
|---|---|---|
| Run inference locally? | ✅ MLX (Qwen 0.5B bundled, custom adapters) | `MLXLocalProvider` |
| Run inference via Anthropic? | ✅ BYOK | `AnthropicCloudProvider` |
| Run inference via OpenAI? | ✅ BYOK | `OpenAICompatibleCloudProvider` |
| Run inference via Gemini? | ✅ BYOK | `GeminiCloudProvider` |
| Run inference via Ollama? | ✅ | `OllamaCloudProvider` |
| Use Apple Intelligence? | ✅ | `AppleLocalProvider` |
| Train a new adapter? | ✅ `train_sft.py`, `train_lora_vastai.py` | Training pipeline |
| Train on Vast.ai? | ✅ (instance 44774137 currently) | Volta v2 |
| Convert PEFT to MLX? | ✅ `convert_peft_to_mlx.py` | |
| Stream tokens in real time? | ✅ | `RouterStreamProvider` |
| Track cost per message? | ✅ | `KCCostLedger` |
| Strip echoed user input? | ✅ | `RouterStreamProvider.stripEcho` |
| Chunk long responses? | ✅ | `ContentChunker` + boundary flush |
| Detect model loops? | ✅ | `ContentChunker` dedup |

### Conversions

| Q | A | Evidence |
|---|---|---|
| Convert KiCad → SKIDL? | ✅ L1 (pin-level) + L2 (component-level) | `convert_to_skidl` |
| Convert SKIDL → KiCad? | ✅ (requires Python runtime) | `convert_from_skidl` |
| Convert MS SchGen → SKIDL? | ✅ | `schgen_to_skidl` |
| Migrate KiCad 6 → 10? | ✅ | `convert_kicad6_to_10` |
| Import SES (Spectra)? | ✅ | `import_ses` |

### Collaboration & workflow

| Q | A | Evidence |
|---|---|---|
| Real-time multi-user? | 🟠 Scaffolded, not live | ProjectGenealogyView |
| CloudKit sync? | 🟠 Types defined, sync engine partial | `Models/Collaboration/` |
| Undo/redo? | ✅ Persistent journal | `undo`, `redo` CLI |
| Time-travel through history? | 🟠 View scaffold exists | TimeTravelView |
| Decision timeline? | 🟠 View scaffold | DecisionTimelineView |
| Copy conversation to clipboard? | ✅ | `ConversationExporter` |
| Export conversation to file? | 🟡 `plainText(messages:)` ready, file export not wired | ChatTypes.swift |

### Vision & input

| Q | A | Evidence |
|---|---|---|
| Camera → schematic? | ❌ Phase 236 pending | Adapter trained, UI missing |
| Image attachment in chat? | 🟡 Model supports, UI wire-up pending (Phase 196) | ImageAttachmentView |
| Schematic render preview? | ✅ (mock data currently) | SchematicPreviewView |
| PCB render preview? | ✅ (mock data currently) | PCBPreviewView |

### Platform

| Q | A | Evidence |
|---|---|---|
| Run on macOS 26+? | ✅ | Target platform |
| Run on Apple Silicon? | ✅ MLX + Swift | Native |
| Run on Intel Mac? | ❌ MLX requires Apple Silicon | — |
| Run on iOS? | ❌ Future | — |
| Run on iPadOS? | ❌ Future | — |
| Run on Linux? | ❌ Not in scope | — |
| Run on Windows? | ❌ Not in scope | — |
| Work without internet? | ✅ Local MLX only | MLXLocalProvider |
| Multi-language UI? | ❌ English only | — |

### Standards & compliance

| Q | A | Evidence |
|---|---|---|
| IPC-2221 compliant DRC? | ❌ Not implemented | See gap analysis |
| IPC-7351 land patterns? | 🟡 KiCad libs are usually compliant, not verified | — |
| IEC 61010 (creepage/clearance)? | ❌ | — |
| IEC 60601 (medical)? | ❌ | — |
| RoHS/REACH BOM? | 🟡 Can mark parts; no automated compliance check | — |
| UL 94 flammability? | ❌ | — |
| FCC Part 15 EMI? | ❌ | — |

---

## 11. Repo Layout

```
volta/
├── macos-app/                    # Swift 6.2 / SwiftUI app
│   ├── Sources/Volta/
│   │   ├── Views/                # SwiftUI views (43 files)
│   │   ├── Parsing/              # Volta engine (3 files, 268 ops)
│   │   ├── Validation/           # NativeERC, NativeDRC, SpatialHash
│   │   ├── Models/Providers/     # LLM providers + protocols
│   │   ├── IPC/                  # DaemonMessenger (JSON-lines stdio)
│   │   ├── State/                # SwiftData persistence
│   │   └── DesignSystem/         # Liquid Glass tokens
│   └── Tests/                    # Swift tests (~25 files)
├── volta-0.1.0/            # Python daemon + training
│   ├── src/volta/
│   │   ├── handler.py            # IPC dispatcher
│   │   ├── ops/                  # Operation implementations
│   │   ├── validation/           # native_erc.py, native_drc.py
│   │   ├── routing/              # A* / Freerouting
│   │   ├── spice/                # ngspice bridge
│   │   ├── training/             # Corpus, SFT/GRPO trainers
│   │   ├── circuit_ir/           # SKiDL ↔ KiCad converter
│   │   ├── inference/            # Model downloader
│   │   └── cli.py                # All CLI subcommands
│   ├── tests/                    # 6,317 tests
│   └── pyproject.toml
├── Scripts/                      # Build, sign, ship, train
├── specs/                        # Legacy specifications
├── docs/                         # Documentation (this file)
└── .planning/                    # GSD project state
```
