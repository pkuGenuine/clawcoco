"""Tests for agent module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clawcoco.agent import ClaudeSDKBackend, OpenClawBackend, TriggerInfo


class TestOpenClawBackend:
    """Tests for OpenClawBackend class."""

    @pytest.fixture
    def backend(self) -> OpenClawBackend:
        return OpenClawBackend()

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

    @pytest.fixture
    def repo_path(self, tmp_path: Path) -> Path:
        return tmp_path / "repos" / "owner" / "repo"

    @pytest.mark.asyncio
    async def test_spawn_new_session(
        self, backend: OpenClawBackend, trigger_info: TriggerInfo, repo_path: Path
    ) -> None:
        """Should spawn agent with new session ID."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_spawn:
            mock_spawn.return_value = MagicMock(pid=12345)
            session_id = await backend.spawn(trigger_info, None, repo_path)

        assert session_id == "github-repo-issue-42"
        args = mock_spawn.call_args[0]
        assert args[0] == "openclaw"

    @pytest.mark.asyncio
    async def test_spawn_existing_session(
        self, backend: OpenClawBackend, trigger_info: TriggerInfo, repo_path: Path
    ) -> None:
        """Should use existing session ID when provided."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_spawn:
            mock_spawn.return_value = MagicMock(pid=12345)
            session_id = await backend.spawn(trigger_info, "existing-session", repo_path)

        assert session_id == "existing-session"


class TestClaudeSDKBackend:
    """Tests for ClaudeSDKBackend class."""

    @pytest.fixture
    def backend(self) -> ClaudeSDKBackend:
        return ClaudeSDKBackend()

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

    @pytest.fixture
    def repo_path(self, tmp_path: Path) -> Path:
        return tmp_path / "repos" / "owner" / "repo"

    @pytest.mark.asyncio
    async def test_spawn_new_session(
        self, backend: ClaudeSDKBackend, trigger_info: TriggerInfo, repo_path: Path
    ) -> None:
        """Should spawn agent with new session ID."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_spawn:
            mock_spawn.return_value = MagicMock(pid=12345)
            session_id = await backend.spawn(trigger_info, None, repo_path)

        assert session_id == "claude-repo-42"
        args = mock_spawn.call_args[0]
        # Check that we're running Python with the module
        assert "-m" in args
        assert "run_claude_agent" in " ".join(args)
        # Check required args are passed
        assert "--repo" in args
        assert "--issue" in args
        # Check cwd is set
        assert mock_spawn.call_args.kwargs.get("cwd") == repo_path

    @pytest.mark.asyncio
    async def test_spawn_existing_session(
        self, backend: ClaudeSDKBackend, trigger_info: TriggerInfo, repo_path: Path
    ) -> None:
        """Should use existing session ID when provided."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_spawn:
            mock_spawn.return_value = MagicMock(pid=12345)
            session_id = await backend.spawn(trigger_info, "existing-session", repo_path)

        assert session_id == "existing-session"
