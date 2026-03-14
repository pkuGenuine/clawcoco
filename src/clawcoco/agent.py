"""Agent backend abstraction for handling GitHub issues."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)


class TriggerInfo:
    """Info about a webhook event that triggers the agent."""

    def __init__(
        self,
        url: str,
        title: str,
        number: int,
        sender: str,
        repo: str,
        event_type: str,
        mention_text: str,
    ) -> None:
        self.url = url
        self.title = title
        self.number = number
        self.sender = sender
        self.repo = repo
        self.event_type = event_type
        self.mention_text = mention_text


class AgentBackend(ABC):
    """Abstract base class for agent backends."""

    @abstractmethod
    async def spawn(self, trigger_info: TriggerInfo, session_id: str | None) -> str:
        """
        Spawn agent to handle the issue.

        Args:
            trigger_info: Information about the webhook trigger
            session_id: Existing session ID to resume, or None to start fresh

        Returns:
            The session ID (new or existing)
        """
        pass


class OpenClawBackend(AgentBackend):
    """OpenClaw CLI-based agent backend."""

    def __init__(self, config: "Config") -> None:
        self.config = config

    async def spawn(self, trigger_info: TriggerInfo, session_id: str | None) -> str:
        """Spawn OpenClaw agent via CLI."""
        agent_id = self.config.openclaw.agent_id

        # Use existing session or generate a new one
        # (Pretend session forking works for now)
        repo_name = trigger_info.repo.split("/")[1]
        new_session_id = session_id or f"github-{repo_name}-issue-{trigger_info.number}"

        # Build task prompt
        task = f"""You have been summoned via GitHub mention.

**Issue/PR:** {trigger_info.title}
**Repository:** {trigger_info.repo}
**From:** @{trigger_info.sender}
**URL:** {trigger_info.url}

Please:
1. Read the issue/PR at the URL above using `gh issue view` or `gh pr view`
2. Understand what is being asked
3. Respond appropriately (answer questions, implement changes, etc.)
4. Post your response as a comment using `gh issue comment` or `gh pr comment`

Use the `gh` CLI which is already authenticated as `{self.config.github.assistant_account}`.
"""

        # Build CLI command
        cmd = [
            "openclaw",
            "agent",
            "--agent",
            agent_id,
            "--session-id",
            new_session_id,
            "--message",
            task,
            "--timeout",
            "0",  # No timeout
        ]

        logger.info(f"Running: {' '.join(cmd[:6])}... (message truncated)")

        try:
            # Run in background, discard output to avoid pipe buffer deadlock
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.info(f"Spawned process PID: {process.pid}")
        except Exception as e:
            logger.error(f"Failed to spawn agent: {e}")

        return new_session_id


def get_backend(config: "Config") -> AgentBackend:
    """Get the configured agent backend."""
    return OpenClawBackend(config)
