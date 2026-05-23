# Phase 12: ADI Footprint Library - Research

**Researched:** 2026-05-23
**Domain:** Manufacturer footprint/symbol fetching, KiCad library integration, HTTP client architecture
**Confidence:** MEDIUM

## Summary

Phase 12 adds on-demand fetching of ADI manufacturer footprints, symbols, and 3D models into KiCad library format. The core challenge is that **no public API exists** for either SamacSys (Component Search Engine) or Ultra Librarian (Cadence) -- the two primary sources ADI links to from product pages. Both require browser-based interaction or desktop applications (Library Loader) to download KiCad-compatible files.

This means Phase 12 must build an HTTP scraping/interaction layer rather than a clean API integration. The recommended approach uses httpx as the HTTP client, with a two-tier strategy: SamacSys Component Search Engine as the primary source (confirmed active, provides direct KiCad .kicad_mod and .kicad_sym downloads per part), with a local filesystem cache to avoid re-downloading. The module integrates with the existing `lib_table.py` for library registration and `lib_resolver.py` for footprint resolution.

**Primary recommendation:** Build a `kicad_agent.project.adi_library` module using httpx for HTTP interaction, SamacSys Component Search Engine as the primary download source, and a local directory cache structure that integrates with the existing LibTable registration system. Fall back to manual ZIP upload if automated download fails.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADI-01 | ADI footprints discoverable by part number | SamacSys CSE search endpoint investigation; httpx client with retry/resilience patterns |
| ADI-02 | .kicad_mod footprints download and import into local library | SamacSys provides per-part KiCad downloads; kiutils 1.4.8 can validate .kicad_mod files post-download |
| ADI-03 | .kicad_sym symbols download and import into local library | Same SamacSys download flow; kiutils validates .kicad_sym; LibTable.add() registers in sym-lib-table |
| ADI-04 | Library cache avoids re-downloading previously fetched parts | Local directory cache with part-number-based key; cache manifest JSON for metadata |

**Note:** ADI-01 through ADI-04 are referenced in ROADMAP.md but NOT formally defined in REQUIREMENTS.md. The planner should ensure formal requirement definitions are added before execution.
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Part number search/discovery | HTTP Client (httpx) | Local cache | External service interaction is inherently network-bound |
| File download (footprint/symbol) | HTTP Client (httpx) | Local cache | Downloads from SamacSys or Ultra Librarian; cache for re-use |
| File validation (post-download) | Parse layer (kiutils) | -- | Must validate .kicad_mod/.kicad_sym parse correctly before import |
| Library registration | lib_table.py | -- | Existing LibTable.add() handles sym-lib-table/fp-lib-table mutation |
| Cache management | Filesystem | JSON manifest | Simple directory-based cache with JSON metadata index |
| Footprint resolution | lib_resolver.py | -- | Existing resolver chain handles Library:Footprint -> .kicad_mod path |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 | HTTP client for fetching footprint files | Modern async-capable client with connection pooling, streaming, built-in timeouts, `raise_for_status()` pattern. Already installed but not in pyproject.toml [VERIFIED: pip3 show httpx] |
| kiutils | 1.4.8 | Validate downloaded .kicad_mod and .kicad_sym files | Already in project; used to parse and verify downloaded KiCad files are valid before import [VERIFIED: pip3 show kiutils] |
| sexpdata | 1.0.0 | S-expression parsing for validation | Already in project; fallback parser for files kiutils cannot handle [VERIFIED: pip3 show sexpdata] |
| pydantic | 2.12.5 | Schema for cache manifest and fetch results | Already in project; consistent with project-wide Pydantic v2 pattern [VERIFIED: pip3 show pydantic] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| zipfile (stdlib) | 3.11+ | Extract downloaded ZIP archives from SamacSys | SamacSys delivers KiCad libraries as .zip files containing .kicad_mod/.kicad_sym |
| hashlib (stdlib) | 3.11+ | Content hashing for cache integrity | Verify downloaded files match expected content; detect corruption |
| shutil (stdlib) | 3.11+ | Filesystem operations for cache management | Move/copy downloaded files into cache directory structure |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx | requests | httpx provides async support, HTTP/2, and streaming that requests lacks; httpx already installed |
| httpx | urllib (stdlib) | urllib lacks connection pooling, retry, and modern timeout patterns; not worth the complexity savings |
| SamacSys scraping | Ultra Librarian scraping | Ultra Librarian URLs broken post-Cadence acquisition (search returns 404); SamacSys is confirmed active |
| SamacSys scraping | Manual ZIP upload | Manual upload is a valid fallback tier but defeats "on-demand" goal; keep as fallback only |

