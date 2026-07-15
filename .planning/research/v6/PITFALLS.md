# Pitfalls Research

**Domain:** Native Mac+iPhone app with Python daemon, Apple Intelligence, CloudKit sync, generative KiCad transforms
**Researched:** 2026-07-07
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: PyInstaller Code Signing Corruption (P0)

**What goes wrong:**
App builds and runs locally but crashes on launch for users with `killed: 9` or `code signature invalid` errors. Dylibs embedded by PyInstaller lose their code signatures during the `--onefile` pack process.

**Why it happens:**
PyInstaller's `--onefile` mode unpacks dylibs to a temporary directory at runtime, but the unpacked copies have no code signature. macOS hardened runtime rejects unsigned libraries even when the parent app is signed.

**How to avoid:**
- Sign EVERY embedded dylib individually before PyInstaller packaging: `codesign --force --deep --sign "$DEV_ID_APP" <dylib>`
- Use `--onefile` mode for executables but `--onedir` for Python dylibs (sign as a bundle, not individual files)
- Add `com.apple.security.cs.allow-unsigned-executable-memory` ONLY if absolutely necessary (MLX-Swift Metal)
- Verify with `codesign -dv --verbose=4 <app>.app` post-build — all embedded libs must show "valid on disk"
- Test on a CLEAN machine (no dev tools) — dev machines have relaxed security

**Warning signs:**
- `killed: 9` immediately after launch
- Console.app shows "code signature invalid" for `PyInstaller/temp/...`
- Works fine on developer machine but fails for testers

**Phase to address:**
Track A Phase 161 (Foundation bundling) — MUST pass clean-machine test before marking complete

---

### Pitfall 2: stdio MCP Buffering Deadlock (P0)

**What goes wrong:**
Swift app hangs indefinitely waiting for Python MCP daemon response. Process appears in Activity Manager but produces no output. Users force-quit the app.

**Why it happens:**
Python's stdout is block-buffered when not a TTY. Swift subprocess reads stdout line-by-line, but Python buffers until 4KB or process exit. If Python expects stdin input before flushing stdout, both sides block forever (Swift waiting for stdout, Python waiting for stdin).

**How to avoid:**
- Force line buffering on Python side: `export PYTHONUNBUFFERED=1` OR `sys.stdout.reconfigure(line_buffering=True)` at process start
- Run Python with `-u` flag: `process.executableURL = pythonURL; process.arguments = ["-u", "-m", "volta.mcp.server"]`
- Use `\n` delimited protocol (JSON-RPC requires newlines anyway)
- Add watchdog timer in Swift: if no stdout response in 30 seconds, kill and restart daemon
- Never mix binary and text output — choose one and stick to it

**Warning signs:**
- App hangs during first MCP operation
- Activity Manager shows Python subprocess using 0% CPU
- `lldb` shows Swift thread blocked in `Pipe.availableData`

**Phase to address:**
Track C Phase 169 (stdio MCP daemon) — MUST pass stress test (100 rapid RPC calls) before complete

---

### Pitfall 3: FoundationModels Unavailability Hard Failure (P0)

**What goes wrong:**
App crashes or shows "unavailable" error on non-Apple-Silicon Macs or devices without Apple Intelligence. Users on Intel Macs or older iPhones get zero functionality.

**Why it happens:**
FoundationModels framework is only available on Apple Silicon Macs with 8+ GB RAM and newer iPhones. Developers on M-series Macs never see this failure mode.

**How to avoid:**
- Check `FoundationModelsAvailability.foundationModelsAvailability()` at app launch, NOT device model
- Graceful degradation: if unavailable, switch to MLX-Swift (download HF model on first run)
- Pre-flight check during onboarding: "AI features require Apple Silicon or newer iPhone — continue with downloaded models?"
- NEVER hard-fail — app must work with downloaded models as fallback
- Unit tests with `FoundationModelsAvailability` stubbed to `.unavailable`

**Warning signs:**
- `FoundationModels is not available` exception in crash logs
- Bad reviews from Intel Mac users
- Onboarding shows no error but AI features silently fail

**Phase to address:**
Track B Phase 163 (FoundationModels integration) — MUST test on Intel Mac or with availability stub

---

### Pitfall 4: SwiftData CloudKit Schema Migration Data Loss (P0)

**What goes wrong:**
App updates with new SwiftData schema version. Users open app and ALL project history vanishes. CloudKit sync stalls with "partial failure" errors.

**Why it happens:**
SwiftData's `@Model` macro generates opaque schema. CloudKit requires exact schema version match between devices. If version diverges (one device updated, another didn't), CloudKit fails to sync and MAY wipe local data to force re-sync from server (which is empty if schema changed).

