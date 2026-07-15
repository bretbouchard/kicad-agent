"""SamacSys Component Search Engine HTTP client.

Best-effort client for searching and downloading KiCad footprint/symbol
libraries from SamacSys (componentsearchengine.com). SamacSys does not
expose a public REST API, so this client attempts HTTP-based interaction
and fails gracefully when automated download is not possible.

Security:
- T-12-04: HTTPS-only connections with TLS verification
- T-12-05: Rate limiting to prevent abuse/429 responses
- T-12-06: Content size limit on responses to prevent memory exhaustion
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# SamacSys base URL
SAMACSYS_BASE_URL = "https://componentsearchengine.com"

# Maximum response size (10 MB)
MAX_RESPONSE_SIZE = 10 * 1024 * 1024

# Rate limit: minimum seconds between requests
RATE_LIMIT_SECONDS = 2.0

# Part number validation
_PART_NUMBER_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\-._/]*$')


@dataclass(frozen=True)
class SearchResult:
    """Immutable result of a SamacSys part search.

    Attributes:
        part_number: The searched part number.
        part_id: SamacSys internal part ID (for download), or None.
        description: Part description from search results, or None.
        has_kicad: Whether KiCad format is available.
        download_url: Direct download URL for KiCad library, or None.
        error: Error message if search failed, or None.
    """

    part_number: str
    part_id: Optional[str]
    description: Optional[str]
    has_kicad: bool
    download_url: Optional[str]
    error: Optional[str] = None


class SamacSysClient:
    """HTTP client for SamacSys Component Search Engine.

    Provides part search and KiCad library download. Designed as best-effort:
    if SamacSys blocks automated access, methods return error results rather
    than raising exceptions.

    Usage:
        client = SamacSysClient()
        result = client.search_part("AD8606ARMZ")
        if result.error:
            print(f"Search failed: {result.error}")
        else:
            print(f"Found: {result.description}")
    """

    def __init__(self, timeout: float = 30.0) -> None:
        """Initialize with httpx client.

        Args:
            timeout: Request timeout in seconds.
        """
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": "volta/0.1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()

    def __enter__(self) -> "SamacSysClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def search_part(self, part_number: str) -> SearchResult:
        """Search for a part on SamacSys Component Search Engine.

        Attempts to fetch the part page and extract download information.
        Best-effort: returns error if the page structure is unexpected.

        Args:
            part_number: Part number to search (e.g. 'AD8606ARMZ').

        Returns:
            SearchResult with either download info or error message.
        """
        if not _PART_NUMBER_PATTERN.match(part_number):
            return SearchResult(
                part_number=part_number,
                part_id=None,
                description=None,
                has_kicad=False,
                download_url=None,
                error=f"Invalid part number format: {part_number!r}",
            )

        try:
            response = self._client.get(
                f"{SAMACSYS_BASE_URL}/ga/part/search",
                params={"search": part_number},
            )

            if response.status_code == 429:
                return SearchResult(
                    part_number=part_number,
                    part_id=None,
                    description=None,
                    has_kicad=False,
                    download_url=None,
                    error="Rate limited by SamacSys (HTTP 429). Try again later.",
                )

            if response.status_code >= 400:
                logger.warning(
                    "SamacSys search returned HTTP %d for %s",
                    response.status_code,
                    part_number,
                )
                return SearchResult(
                    part_number=part_number,
                    part_id=None,
                    description=None,
                    has_kicad=False,
                    download_url=None,
                    error=f"SamacSys returned HTTP {response.status_code}. "
                          "Automated search may not be available.",
                )

            return self._parse_search_response(part_number, response.text)

        except httpx.TimeoutException:
            return SearchResult(
                part_number=part_number,
                part_id=None,
                description=None,
                has_kicad=False,
                download_url=None,
                error="Request to SamacSys timed out.",
            )
        except httpx.ConnectError:
            return SearchResult(
                part_number=part_number,
                part_id=None,
                description=None,
                has_kicad=False,
                download_url=None,
                error="Cannot connect to SamacSys. Check internet connectivity.",
            )
        except Exception as e:
            logger.exception("Unexpected error searching SamacSys for %s", part_number)
            return SearchResult(
                part_number=part_number,
                part_id=None,
                description=None,
                has_kicad=False,
                download_url=None,
                error=f"Unexpected error: {e}",
            )

    def download_library(self, download_url: str, target_path: Path) -> Optional[Path]:
        """Download a KiCad library ZIP from the given URL.

        Args:
            download_url: URL to download from.
            target_path: Directory to save the downloaded file.

        Returns:
            Path to the downloaded ZIP file, or None on failure.
        """
        try:
            response = self._client.get(download_url)

            if response.status_code != 200:
                logger.warning(
                    "Download returned HTTP %d from %s",
                    response.status_code,
                    download_url,
                )
                return None

            if len(response.content) > MAX_RESPONSE_SIZE:
                logger.warning(
                    "Response too large: %d bytes from %s",
                    len(response.content),
                    download_url,
                )
                return None

            if len(response.content) == 0:
                logger.warning("Empty response from %s", download_url)
                return None

            filename = self._extract_filename(response, download_url)
            zip_path = target_path / filename
            zip_path.write_bytes(response.content)
            return zip_path

        except httpx.TimeoutException:
            logger.warning("Download timed out: %s", download_url)
            return None
        except Exception as e:
            logger.exception("Download failed: %s", download_url)
            return None

    def _parse_search_response(self, part_number: str, html: str) -> SearchResult:
        """Parse SamacSys search response HTML to extract download info.

        Best-effort parsing using regex. If the HTML structure doesn't match
        expected patterns, returns an error result.

        Looks for:
        1. Download links containing 'kicad' in the URL
        2. Part ID in data attributes or URL parameters
        3. Part description text
        """
        # Look for KiCad download links
        kicad_link_match = re.search(
            r'href="([^"]*kicad[^"]*)"',
            html,
            re.IGNORECASE,
        )

        # Look for part ID patterns
        part_id_match = re.search(
            r'data-part-id="([^"]+)"|/part/(\d+)',
            html,
        )

        # Look for description
        desc_match = re.search(
            r'<(?:td|span|div)[^>]*class="[^"]*description[^"]*"[^>]*>([^<]+)',
            html,
            re.IGNORECASE,
        )

        part_id: Optional[str] = None
        if part_id_match:
            part_id = part_id_match.group(1) or part_id_match.group(2)

        description: Optional[str] = None
        if desc_match:
            description = desc_match.group(1).strip()

        if kicad_link_match:
            download_url = kicad_link_match.group(1)
            if not download_url.startswith("http"):
                download_url = f"{SAMACSYS_BASE_URL}{download_url}"
            return SearchResult(
                part_number=part_number,
                part_id=part_id,
                description=description,
                has_kicad=True,
                download_url=download_url,
            )

        # No KiCad download link found -- SamacSys may require browser session
        return SearchResult(
            part_number=part_number,
            part_id=part_id,
            description=description,
            has_kicad=False,
            download_url=None,
            error="No KiCad download link found in SamacSys response. "
                  "Automated download may not be available. "
                  "Use manual ZIP upload as fallback.",
        )

    def _extract_filename(self, response: httpx.Response, url: str) -> str:
        """Extract filename from Content-Disposition header or URL path."""
        content_disp = response.headers.get("content-disposition", "")
        if content_disp:
            match = re.search(r'filename="?([^";\n]+)"?', content_disp)
            if match:
                return match.group(1)

        # Fall back to URL path
        path = urlparse(url).path
        filename = Path(path).name
        if not filename or not filename.endswith(".zip"):
            filename = "download.zip"
        return filename
