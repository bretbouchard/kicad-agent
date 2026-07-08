# App Store Review Notes — KiCad Agent

**App:** KiCad Agent
**Bundle ID:** `com.kicadagent.app`
**Target:** macOS 27+ (Liquid Glass)
**Distribution:** Mac App Store (with notarized direct-download fallback)

---

## External Tool Requirement (Pitfall 9 Prevention)

**KiCad Agent requires KiCad 10+ to be installed separately.** The KiCad
CLI (`kicad-cli`) is **NOT bundled** with this app. Users install KiCad
from the official source: https://www.kicad.org/download/macos/

### Why kicad-cli is not bundled

KiCad is licensed under **GPLv3**, which is incompatible with the Mac App
Store's terms. Bundling kicad-cli inside the `.app` package would constitute
distribution of GPLv3 code under more restrictive terms than GPLv3 permits,
which would violate both the GPL and Mac App Store Review Guideline 2.6.

This app invokes `kicad-cli` exclusively as an **external subprocess** owned
by the end user. No GPL code is linked, modified, or distributed within
the app bundle.

### How the app handles the external dependency

1. **First-run onboarding.** On launch, the app probes for `kicad-cli` via
   `which kicad-cli`, then falls back to `/Applications/KiCad/kicad-cli`,
   `/usr/local/bin/kicad-cli`, and `/opt/homebrew/bin/kicad-cli`. If not
   found, a dedicated onboarding sheet appears with a one-tap link to
   https://www.kicad.org/download/macos/ and a "check again" button that
   re-runs detection after the user installs KiCad.

2. **Version verification.** When `kicad-cli` is found, the app runs
   `kicad-cli --version` and parses the output. The app requires version
   10.0 or newer. KiCad 9.x and earlier are rejected with a clear message.

3. **Workflow gating.** The main chat workflow (project creation, schematic
   editing, PCB layout, ERC/DRC) is blocked until `kicad-cli` is verified
   as `.ready`. Users cannot accidentally start a design without a working
   KiCad install.

4. **Operation-time fallback.** If `kicad-cli` is uninstalled or broken
   mid-session, any operation that requires it (ERC, DRC, render, export)
   surfaces an inline error with a "Reinstall KiCad" deep-link back to the
   onboarding sheet.

### Analogous patterns on the App Store

This is the same pattern used by:

- **GitKraken / Tower** — require external `git` install on macOS
- **VS Code** — requires external language runtimes (Python, Node, etc.)
- **iTerm2** — invokes system `bash`, `zsh`, and other shells
- **BBEdit** — invokes external compilers and build tools

None of these bundle their respective GPL or system tools. KiCad Agent
follows the same convention.

### KiCad is never redistributed

KiCad Agent:

- Does not include the KiCad binary, source, or any GPL-covered KiCad code.
- Does not modify KiCad or its license terms.
- Does not misrepresent KiCad's authorship or provenance.
- Directs users to the official KiCad download page maintained by the
  KiCad project (a non-profit foundation).

Users who install KiCad do so under KiCad's own GPLv3 license, completely
independent of KiCad Agent.

---

## App Sandbox

KiCad Agent ships with the standard Mac App Store sandbox enabled.
Entitlements are limited to:

- `com.apple.security.app-sandbox` — base sandbox
- `com.apple.security.files.user-selected.read-write` — open KiCad project files
- `com.apple.security.network.client` — for BYOK cloud model providers
  (Anthropic, OpenAI, etc.) — opt-in only

The app does **not** request:

- `com.apple.security.network.server` for the default configuration (the
  optional External HTTP MCP server, when enabled, binds to `127.0.0.1`
  only and does not require server entitlements — it uses local HTTP)
- Camera, microphone, location, contacts, photos, or HomeKit access
- Full disk access

---

## External HTTP MCP Server (Optional, Off by Default)

KiCad Agent ships an **opt-in** local HTTP MCP server for users who want
to drive KiCad Agent from external clients like Claude Code, Cursor, or
custom scripts.

- **Default state:** OFF
- **Enable path:** Settings → External HTTP MCP → Toggle "Enable"
- **Binding:** `127.0.0.1` only — never exposed to network
- **Authentication:** 32-byte URL-safe base64 token required on every request
- **Rate limiting:** 10 requests/second per IP
- **Auto-revoke (DAEM-08):** 10 consecutive failed auth attempts disable
  the server and rotate the token. User is notified via in-app banner.
- **Token storage:** macOS Keychain (device-scoped, NOT iCloud-synced)

This server is for power users. The default configuration has zero network
exposure and no external attack surface.

---

## Privacy

- **No tracking.** The app does not collect telemetry, analytics, or crash
  reports without explicit user consent.
- **No account required.** Users can design PCBs without creating any account.
- **Local-first.** All model inference runs locally via FoundationModels by
  default. Cloud providers (Anthropic, OpenAI, Google, Groq, xAI, Together)
  are pure BYOK — user-supplied keys, direct API calls, no proxy.
- **iCloud Keychain sync** is on by default for API keys but can be opted out.
- **CloudKit** syncs conversation history across the user's Mac and iPhone
  via the user's private iCloud database — never to developer infrastructure.

---

## Pricing

KiCad Agent is a **paid app** with no in-app purchases, subscriptions, or
ads. The developer maintains zero ongoing infrastructure costs (no proxy
servers, no AI bill). The price covers ongoing development.

---

## Reviewer Guidance

To verify the external KiCad dependency:

1. Install KiCad 10+ from https://www.kicad.org/download/macos/
2. Launch KiCad Agent — the onboarding sheet should auto-dismiss.
3. Try creating a project and running an ERC. The operation should
   invoke `kicad-cli` and return results.
4. Quit, move KiCad to Trash, empty Trash, relaunch KiCad Agent. The
   onboarding sheet should re-appear.
5. Try the External HTTP MCP server (Settings → External HTTP MCP → Enable).
   Verify it binds to 127.0.0.1:8080 only (e.g. `curl http://127.0.0.1:8080/`
   from another terminal).

For questions, contact: support@kicadagent.app