**How to avoid:**
- NEVER auto-migrate — use `VersionedSchema` with explicit migration plans
- Migration strategy: lightweight migration for additive changes, staged migration for breaking changes
- ALWAYS test two-device migration: update Phone, leave Mac on old version, open project on both, verify sync
- On migration failure: show alert "Cloud sync paused until both devices update" — do NOT wipe data
- For v6.0: freeze schema early (Track E Phase 177), ship schema stability guarantees

**Warning signs:**
- Projects disappear after app update
- CloudKit dashboard shows "schema mismatch" errors
- `NSPersistentCloudKitContainer` logs `partial error` with no detail

**Phase to address:**
Track E Phase 173 (SwiftData + CloudKit) — MUST pass two-device migration test

---

### Pitfall 5: Generative Transform Hash Instability (P0)

**What goes wrong:**
Same conversation state produces different KiCad files on each generation. "Re-generate from checkpoint" creates divergent artifacts, breaking event sourcing guarantees. User cannot repro bugs.

**Why it happens:**
Python dict ordering is insertion-ordered but not guaranteed sorted. JSON serialization includes timestamp metadata. Floating point rounding in SKIDL net calculations. Each generation runs at slightly different time, producing different hashes.

**How to avoid:**
- Hash ONLY the deterministic inputs: operation list, component set, net list, conversation intent
- Exclude from hash: timestamps, UUIDs, metadata, ordering-independent fields
- Sort all collections before hashing: `json.dumps(data, sort_keys=True)`
- Store canonical JSON (sorted keys, no whitespace) in event journal
- Gold master tests run 10x with same inputs, assert all hashes identical

**Warning signs:**
- Regression tests fail intermittently
- "Re-generate" produces different PCB
- Event journal shows same intent with different artifact hash

**Phase to address:**
Track F Phase 183 (generative transforms) — MUST pass 10-run determinism test

---

### Pitfall 6: iCloud Drive `.kicadagent` Bundle Corruption (P1)

**What goes wrong:**
Users edit project on both Mac and iPhone simultaneously. iCloud creates conflict copies but neither side resolves correctly. `.kicadagent` bundle contains partial `.kicad_sch` and `.kicad_pcb` files that KiCad refuses to open.

**Why it happens:**
iCloud Drive syncs files individually, not bundles atomically. If Mac writes `.kicad_sch` and iPhone writes `.kicad_pcb` at the same time, iCloud may deliver a mixed state to one device. KiCad validates bundle integrity and fails.

**How to avoid:**
- Treat `.kicadagent` as atomic document: always write whole bundle in one operation (copy temp → replace)
- Use `NSFileCoordinator` for bundle writes on all platforms
- On conflict: detect via `NSFileVersion`, alert user "Project edited on another device — which version wins?"
- Never auto-merge KiCad files — binary merge corrupts S-expressions
- Store conversation journal separately (CloudKit) — survives bundle conflicts

**Warning signs:**
- KiCad refuses to open `.kicadagent` bundle
- `.kicad_sch` opens but reports "corrupted UUIDs"
- iCloud Drive shows "conflict copy" alongside original

**Phase to address:**
Track G Phase 190 (iCloud Drive documents) — MUST test simultaneous edit scenario

---

### Pitfall 7: MLX-Swift Metal Memory Pressure (P1)

**What goes wrong:**
On 8GB Macs, app OOM crashes when loading 4B parameter model. GPU memory fills, system begins swapping, Metal kills context. Users report "app slows down then disappears."

**Why it happens:**
MLX-Swift loads full model into VRAM. 4B model at 4-bit quantization = ~2.5 GB VRAM. Plus 100MB Swift app, plus Metal allocation overhead, plus system GPU usage = exceeds 8GB device capacity.

**How to avoid:**
- Detect available VRAM at startup: `Metal.device.totalMemory > 3_000_000_000` for 4B model
- Dynamic model selection: 4B on 16GB+ Macs, 2B on 8GB
- Quantization tier: Q4 on 16GB+, Q2 on 8GB
- Release model context between operations: `model.unload()` when idle
- Show VRAM usage in UI: warn user before loading model

**Warning signs:**
- App OOM on MacBook Air 8GB
- Metal log shows "out of memory" errors
- System lag before crash

**Phase to address:**
Track B Phase 165 (MLX-Swift models) — MUST test on 8GB M1 MacBook Air

---

### Pitfall 8: SwiftData Query Performance with Millions of Events (P1)