**Installation:**
```bash
# httpx already installed (v0.28.1) but needs adding to pyproject.toml
# Add to dependencies list:
# "httpx>=0.28.0",
```

**Version verification:**
- httpx: 0.28.1 [VERIFIED: pip3 show httpx, 2026-05-23]
- kiutils: 1.4.8 [VERIFIED: pip3 show kiutils, 2026-05-23]
- sexpdata: 1.0.0 [VERIFIED: pip3 show sexpdata, 2026-05-23]
- pydantic: 2.12.5 [VERIFIED: pip3 show pydantic, 2026-05-23]

## Architecture Patterns

### System Architecture Diagram

```
Part Number Input
      |
      v
[ADI Library Client] --(httpx GET)--> [SamacSys Component Search Engine]
      |                                      |
      |                          HTML/JSON response with
      |                          download links
      v                                      |
[Cache Lookup] <---------- Cache Miss -------+
      |                          |
   Cache Hit                 Cache Miss
      |                          |
      v                          v
[Return Cached Path]    [Download .zip via httpx]
                                   |
                                   v
                          [Extract .zip (zipfile)]
                                   |
                          +--------+--------+
                          |                 |
                          v                 v
                   [.kicad_mod]      [.kicad_sym]
                          |                 |
                          v                 v
                   [kiutils validate] [kiutils validate]
                          |                 |
                          v                 v
                   [Write to Cache Dir] [Write to Cache Dir]
                          |                 |
                          v                 v
                   [LibTable.add()]   [LibTable.add()]
                   (fp-lib-table)     (sym-lib-table)
                          |                 |
                          +--------+--------+
                                   |
                                   v
                          [Return Library Paths]
                                   |
                                   v
                          [lib_resolver.py can now resolve]
                          ("ADI_Local:AD8606ARMZ" -> .kicad_mod)
```

### Recommended Project Structure
```
src/kicad_agent/project/
    adi_library/              # New module for Phase 12
        __init__.py           # Barrel exports (following project/ pattern)
        client.py             # SamacSys HTTP client (httpx-based)
        cache.py              # Local filesystem cache with JSON manifest
        fetcher.py            # High-level fetch workflow (search -> download -> validate -> register)
        types.py              # Frozen dataclasses and Pydantic models
    __init__.py               # Updated barrel exports
    lib_table.py              # Existing -- used for library registration
    design_rules.py           # Existing -- not modified
    project_file.py           # Existing -- not modified

tests/
    test_adi_library.py       # Unit + integration tests for the module
    test_adi_cache.py         # Cache-specific tests (tmp_path fixtures)
    fixtures/                 # Sample .kicad_mod/.kicad_sym for validation tests
```

### Pattern 1: HTTP Client with Retry and Timeouts
**What:** Robust HTTP client for fetching from external services with configurable retry and timeout
**When to use:** All external HTTP interactions in this module
**Example:**
```python
# Source: httpx documentation (python-httpx.org)
import httpx

client = httpx.Client(
    timeout=httpx.Timeout(30.0, connect=10.0),
    follow_redirects=True,
    headers={"User-Agent": "kicad-agent/0.1.0"},
)

try:
    response = client.get(url)
    response.raise_for_status()  # Raises httpx.HTTPStatusError for 4xx/5xx
except httpx.TimeoutException:
    # Handle timeout
    pass
except httpx.HTTPStatusError as e:
    # Handle HTTP errors
    pass
```

