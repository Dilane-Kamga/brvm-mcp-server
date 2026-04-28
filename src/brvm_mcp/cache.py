"""
Cache layer for BRVM data.
Uses diskcache for persistent, TTL-based caching.
Respectful of source servers — default TTL is 5 minutes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import diskcache

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "brvm-mcp"
DEFAULT_TTL = 300  # 5 minutes — BRVM trades once daily, this is more than enough


class BRVMCache:
    """Simple disk-backed cache with TTL."""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR, ttl: int = DEFAULT_TTL):
        self.ttl = ttl
        self._cache = diskcache.Cache(str(cache_dir))
        logger.info(f"Cache initialized at {cache_dir} with TTL={ttl}s")

    def get(self, key: str) -> Any | None:
        """Get a value from cache, returns None if expired or missing."""
        value = self._cache.get(key)
        if value is not None:
            logger.debug(f"Cache HIT: {key}")
            return json.loads(value) if isinstance(value, str) else value
        logger.debug(f"Cache MISS: {key}")
        return None

    def set(self, key: str, value: Any) -> None:
        """Set a value in cache with TTL."""
        serialized = json.dumps(value, default=str)
        self._cache.set(key, serialized, expire=self.ttl)
        logger.debug(f"Cache SET: {key} (TTL={self.ttl}s)")

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        logger.info("Cache cleared")

    def close(self) -> None:
        self._cache.close()