**What goes wrong:**
After 6 months of use, Decision Timeline UI takes 10+ seconds to load. App becomes unusable. Query planner shows full table scan on `events` table with 2M+ rows.

**Why it happens:**
SwiftData generates naive SQL queries without proper indexes. Event sourcing appends millions of `DecisionEvent` rows. Materialized view queries (e.g., "show current component state") require full event replay.

**How to avoid:**
- Add indexes on all query predicates: `@Attribute(.unique)` on event UUID, index on `timestamp`
- Materialized views: maintain snapshot state in SwiftData, don't replay events on every query
- Pagination: Decision Timeline loads chunks, not entire history
- Partition events by project: separate `Event` per `ProjectID` (query pruning)
- Event compaction: archive old events to separate store, keep active project events < 100K

**Warning signs:**
- UI slows down over time
- `NSFetchRequest` takes >1 second in Instruments
- SQLite `EXPLAIN QUERY PLAN` shows full table scan

**Phase to address:**
Track E Phase 175 (event sourcing) — MUST test with 100K event dataset

---

### Pitfall 9: App Store Review GPL Licensing Rejection (P0)

**What goes wrong:**
App submission rejected for "GPL license violation" because app bundles kicad-cli (GPLv3). Review requires "proof of license compliance" but app is closed-source paid product.

**Why it happens:**
KiCad is GPLv3. Bundling kicad-cli means entire app becomes GPLv3 unless KiCad is a separate "system tool" invoked via subprocess. Apple reviews bundled binaries, not subprocess invocation.

**How to avoid:**
- Do NOT bundle kicad-cli in `.app/Contents/MacOS/` or `.app/Contents/Resources/`
- Require user to install KiCad separately (from kicad.org) — app detects via `which kicad-cli`
- Show helpful install prompt with link to kicad.org
- Document in App Store review notes: "App requires KiCad 10+ installed separately"
- For Windows v7+: include KiCAD installer in app installer, not in app bundle

**Warning signs:**
- App review rejection citing "open source license"
- Review asks for "source code availability"

**Phase to address:**
Track A Phase 162 (kicad-cli integration) — MUST pass App Store review with external kicad-cli

---

### Pitfall 10: CKShare Participant Permission Edge Cases (P2)

**What goes wrong:**
Owner shares project via CKShare with "view" permission. Collaborator edits offline, then reconnects. CKShare metadata says "view" but collaborator has local edits. Sync fails with "permission denied" but no UI explains why.

**Why it happens:**
CKShare permissions are enforced server-side. Local edits are allowed. On sync, server rejects writes due to permission mismatch. But CKShare doesn't expose "write rejected because of permission" error — just generic "sync failed."

**How to avoid:**
- Check `CKShare.userRole` before allowing edits: if `.viewer`, disable edit UI entirely
- On permission change (owner upgrades viewer → editor), force app reload to apply new ACL
- Offline edits: queue in local store, show "waiting for permission upgrade" alert
- Never rely on server-side rejection as UX — enforce permissions client-side first

**Warning signs:**
- Collaborator reports "can edit but sync fails"
- CKShare `.participantStatus` shows `.pending` indefinitely
- No error UI despite sync failure

