"""Token bucket rate limiter for GitHub API calls.

Monitors PyGithub's rate limit headers and sleeps when approaching limits.
Uses calculated sleep based on reset timestamp -- no hardcoded delays.
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Minimum remaining requests before we preemptively sleep
_THRESHOLD = 50


class RateLimiter:
    """Rate limiter that monitors GitHub API remaining requests.

    Uses PyGithub's get_rate_limit() to check remaining quota.
    Sleeps until reset time when remaining drops below threshold.
    """

    def __init__(self, github_client) -> None:
        """Initialize with a PyGithub Github instance.

        Args:
            github_client: An authenticated github.Github instance.
        """
        self._client = github_client

    def wait_if_needed(self, limit_type: str = "core") -> None:
        """Check rate limit and sleep if remaining is below threshold.

        Args:
            limit_type: 'core' for general API, 'search' for search API.
        """
        rate_limit = self._client.get_rate_limit()
        if limit_type == "search":
            resource = rate_limit.search
        else:
            resource = rate_limit.core

        if resource.remaining < _THRESHOLD:
            now = datetime.now(timezone.utc)
            sleep_seconds = (resource.reset.replace(tzinfo=timezone.utc) - now).total_seconds()
            if sleep_seconds > 0:
                logger.warning(
                    "Rate limit approaching (%d remaining), sleeping %.0f seconds until reset",
                    resource.remaining,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds + 1)  # +1s buffer

    @property
    def remaining(self) -> int:
        """Current remaining core API requests."""
        return self._client.get_rate_limit().core.remaining
