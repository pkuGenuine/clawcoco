"""Tests for agent module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawcoco.agent import OpenClawBackend, TriggerInfo
from clawcoco.config import Config


class TestOpenClawBackend:
    """Tests for OpenClawBackend class."""

    @pytest.fixture
    def backend(self, test_config: Config) -> OpenClawBackend:
        return OpenClawBackend(test_config)

    @pytest.fixture
    def trigger_info(self) -> TriggerInfo:
        return TriggerInfo(
            url="https://github.com/owner/repo/issues/42",
            title="Fix the bug",
            number=42,
            sender="testuser",
            repo="owner/repo",
            event_type="issue_comment",
            mention_text="@claude-bot please fix this",
        )

    @pytest.mark.asyncio
    async def test_spawn_new_session(
        self, backend: OpenClawBackend, trigger_info: TriggerInfo
    ) -> None:
        """Should spawn agent with new session ID."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_spawn:
            mock_spawn.return_value = MagicMock(pid=12345)
            session_id = await backend.spawn(trigger_info, None)

        assert session_id == "github-repo-issue-42"
        args = mock_spawn.call_args[0]
        assert args[0] == "openclaw"

    @pytest.mark.asyncio
    async def test_spawn_existing_session(
        self, backend: OpenClawBackend, trigger_info: TriggerInfo
    ) -> None:
        """Should use existing session ID when provided."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_spawn:
            mock_spawn.return_value = MagicMock(pid=12345)
            session_id = await backend.spawn(trigger_info, "existing-session")

        assert session_id == "existing-session"
