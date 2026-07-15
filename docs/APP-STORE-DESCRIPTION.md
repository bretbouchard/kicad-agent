# volta — App Store Description

**Version 6.0 · 2026-07-14**

---

## Short Description (30 words)

> Describe a circuit in plain English, get a real KiCad schematic you can edit, validate, and send to a fab house. No EDA experience required.

## Subtitle (30 chars)

> Words-to-board for makers

## Promotional Text (170 chars)

> Type "18dB guitar preamp" — get the schematic, the SPICE-verified gain, the PCB layout, and the JLCPCB manufacturing files. v6 ships native ERC and local MLX inference.

---

## Full Description

**volta turns words into KiCad schematics.**

You describe the circuit. volta designs it. The output is a real `.kicad_sch` file — openable in KiCad 10, editable by hand, and ready to route.

### What you do

Open a project. Type what you want in plain English:

- *"12V LED driver with PWM dimming, 1A output"*
- *"ESP32-S3 dev board with USB-C and 4MB flash"*
- *"Non-inverting op-amp preamp, 20dB gain, 9V battery"*

volta uses a local MLX language model (or your API key for cloud) to draft a KiCad schematic with parts, nets, and pin connections. The assistant streams its work, attaches the schematic as you go, and you can copy the conversation to a clipboard at any time.

### What you get

- **Native KiCad schematic** — `.kicad_sch` you can open in KiCad 10
- **Native ERC** — pin-type, power-net, no-connect, and dangling-wire checks run instantly without KiCad CLI (`Phase 231`)
- **Native DRC** — copper spacing, courtyard overlap, annular ring checks (`Phase 232`)
- **Inline previews** — schematic SVG and PCB PNG rendered directly in chat (`Phase 233`)
- **Manufacturer handoff** — Gerbers, drill, BOM, pick-and-place, STEP, manifest, README for JLCPCB, PCBWay, AISLER, OSH Park (`Phase 208`)
- **Vendor DRC profiles** — rule packs tuned to specific fab houses (`Phase 206`)

### Who it's for

- **Makers and hobbyists** who have an idea but find KiCad too steep
- **Engineers** who want to rough out a topology before opening the EDA tool
- **Educators** teaching circuits without the tool-tax
- **Inventors** prototyping a one-off board without a $5K/seat Altium license
- **Synth / pedal / keyboard / ham / LED DIY communities** — see our community-specific templates (in roadmap)

### What volta does NOT do (yet)

We're honest about scope:

- **No automatic full PCB layout.** You get a schematic and a routing plan; final placement and routing are still a human-in-the-loop step using Freerouting or KiCad's router.
- **No Altium / Eagle import.** KiCad 10+ native only.
- **No real-time multi-user collaboration.** CloudKit sync is scaffolded; live cursors are not.
- **No vision input yet** (camera → schematic). The MLX vision adapter is trained but the UI hook is coming in a follow-up.
- **No high-speed design rules** (impedance control, length matching, eye diagrams).

The full feature inventory is in `FEATURE-INVENTORY.md`. The honest gap list is in `GAP-ANALYSIS-CURRENT.md`.

### Why we built it

Most people with a circuit idea never get past the KiCad learning curve. They give up, hire someone, or build a breadboard. volta removes the first wall: getting from "I know what I want" to "I have a schematic I can edit." Everything past that — layout, fab, assembly — still benefits from a human eye, but the barrier to start drops to zero.

### Tech

- **Native macOS** — Swift 6.2, SwiftUI, SwiftData, Liquid Glass design system
- **Local MLX inference** — Qwen 2.5 0.5B / Gemma 4 12B / your own adapter, runs offline on Apple Silicon
- **Cloud providers** — Anthropic, OpenAI-compatible, Gemini, Ollama (BYOK; we never see your keys)
- **Python daemon** — 268 atomic operations, full KiCad parser, kicad-cli fallback
- **No telemetry** — your projects, models, and conversations stay on your Mac

### Privacy

volta runs locally. The Python daemon is local. Local models run on your GPU. When you use a cloud provider, your prompts go directly to that provider — volta does not proxy, log, or store them. See `PRIVACY.md`.

### Requirements

- macOS 26 (Tahoe) or later, Apple Silicon
- ~3 GB disk for the bundled Qwen 0.5B starter model
- (Optional) KiCad 10 if you want to open generated schematics in the full EDA tool

### In-app purchases

None. v6 is the free tier. v7 (planned) will offer a cloud-pro tier with shared rendering compute, but everything in v6 is yours forever.

### Support

- Docs: https://volta.dev/docs
- Issues: https://github.com/bretbouchard/volta/issues
- Community: Discord (link in app)

### License

Core daemon: Apache 2.0
macOS app: proprietary (App Store distribution)
Adapters: open weights on HuggingFace