### Pattern 2: Cache Directory with JSON Manifest
**What:** Local filesystem cache using part numbers as keys, JSON manifest for metadata
**When to use:** Every fetch operation checks cache first, writes to cache on miss
**Example:**
```python
# Source: Project convention (frozen dataclasses, Pydantic models)
from dataclasses import dataclass
from pathlib import Path
from pydantic import BaseModel

class CacheEntry(BaseModel):
    """Pydantic model for cache manifest entries."""
    part_number: str
    source: str  # "samacsys" | "ultralibrarian" | "manual"
    footprint_path: str | None = None
    symbol_path: str | None = None
    model_3d_path: str | None = None
    downloaded_at: str  # ISO 8601 timestamp
    content_hash: str   # SHA256 of downloaded archive

@dataclass(frozen=True)
class FetchResult:
    """Immutable result of a footprint fetch operation."""
    part_number: str
    footprint_path: Path | None
    symbol_path: Path | None
    model_3d_path: Path | None
    source: str
    from_cache: bool
```

### Pattern 3: Library Registration via Existing LibTable
**What:** Register downloaded libraries in sym-lib-table/fp-lib-table using existing `LibTable.add()`
**When to use:** After successful download and validation
**Example:**
```python
# Source: Existing lib_table.py pattern
from kicad_agent.project.lib_table import LibEntry, LibTable, parse_lib_table, serialize_lib_table

def register_adi_library(
    project_dir: Path,
    lib_type: str,  # "sym_lib_table" or "fp_lib_table"
    lib_name: str,  # e.g., "ADI_Local"
    lib_path: Path,  # e.g., "${KIPRJMOD}/adi_cache/footprints"
) -> None:
    table_path = project_dir / ("sym-lib-table" if lib_type == "sym_lib_table" else "fp-lib-table")
    if table_path.exists():
        table = parse_lib_table(table_path)
    else:
        table = LibTable(table_type=lib_type)

    try:
        table.get(lib_name)  # Already registered
    except KeyError:
        table.add(LibEntry(
            name=lib_name,
            type="KiCad",
            uri=str(lib_path),
            descr="ADI parts fetched by kicad-agent",
        ))
        serialize_lib_table(table, table_path)
```

### Anti-Patterns to Avoid
- **Scraping without caching:** Every fetch hits the external service, even for the same part. Always check cache first.
- **Skipping validation:** Downloaded .kicad_mod/.kicad_sym files may be malformed. Always parse with kiutils before registering.
- **Hardcoding SamacSys URLs:** SamacSys may change their URL structure (Ultra Librarian already did after Cadence acquisition). Use configurable URL templates.
- **Blocking the main thread on downloads:** Use httpx sync client for simplicity but structure code so async migration is straightforward later.
- **Storing downloaded ZIPs in cache:** Extract and store only the .kicad_mod/.kicad_sym files; ZIPs waste disk space.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client with retry | Custom requests wrapper | httpx.Client with retry transport | Connection pooling, timeout management, redirect handling, streaming |
| ZIP extraction | Custom ZIP parser | zipfile stdlib | Handles encoding, symlinks, compression methods, security (path traversal in ZIPs) |
| S-expression validation | Custom parser | kiutils / sexpdata | Both already in project; handle all KiCad S-expression edge cases |
| Library table mutation | Direct file manipulation | lib_table.py LibTable.add() | Handles validation, deduplication, MAX_ENTRIES security, normalization |
| Content integrity | Custom checksum | hashlib.sha256 | stdlib, proven, fast |

**Key insight:** Phase 10 already built `lib_table.py` for exactly this use case -- registering new libraries in sym-lib-table/fp-lib-table. Phase 12 must reuse it, not build parallel library management.

## Common Pitfalls

### Pitfall 1: SamacSys API Not Publicly Accessible
**What goes wrong:** Attempting to call SamacSys REST API endpoints directly (e.g., `/ga/part/search`, `/part/search`) returns 500 or 400 errors.
**Why it happens:** SamacSys/Component Search Engine does not expose a public REST API. The search and download workflow is browser-based, likely requiring session cookies or CSRF tokens.
**How to avoid:** Scrape the HTML search page to extract download links, or use the Component Search Engine website's download button flow programmatically. Alternatively, accept that fully automated fetch may require the user to provide downloaded ZIP files, and build the import/cache pipeline to handle both automated and manual sources.
**Warning signs:** HTTP 400/500 responses from API endpoints; empty response bodies; redirect loops.

