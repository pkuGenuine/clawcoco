"""Tests for github_ip module."""

import pytest
import pytest_httpx
from httpx import AsyncClient

from clawcoco.github_ip import DEFAULT_GITHUB_IP_RANGES, GitHubIPManager


class TestGitHubIPManager:
    """Tests for GitHubIPManager class."""

    @pytest.mark.asyncio
    async def test_fetch_updates_ranges(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ) -> None:
        """Should fetch and update IP ranges from GitHub API."""
        httpx_mock.add_response(
            url="https://api.github.com/meta",
            json={"hooks": ["1.2.3.4/24", "5.6.7.8/24"]},
        )

        manager = GitHubIPManager()
        async with AsyncClient() as client:
            await manager.initialize(client)

        assert manager.get_ranges() == ["1.2.3.4/24", "5.6.7.8/24"]
        assert manager.last_fetch is not None

    @pytest.mark.asyncio
    async def test_fallback_on_error(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """Should keep default ranges if fetch fails."""
        httpx_mock.add_exception(
            url="https://api.github.com/meta", exception=Exception("Network error")
        )

        manager = GitHubIPManager()
        async with AsyncClient() as client:
            await manager.initialize(client)

        assert manager.get_ranges() == DEFAULT_GITHUB_IP_RANGES
        assert manager.last_fetch is None
