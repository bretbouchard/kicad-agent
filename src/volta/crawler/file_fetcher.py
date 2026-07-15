"""Sparse file fetching from GitHub repos via Contents API.

Retrieves individual .kicad_sch and .kicad_pcb files without cloning
entire repositories. Uses PyGithub's get_contents() for single-file
access with base64 content decoding.

For repos larger than 1MB of KiCad files, this is orders of magnitude
faster than git clone.
"""

import base64
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from volta.crawler.github_discovery import KicadFilePair

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedFile:
    """Result of a single file fetch from GitHub.

    Attributes:
        repo_name: Full repo name (owner/repo).
        path: File path within the repo.
        local_path: Path to the downloaded local file.
        content_hash: SHA256 of raw file content for dedup.
    """

    repo_name: str
    path: str
    local_path: Path
    content_hash: str


class FileFetcher:
    """Fetch individual KiCad files from GitHub repos.

    Uses PyGithub Contents API to download files to a local staging
    directory. Files are written as raw text for subsequent parsing.
    """

    def __init__(self, github_client, staging_dir: Path, rate_limiter=None) -> None:
        """Initialize with PyGithub client and staging directory.

        Args:
            github_client: Authenticated github.Github instance.
            staging_dir: Local directory for downloaded files.
            rate_limiter: Optional RateLimiter for API throttling.
        """
        self._client = github_client
        self._staging_dir = staging_dir
        self._rate_limiter = rate_limiter
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    def fetch_file(self, repo_name: str, file_path: str) -> Optional[FetchedFile]:
        """Fetch a single file from a GitHub repo.

        Uses Contents API to get file content, decodes base64, writes
        to staging directory preserving the file extension.

        Args:
            repo_name: Full repo name (e.g. 'user/project').
            file_path: Path within the repo (e.g. 'board.kicad_pcb').

        Returns:
            FetchedFile with local path and content hash, or None if
            the file cannot be fetched (deleted, too large, etc).
        """
        try:
            repo = self._client.get_repo(repo_name)
            if self._rate_limiter:
                self._rate_limiter.wait_if_needed("core")

            contents = repo.get_contents(file_path)

            # PyGithub returns base64-encoded content
            if isinstance(contents, list):
                # get_contents returned a directory, not a file
                return None

            raw_content = base64.b64decode(contents.content)

            # Sanitize file_path for local filesystem (prevent path traversal)
            safe_name = Path(file_path).name
            if not safe_name.endswith((".kicad_sch", ".kicad_pcb")):
                return None

            # Create repo-specific subdirectory to avoid name collisions
            repo_dir = self._staging_dir / repo_name.replace("/", "_")
            repo_dir.mkdir(parents=True, exist_ok=True)
            local_path = repo_dir / safe_name

            local_path.write_bytes(raw_content)

            content_hash = hashlib.sha256(raw_content).hexdigest()

            return FetchedFile(
                repo_name=repo_name,
                path=file_path,
                local_path=local_path,
                content_hash=content_hash,
            )

        except Exception as e:
            logger.warning("Failed to fetch %s/%s: %s", repo_name, file_path, e)
            return None

    def fetch_pair(
        self, repo_name: str, pair: "KicadFilePair"
    ) -> tuple[Optional[FetchedFile], Optional[FetchedFile]]:
        """Fetch both files of a schematic+PCB pair.

        Args:
            repo_name: Full repo name.
            pair: KicadFilePair with schematic and PCB paths.

        Returns:
            Tuple of (schematic_file, pcb_file), either may be None
            if the fetch failed.
        """
        sch = self.fetch_file(repo_name, pair.schematic_path)
        pcb = self.fetch_file(repo_name, pair.pcb_path)
        return (sch, pcb)