### Pitfall 2: Ultra Librarian URLs Broken After Cadence Acquisition
**What goes wrong:** Historical Ultra Librarian search URLs (e.g., `ultralibrarian.com/search?query=AD8606ARMZ`) return 404.
**Why it happens:** Cadence acquired Ultra Librarian and restructured their URL scheme. Old search patterns no longer work.
**How to avoid:** Do not rely on Ultra Librarian as primary source. Use SamacSys instead. If Ultra Librarian is needed, treat it as a manual fallback (user downloads and provides the file).
**Warning signs:** 404 responses from ultralibrarian.com; redirect to cadence.com domain.

### Pitfall 3: Downloaded Files Not Valid KiCad Format
**What goes wrong:** SamacSys downloads a .zip that contains files with .kicad_mod extension but the content is malformed or uses an incompatible format version.
**Why it happens:** SamacSys may generate files targeting older KiCad versions, or the download may be incomplete/corrupted.
**How to avoid:** Always validate downloaded files with kiutils before importing. If parsing fails, log the error and skip that file (do not register in lib table).
**Warning signs:** kiutils parse exceptions on downloaded files; unexpected file sizes (0 bytes, extremely small).

### Pitfall 4: ZIP Path Traversal in Downloaded Archives
**What goes wrong:** A malicious or poorly constructed ZIP archive contains entries with `../` paths that could write outside the cache directory.
**Why it happens:** ZIP files can contain arbitrary path entries, including relative paths that escape the target directory.
**How to avoid:** Use the existing `_validate_path()` pattern from `lib_table.py`. When extracting ZIPs, verify each entry's resolved path is within the cache directory before writing.
**Warning signs:** ZIP entries containing `..` or absolute paths.

### Pitfall 5: Duplicate Library Registration
**What goes wrong:** Fetching the same part twice creates duplicate entries in sym-lib-table or fp-lib-table.
**Why it happens:** Cache lookup fails or is bypassed, and LibTable.add() raises ValueError on duplicate name.
**How to avoid:** Always check cache first. Use LibTable.get() to check if library already registered before calling add(). Handle the KeyError gracefully.
**Warning signs:** ValueError from LibTable.add(); multiple entries for same part in cache manifest.

### Pitfall 6: SamacSys Rate Limiting or Blocking
**What goes wrong:** Rapid successive requests to SamacSys result in 429 (Too Many Requests) or IP blocking.
**Why it happens:** Automated scraping without rate limiting triggers anti-bot protections.
**How to avoid:** Implement configurable rate limiting in httpx client (e.g., 1 request per 2 seconds). Add exponential backoff on 429 responses. Cache aggressively to minimize requests.
**Warning signs:** HTTP 429 responses; connection timeouts after initial success; CAPTCHA pages.

## Code Examples

### SamacSys Search and Download Flow (Conceptual)
```python
# Source: [ASSUMED] based on SamacSys website investigation (componentsearchengine.com)
# SamacSys does not have a public API. The search flow is browser-based.
# This pattern uses httpx to scrape search results and extract download links.

import httpx
from pathlib import Path
from bs4 import BeautifulSoup  # Would need to add as dependency

# NOTE: BeautifulSoup is NOT currently in the project.
# The planner must decide: add it as a dependency, or use regex/sexpdata
# for simpler HTML parsing needs.

class SamacSysClient:
    """HTTP client for SamacSys Component Search Engine."""

    BASE_URL = "https://componentsearchengine.com"

    def __init__(self, cache_dir: Path) -> None:
        self.client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
        self.cache_dir = cache_dir

    def search_part(self, part_number: str) -> list[dict]:
        """Search for a part and return available download options."""
        response = self.client.get(
            f"{self.BASE_URL}/ga/part/search",
            params={"search": part_number},
        )
        response.raise_for_status()
        # Parse response -- structure depends on actual SamacSys response format
        # This is a placeholder; actual implementation must map the real response
        return []

    def download_kicad_library(self, part_id: str) -> Path:
        """Download KiCad library ZIP for a specific part."""
        response = self.client.get(
            f"{self.BASE_URL}/ga/part/download",
            params={"id": part_id, "format": "kicad"},
        )
        response.raise_for_status()
        zip_path = self.cache_dir / f"{part_id}.zip"
        zip_path.write_bytes(response.content)
        return zip_path
```