**Phase to address:**
Track G Phase 192 (CKShare invites) — MUST test permission downgrade scenario

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| **Bundling kicad-cli to simplify install** | Users don't need KiCad installed | App Store rejection, GPL compliance burden, app bloat (500MB+) | NEVER — external install only |
| **Hard-coded FoundationModels assumption** | Faster development, no fallback logic | Intel Macs get broken app, bad reviews | NEVER — graceful degradation required |
| **Auto-merge SwiftData schema migrations** | Faster development, no migration code | Data loss on schema drift, sync failures | NEVER — explicit migrations only |
| **Mixed stdio + HTTP MCP** | Quick debug in browser, production stdio | Confusing architecture, security surface | v1.0 MVP only — remove HTTP before ship |
| **Snapshot tests with dated fixtures** | Tests pass, no flakiness | Tests fail in 2 weeks when dates/models change | NEVER — use frozen time in tests |
| **Event sourcing without compaction** | Simple architecture, no archive logic | Query degradation, OOM after months | v1.0 acceptable, compaction by v1.1 |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **PyInstaller + code signing** | Sign app bundle only, ignore embedded dylibs | Sign every dylib individually before packaging, verify with `codesign -dv` |
| **stdio MCP** | Assume stdout flushes on newline | Force line buffering with `PYTHONUNBUFFERED=1` or `-u` flag |
| **FoundationModels** | Crash on `.unavailable` | Check availability at launch, fallback to MLX-Swift + HF download |
| **CloudKit + SwiftData** | Auto-migrate schema on version mismatch | Explicit `VersionedSchema` migration plan, two-device sync test |
| **iCloud Drive bundles** | Write individual files in bundle | Atomic bundle replace via `NSFileCoordinator` |
| **CKShare** | Rely on server-side permission enforcement | Check `userRole` client-side before allowing operations |
| **Group Activities** | Assume all participants receive same messages | Handle out-of-order arrival, version per message, replay tolerance |
| **MLX-Swift** | Load largest model unconditionally | Detect VRAM, quantize down on 8GB devices |
| **App Store review** | Bundle GPL tool, hope reviewer misses it | External tool install, documented in review notes |
| **MCP stdio buffering** | Write partial JSON lines (streaming) | Always delimit with `\n`, never mix binary/text |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| **SwiftData events without pagination** | Decision Timeline loads slowly after months | Pagination, partition by project, index timestamp | 100K+ events |
| **Event replay without snapshots** | Restoring checkpoint takes minutes | Snapshot every 100 events, replay from nearest snapshot | 10K+ events |
| **MLX-Swift model not released** | Metal memory fills, OOM crashes | Explicit `model.unload()` when idle, VRAM monitoring | 8GB devices |
| **CKShare full sync on every change** | Group Activities lag, messages dropped | Delta sync, version per message, batch 10msg/sec | 5+ participants, rapid edits |
| **Generative transform without caching** | Re-generating same intent is slow | Cache hash→artifact, invalidate on upstream change | Repeated undo/redo |
| **iCloud Drive conflict copies proliferation** | Drive fills with `.conflict` files | Auto-resolve with prompt, detect via `NSFileVersion` | Multiple devices, simultaneous edit |
| **FoundationModels uncached embeddings** | Latency spikes on repeated queries | Cache embeddings locally (SwiftData), TTL 24h | 1000+ queries/day |

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| **Keychain sync disabled by default** | User loses BYOK key on device swap, no recovery | iCloud Keychain opt-out only, force user to explicitly disable, warn on disable |
| **HTTP MCP enabled by default** | Local network exposure, MITM on public WiFi | HTTP off by default, require localhost only, auth token for LAN access |
| **FoundationModels without privacy prompt** | App Store rejection, user distrust | Show "AI features use Apple Intelligence" on first use, link to privacy policy |
| **MLX-Swift model download without hash verification** | Supply chain attack via poisoned HF Hub | Verify SHA256 of downloaded `.safetensors` against known-good manifest |
| **CKShare without participant limit** | Spam invites, privacy leak | Cap at 4 participants v1.0, require explicit upgrade |

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| **Time-travel without context** | User restores checkpoint but doesn't understand what changed | Decision Timeline highlights changes between checkpoints, diff view |
| **Generative opacity** | "Why did it make this routing decision?" | Link decision → artifact in UI, show operation list |
| **Collaborative permission confusion** | "Why can't I edit?" | Clear permission badge, request edit action (sends notification to owner) |
| **KiCad external install friction** | User downloads app, can't use it without KiCad | Onboarding shows KiCad install link, auto-detect after install |
| **Event timeline clutter** | 1000 events, impossible to find decision | Chapter segmentation (intent → spec → roadmap), filter by type |
| **Model download silent failure** | "AI features don't work" with no error | Progress bar, retry button, error explanation |
| **Conflict resolution hidden** | "Why is there a duplicate project?" | Proactive conflict UI, side-by-side diff, choose-or-merge |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **PyInstaller build:** Often missing dylib signing — verify with `codesign -dv` on ALL embedded libs
- [ ] **stdio MCP:** Often works locally but deadlocks under load — stress test with 100 rapid RPC calls
- [ ] **FoundationModels:** Often works on M-series Mac only — test availability stub or Intel Mac
- [ ] **SwiftData migration:** Often works on single device — test two-device schema drift scenario
- [ ] **Generative hash:** Often deterministic-ish — run 10x with same inputs, assert identical hashes
- [ ] **CKShare permissions:** Often works for owner — test viewer role downgrade, offline edit
- [ ] **Group Activities:** Often works on single device — requires 2+ physical devices (no simulator)
- [ ] **iCloud bundles:** Often works on single device — test simultaneous edit on Mac + iPhone
- [ ] **App Store review:** Often passes internal review — submit test flight, verify GPL handling
- [ ] **A11y:** Often "VoiceOver talks" — test Dynamic Type XXXL, keyboard nav, high contrast mode

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| **PyInstaller dylib unsigned** | MEDIUM | Re-sign all dylibs, rebuild app, deploy hotfix |
| **stdio MCP deadlock** | LOW | Watchdog auto-restarts daemon, user retries operation (auto-save prevents loss) |
| **FoundationModels unavailable** | LOW | Fallback to MLX-Swift + HF download (slower but functional) |
| **SwiftData migration failure** | HIGH | Schema rollback, export data, manual migration, re-sync |
| **Generative hash drift** | MEDIUM | Pin canonical JSON format, re-hash existing events, data loss unlikely |
| **iCloud bundle corruption** | MEDIUM | Recover from CloudKit `NSFileVersion` older copy, manual merge |
| **MLX-Swift OOM** | LOW | Auto-downgrade to 2B model, warn user, reload |
| **App Store GPL rejection** | HIGH | External kicad-cli requirement, re-submit with review notes |
| **CKShare permission desync** | LOW | Force app reload to fetch latest ACL, client-side permission check |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls. **Corrected per Council Gate 1 review (2026-07-07).**

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| **PyInstaller dylib signing** | Track A Phase 162 | `codesign -dv` on clean machine, no "code signature invalid" in logs |
| **stdio MCP deadlock** | Track C Phase 167 | Stress test 100 RPC calls in 10 seconds, zero hangs |
| **FoundationModels unavailable** | Track B Phase 164 | Run on Intel Mac or with availability stub, fallback to MLX-Swift |
| **SwiftData migration loss** | Track E Phase 177 | Two-device migration test (Phone v1.0, Mac v1.1, verify sync) |
| **Generative hash instability** | Track F Phase 184 (10-run test) + Phase 183 (gold master) | 10-run determinism test, all hashes identical |
| **iCloud bundle corruption** | Track G Phase 190 | Simultaneous edit Mac + iPhone, verify atomic bundle replace |
| **MLX-Swift OOM** | Track B Phase 164 (Task 3: VRAM detection) | Run on 8GB M1 MacBook Air, 4B model loads without swap |
| **App Store GPL rejection** | Track A Phase 163 | TestFlight submission passes, external kicad-cli install documented |
| **CKShare permission edge cases** | Track G Phase 188 | Permission downgrade test (editor → viewer, verify edit disabled) |
| **Group Activities state desync** | Track G Phase 187 | 2-device rapid edit test, verify message ordering |
| **SwiftData query slowdown** | Track E Phase 178 + Phase 180 | Load 100K events, Decision Timeline < 2 seconds |
| **Snapshot test fragility** | Track H Phase 192 | Run 4-variant snapshot test 10x, zero flakes |
| **A11y gaps** | Track H Phase 201 | VoiceOver + Dynamic Type XXXL on all views |

