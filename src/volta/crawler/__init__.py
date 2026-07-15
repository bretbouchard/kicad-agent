"""GitHub crawler for discovering KiCad repositories.

Provides GitHub API-based discovery of repos with .kicad_sch and .kicad_pcb
files, file pair extraction, and rate-limit-aware pagination.
"""

from volta.crawler.rate_limiter import RateLimiter
from volta.crawler.github_discovery import (
    GithubDiscovery,
    RepoInfo,
    KicadFilePair,
)
from volta.crawler.file_fetcher import FileFetcher

__all__ = [
    "GithubDiscovery",
    "FileFetcher",
    "RateLimiter",
    "RepoInfo",
    "KicadFilePair",
]