### Cache Manager Pattern
```python
# Source: Project convention (frozen dataclasses, Pydantic models, tmp_path fixtures)
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel


class CacheManifest(BaseModel):
    """Pydantic model for the cache manifest file."""
    version: str = "1.0"
    entries: dict[str, dict] = {}  # part_number -> metadata


class FootprintCache:
    """Local filesystem cache for downloaded footprints and symbols."""

    def __init__(self, cache_root: Path) -> None:
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.footprints_dir = cache_root / "footprints"
        self.symbols_dir = cache_root / "symbols"
        self.footprints_dir.mkdir(exist_ok=True)
        self.symbols_dir.mkdir(exist_ok=True)
        self.manifest_path = cache_root / "cache_manifest.json"
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> CacheManifest:
        if self.manifest_path.exists():
            data = json.loads(self.manifest_path.read_text())
            return CacheManifest.model_validate(data)
        return CacheManifest()

    def _save_manifest(self) -> None:
        self.manifest_path.write_text(
            self._manifest.model_dump_json(indent=2)
        )

    def is_cached(self, part_number: str) -> bool:
        return part_number in self._manifest.entries

    def get_cached_paths(self, part_number: str) -> dict[str, Path | None]:
        entry = self._manifest.entries.get(part_number, {})
        return {
            "footprint": (
                self.cache_root / entry["footprint_path"]
                if entry.get("footprint_path") else None
            ),
            "symbol": (
                self.cache_root / entry["symbol_path"]
                if entry.get("symbol_path") else None
            ),
        }

    def add_entry(
        self,
        part_number: str,
        source: str,
        footprint_path: Path | None = None,
        symbol_path: Path | None = None,
        content_hash: str = "",
    ) -> None:
        self._manifest.entries[part_number] = {
            "source": source,
            "footprint_path": str(footprint_path.relative_to(self.cache_root)) if footprint_path else None,
            "symbol_path": str(symbol_path.relative_to(self.cache_root)) if symbol_path else None,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": content_hash,
        }
        self._save_manifest()
```

