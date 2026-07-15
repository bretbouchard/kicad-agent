"""ADI footprint library -- on-demand manufacturer footprint and symbol fetching.

Provides local caching, SamacSys HTTP client, and KiCad library integration
for Analog Devices (and other manufacturer) parts.
"""

from volta.project.adi_library.types import (
    CacheEntry,
    CacheManifest,
    FetchResult,
)
from volta.project.adi_library.cache import FootprintCache
from volta.project.adi_library.client import SamacSysClient, SearchResult
from volta.project.adi_library.fetcher import AdiFetcher

__all__ = [
    "AdiFetcher",
    "CacheEntry",
    "CacheManifest",
    "FetchResult",
    "FootprintCache",
    "SamacSysClient",
    "SearchResult",
]
