"""General-purpose in-memory LRU cache for kicad-agent.

Provides a simple, thread-safe key-value cache with TTL support and
LRU eviction. Designed as a lightweight utility that domain-specific
caches (ir_cache, project cache, etc.) can build on top of if needed,
or can be used directly for caching analysis results, validation outputs,
and other expensive computations.

Usage:
    from kicad_agent.cache import Cache

    cache = Cache(max_size=128, default_ttl_seconds=300)
    cache.put("erc_result:board.kicad_sch", result_data)
    data = cache.get("erc_result:board.kicad_sch")
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    """A single cache entry with optional TTL.

    Attributes:
        value: The cached value.
        expires_at: Unix timestamp when this entry expires, or 0 for no expiry.
        created_at: Unix timestamp when this entry was created.
    """

    value: Any
    expires_at: float = 0.0
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        """Check if this entry has passed its TTL."""
        return self.expires_at > 0 and time.time() > self.expires_at


class Cache:
    """Thread-safe LRU cache with optional TTL expiration.

    Args:
        max_size: Maximum number of entries before LRU eviction.
        default_ttl_seconds: Default TTL in seconds for entries. 0 means no expiry.
    """

    def __init__(self, max_size: int = 64, default_ttl_seconds: float = 0.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        """Current number of entries."""
        with self._lock:
            return len(self._store)

    def get(self, key: str) -> Any | None:
        """Retrieve a value by key. Returns None if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return entry.value

    def put(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        """Store a value with an optional per-entry TTL override."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expires_at = time.time() + ttl if ttl > 0 else 0.0
        entry = CacheEntry(value=value, expires_at=expires_at)

        with self._lock:
            if key in self._store:
                del self._store[key]
            elif len(self._store) >= self._max_size:
                self._store.popitem(last=False)
            self._store[key] = entry

    def has(self, key: str) -> bool:
        """Check if a non-expired entry exists for key."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            if entry.is_expired:
                del self._store[key]
                return False
            return True

    def invalidate(self, key: str) -> bool:
        """Remove a single entry. Returns True if it existed."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    def purge_expired(self) -> int:
        """Remove all expired entries. Returns count of purged entries."""
        with self._lock:
            expired_keys = [
                k for k, v in self._store.items() if v.is_expired
            ]
            for k in expired_keys:
                del self._store[k]
            return len(expired_keys)

    def keys(self) -> tuple[str, ...]:
        """Return all non-expired keys."""
        with self._lock:
            return tuple(
                k for k, v in self._store.items() if not v.is_expired
            )