### ZIP Extraction with Path Traversal Protection
```python
# Source: Security pattern from lib_table.py's _validate_path()
import zipfile
from pathlib import Path


def extract_zip_safe(zip_path: Path, target_dir: Path) -> list[Path]:
    """Extract ZIP archive with path traversal protection.

    Rejects entries that would escape target_dir.
    Returns list of extracted file paths.
    """
    extracted: list[Path] = []
    target_resolved = target_dir.resolve()

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # Skip directories
            if info.is_dir():
                continue

            # Resolve the target path and verify it stays within target_dir
            target_file = (target_dir / info.filename).resolve()

            if not str(target_file).startswith(str(target_resolved)):
                raise ValueError(
                    f"ZIP entry '{info.filename}' escapes target directory "
                    f"(path traversal attempt)"
                )

            # Extract
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(zf.read(info.filename))
            extracted.append(target_file)

    return extracted
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Ultra Librarian standalone | Ultra Librarian via Cadence | 2024-2025 (Cadence acquisition) | Old search URLs broken; Cadence integration changes access patterns |
| SamacSys Library Loader desktop app | Component Search Engine web | 2024+ | Web-based access may enable programmatic fetch without desktop app |
| Manual footprint creation | Manufacturer-provided CAD models | 2020s standard | ADI, TI, ST all provide footprint libraries via third parties |
| KiCad 6 footprint format (.kicad_mod) | Same format in KiCad 7/8/9/10 | Stable since KiCad 6 | .kicad_mod format stable; downloads from SamacSys are forward-compatible |

**Deprecated/outdated:**
- Ultra Librarian pre-Cadence search URLs: Return 404, no longer functional
- SamacSys GitHub repos (KiCad-SamacSys-Fetch, KiCadLibraryLoader): Both return 404 -- repositories removed or never existed at those URLs
- SamacSys REST API endpoints (`/ga/part/search`, `/part/search`): Return 500/400 errors -- not publicly accessible

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SamacSys Component Search Engine allows programmatic download of KiCad files | Standard Stack, Architecture | HIGH -- if blocked, entire automated approach fails; must fall back to manual ZIP upload |
| A2 | SamacSys delivers files as .zip containing .kicad_mod and .kicad_sym files | Code Examples, Architecture | MEDIUM -- format could be different (e.g., single file, different extension); affects extraction logic |
| A3 | kiutils 1.4.8 can parse all SamacSys-generated .kicad_mod/.kicad_sym files | Standard Stack | LOW -- kiutils is the standard parser; but format version mismatches are possible |
| A4 | No additional HTML parsing library needed (regex sufficient for extracting download links from SamacSys) | Standard Stack | MEDIUM -- if SamacSys pages are complex, BeautifulSoup or lxml may be needed as an additional dependency |
| A5 | SamacSys does not require authentication/cookies for KiCad downloads | Pitfalls, Architecture | HIGH -- if authentication is required, automated fetch is blocked |
| A6 | Downloaded .kicad_mod files use a compatible format version for KiCad 10 | Standard Stack | LOW -- KiCad format has been stable since v6 |

## Open Questions

1. **SamacSys Automated Download Feasibility**
   - What we know: SamacSys provides KiCad downloads on their website; API endpoints returned errors
   - What's unclear: Whether programmatic HTTP access to download links works without browser session/cookies
   - Recommendation: Plan includes a manual fallback tier (user provides ZIP file) so the project is not blocked if automated fetch fails

2. **BeautifulSoup Dependency Decision**
   - What we know: HTML parsing of SamacSys search results may be needed to extract download links
   - What's unclear: Whether regex-based parsing is sufficient for the SamacSys HTML structure
   - Recommendation: Start without BeautifulSoup; add it only if regex proves insufficient during implementation

3. **Cache Location Strategy**
   - What we know: Cache needs a standard location; project-local vs. global user cache
   - What's unclear: Whether to cache per-project (in `.kicad` project dir) or globally (in `~/.cache/kicad-agent/adi/`)
   - Recommendation: Default to project-local cache (`${KIPRJMOD}/.adi_cache/`) with configurable global cache option

4. **ADI-01 Through ADI-04 Formal Definitions**
   - What we know: These requirement IDs are referenced in ROADMAP.md but not defined in REQUIREMENTS.md
   - What's unclear: The exact wording and acceptance criteria for each requirement
   - Recommendation: Planner should define these formally before execution; the ROADMAP success criteria provide the basis

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| httpx | HTTP client for footprint downloads | Yes | 0.28.1 | -- |
| kiutils | Downloaded file validation | Yes | 1.4.8 | -- |
| sexpdata | S-expression fallback parsing | Yes | 1.0.0 | -- |
| pydantic | Cache manifest schema | Yes | 2.12.5 | -- |
| Python >=3.11 | zipfile, hashlib, shutil stdlib | Yes | 3.11+ | -- |
| pytest >=8.0 | Testing | Yes | 8.4.2 | -- |
| Internet connectivity | SamacSys downloads | Untested | -- | Manual ZIP upload fallback |

**Missing dependencies with no fallback:**
- None -- all required libraries are installed

**Missing dependencies with fallback:**
- Internet connectivity for SamacSys: Falls back to manual ZIP upload workflow (user downloads file and provides path)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `pytest tests/test_adi_library.py tests/test_adi_cache.py -x -q` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADI-01 | Part number search returns results or clear failure | unit + integration | `pytest tests/test_adi_library.py::test_search_part -x` | Wave 0 |
| ADI-02 | Downloaded .kicad_mod validates and registers | unit | `pytest tests/test_adi_library.py::test_fetch_footprint -x` | Wave 0 |
| ADI-03 | Downloaded .kicad_sym validates and registers | unit | `pytest tests/test_adi_library.py::test_fetch_symbol -x` | Wave 0 |
| ADI-04 | Cache prevents re-download of same part | unit | `pytest tests/test_adi_cache.py::test_cache_hit -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_adi_library.py tests/test_adi_cache.py -x -q`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_adi_library.py` -- covers ADI-01, ADI-02, ADI-03
- [ ] `tests/test_adi_cache.py` -- covers ADI-04
- [ ] `tests/fixtures/adi_cache/` -- sample .kicad_mod/.kicad_sym for validation tests
- [ ] `httpx>=0.28.0` added to pyproject.toml dependencies

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user auth in this module |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No access control |
| V5 Input Validation | yes | Part number validation (alphanumeric + dash only); ZIP path traversal protection; kiutils parse validation |
| V6 Cryptography | yes | SHA256 content hashing for cache integrity (hashlib stdlib) |

