"""Agent backend abstraction for handling GitHub issues."""

import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .config import config
from .git_utils import copy_skills, ensure_clone
from .session_store import SessionStore

logger = logging.getLogger(__name__)


@dataclass
class Trigger:
    """Minimal trigger info for spawning an agent."""

    repo: str
    number: int
    prompt: str


class AgentBackend(ABC):
    """Abstract base class for agent backends."""

    @abstractmethod
    async def spawn(
        self,
        trigger: Trigger,
        session_id: str | None,
        repo_path: Path,
    ) -> str:
        """
        Spawn agent to handle the issue.

        Args:
            trigger: Trigger info with repo, number, and prompt
            session_id: Existing session ID to resume, or None to start fresh
            repo_path: Path to the cloned repository

        Returns:
            The session ID (new or existing)
        """
        pass


class OpenClawBackend(AgentBackend):
    """OpenClaw CLI-based agent backend."""

    async def spawn(
        self,
        trigger: Trigger,
        session_id: str | None,
        repo_path: Path,
    ) -> str:
        """Spawn OpenClaw agent via CLI."""
        agent_id = config.openclaw.agent_id

        # Use existing session or generate a new one
        repo_name = trigger.repo.split("/")[1]
        new_session_id = session_id or f"github-{repo_name}-issue-{trigger.number}"

        # Build CLI command
        cmd = [
            "openclaw",
            "agent",
            "--agent",
            agent_id,
            "--session-id",
            new_session_id,
            "--message",
            trigger.prompt,
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


class ClaudeSDKBackend(AgentBackend):
    """Claude Agent SDK backend via subprocess script."""

    async def spawn(
        self,
        trigger: Trigger,
        session_id: str | None,
        repo_path: Path,
    ) -> str:
        """Spawn agent via script subprocess."""
        repo_name = trigger.repo.split("/")[1]
        new_session_id = session_id or f"claude-{repo_name}-{trigger.number}"

        cmd = [
            sys.executable,
            "-m",
            "clawcoco.scripts.run_claude_agent",
            "--prompt",
            trigger.prompt,
            "--session-id",
            new_session_id,
            "--repo",
            trigger.repo,
            "--issue",
            str(trigger.number),
        ]

        logger.info(f"Running: {' '.join(cmd[:4])}... (prompt truncated)")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=repo_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.info(f"Spawned process PID: {process.pid}")
        except Exception as e:
            logger.error(f"Failed to spawn agent: {e}")

        return new_session_id


def get_backend() -> AgentBackend:
    """Get the configured agent backend."""
    if config.backend_type == "claude_sdk":
        return ClaudeSDKBackend()
    return OpenClawBackend()


async def run_agent(trigger: Trigger, session_store: SessionStore) -> None:
    """Run agent in background. Called by handlers."""
    repo_name = trigger.repo.split("/")[1]
    issue_number = trigger.number

    # Setup repo before spawning agent
    repo_path = await ensure_clone(
        config.data_dir,
        trigger.repo,
        config.github.assistant_account,
        config.github.assistant_account_token,
    )
    await copy_skills(config.data_dir, repo_path)

    # Get existing session or None
    existing_session_id = session_store.get_session_id(repo_name, issue_number)

    # Spawn agent
    backend = get_backend()
    new_session_id = await backend.spawn(trigger, existing_session_id, repo_path)

    # Store session ID for future webhooks
    session_store.set_session_id(repo_name, issue_number, new_session_id)
    logger.info(f"Session saved: {repo_name}/{issue_number} -> {new_session_id}")
