"""GitHub IP range management for webhook verification."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

# Default GitHub IP ranges for webhook delivery (fallback if fetch fails)
# https://api.github.com/meta
DEFAULT_GITHUB_IP_RANGES = [
    "192.30.252.0/22",
    "185.199.108.0/22",
    "140.82.112.0/20",
    "143.55.64.0/20",
]

GITHUB_META_URL = "https://api.github.com/meta"
IP_REFRESH_INTERVAL = timedelta(hours=24)


class GitHubIPManager:
    """Manages GitHub IP ranges with automatic refresh."""

    def __init__(self) -> None:
        self._ranges: list[str] = DEFAULT_GITHUB_IP_RANGES.copy()
        self._last_fetch: datetime | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._shutdown = False

    async def initialize(self, http_client: httpx.AsyncClient) -> None:
        """Initialize with HTTP client and fetch initial ranges."""
        self._http_client = http_client
        await self.fetch()
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def shutdown(self) -> None:
        """Stop background refresh task."""
        self._shutdown = True
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

    async def fetch(self) -> bool:
        """Fetch latest IP ranges from GitHub API."""
        if not self._http_client:
            logger.warning("HTTP client not initialized, using default ranges")
            return False

        try:
            response = await self._http_client.get(GITHUB_META_URL, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            # Extract webhook IP ranges
            if "hooks" in data and isinstance(data["hooks"], list):
                self._ranges = data["hooks"]
                self._last_fetch = datetime.now(timezone.utc)
                logger.info(f"Fetched {len(self._ranges)} GitHub IP ranges")
                return True
            else:
                logger.warning("No 'hooks' field in GitHub meta response")
                return False

        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch GitHub IP ranges: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error fetching GitHub IP ranges: {e}")
            return False

    async def _refresh_loop(self) -> None:
        """Background task to periodically refresh IP ranges."""
        while not self._shutdown:
            await asyncio.sleep(IP_REFRESH_INTERVAL.total_seconds())
            if not self._shutdown:
                success = await self.fetch()
                if not success:
                    logger.warning("IP range refresh failed, keeping current ranges")

    def get_ranges(self) -> list[str]:
        """Get current IP ranges."""
        return self._ranges

    @property
    def last_fetch(self) -> datetime | None:
        """Get timestamp of last successful fetch."""
        return self._last_fetch