### Known Threat Patterns for HTTP Download + KiCad Pipeline

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| ZIP path traversal | Tampering | resolve() check against target directory; reject entries escaping cache dir |
| Malformed KiCad files | Tampering | kiutils parse validation before registration; catch parse exceptions |
| HTTP response tampering | Tampering | https:// only; httpx TLS verification (default on); content hash verification |
| Cache poisoning | Tampering | SHA256 content hash in manifest; verify on read |
| Rate limiting / DoS | Denial of Service | Configurable rate limit; backoff on 429; max retries |
| URI injection (lib table) | Tampering | Reuse lib_table.py _validate_uri() which blocks shell metacharacters |
| Cache directory traversal | Tampering | Part number validation (alphanumeric + dash only); no user-provided paths |

### Security Controls Inherited from Existing Code
- `lib_table.py`: `_SHELL_META_PATTERN` blocks backticks and command substitution in URIs
- `lib_table.py`: `_SAFE_ID_PATTERN` validates library names are safe identifiers
- `lib_table.py`: `MAX_ENTRIES = 1000` prevents table bloat DoS
- `lib_table.py`: `_validate_path()` blocks `..` traversal
- These controls apply automatically when using LibTable.add() for registration

## Sources

### Primary (HIGH confidence)
- pip3 show output: httpx 0.28.1, kiutils 1.4.8, sexpdata 1.0.0, pydantic 2.12.5, pytest 8.4.2
- Project source code: `src/kicad_agent/project/lib_table.py` -- LibTable, LibEntry, validation patterns
- Project source code: `src/kicad_agent/lib_resolver.py` -- footprint resolution chain
- Project config: `pyproject.toml` -- dependencies, tool configuration
- ROADMAP.md lines 237-246 -- Phase 12 definition, success criteria, requirement IDs

### Secondary (MEDIUM confidence)
- httpx documentation (python-httpx.org) -- Client API, timeouts, streaming patterns [CITED: python-httpx.org]
- SamacSys Component Search Engine (componentsearchengine.com) -- Confirmed active site providing KiCad downloads [CITED: componentsearchengine.com]
- Ultra Librarian (ultralibrarian.com) -- Confirmed KiCad format support but broken search URLs [CITED: ultralibrarian.com]

### Tertiary (LOW confidence)
- SamacSys download workflow (browser-based) -- [ASSUMED] based on website investigation, not verified programmatically
- SamacSys ZIP file contents -- [ASSUMED] to contain .kicad_mod and .kicad_sym files
- SamacSys authentication requirements -- [ASSUMED] none needed for public downloads

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified installed, versions confirmed
- Architecture: MEDIUM -- integration points well understood, but SamacSys download flow unverified programmatically
- Pitfalls: HIGH -- SamacSys API failure confirmed (500/400 errors), Ultra Librarian 404 confirmed, GitHub repos confirmed 404
- Security: HIGH -- existing security controls from lib_table.py well documented; ZIP traversal pattern well known
- SamacSys automated fetch: LOW -- not verified programmatically; may require browser session/cookies

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (30 days -- stable libraries but SamacSys website behavior may change)