## Sources

### HIGH Confidence (Official Documentation)
- **Apple Code Signing** — code signing requirements, hardened runtime, dylib signing
- **FoundationModels** — availability checks, graceful degradation patterns
- **SwiftData + CloudKit** — migration strategies, two-device sync testing
- **CKShare** — permission roles, ACL enforcement, edge cases
- **Group Activities** — session lifecycle, message ordering, simulator limitations
- **App Store Review** — GPL licensing, bundled binaries, external tool requirements
- **MLX-Swift** — Metal memory management, VRAM detection, model loading
- **iCloud Drive** — `NSFileCoordinator` for atomic bundle writes

### HIGH Confidence (Post-Mortems / Community)
- **PyInstaller code signing corruption** — multiple HN/reddit threads on dylib signing failures
- **stdio buffering deadlocks** — Python subprocess documentation, Swift `Process` known issues
- **SwiftData migration data loss** — Swift Forums threads on CloudKit schema drift
- **CKShare permission edge cases** — developer forums on "sync failed with permission denied"
- **iCloud Drive conflict copies** — StackOverflow on bundle corruption scenarios

### MEDIUM Confidence (Common Patterns)
- **Generative transform hash instability** — Similar to event-sourcing replay bugs in other systems
- **Snapshot test fragility** — Known issue in snapshot testing, fixed with frozen time fixtures
- **A11y testing gaps** — Common in SwiftUI apps, requires explicit Dynamic Type testing

### LOW Confidence (Projected Risks)
- **Group Activities debugging difficulty** — Expected complexity from Apple's "no simulator" constraint, needs real-device testing
- **iPhone-to-Mac network edge cases** — Standard iCloud sync issues, applies to CKShare/cloudKit broadly

---
*Pitfalls research for: Native Mac+iPhone app with Python daemon, generative KiCad transforms, CloudKit sync*
*Researched: 2026-07-07*
*Confidence: HIGH*
