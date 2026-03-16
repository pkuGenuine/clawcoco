#!/usr/bin/env python3
"""Claude Agent SDK runner script."""

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

logger = logging.getLogger(__name__)


def ensure_clone(data_dir: Path, repo: str) -> Path:
    """
    Ensure repo is cloned and return its path.

    Args:
        data_dir: Base data directory (e.g., /var/lib/clawcoco)
        repo: Full repo name (e.g., "pkuGenuine/claw-infra-kit")

    Returns:
        Path to the cloned repo directory
    """
    org, repo_name = repo.split("/")
    repos_dir = data_dir / "repos" / org
    clone_path = repos_dir / repo_name

    repos_dir.mkdir(parents=True, exist_ok=True)

    if not clone_path.exists():
        clone_url = f"https://github.com/{repo}.git"
        logger.info(f"Cloning repo: {clone_url}")
        subprocess.run(
            ["git", "clone", clone_url, str(clone_path)],
            check=True,
            capture_output=True,
        )
        logger.info(f"Repo cloned to: {clone_path}")
    else:
        # Fetch latest
        logger.info(f"Fetching latest from remote")
        subprocess.run(
            ["git", "-C", str(clone_path), "fetch"],
            check=False,
            capture_output=True,
        )

    # Copy skills from data_dir/skills to clone_path/.claude/skills
    _copy_skills(data_dir, clone_path)

    return clone_path


def _copy_skills(data_dir: Path, clone_path: Path) -> None:
    """Copy skills from data_dir/skills to the cloned repo."""
    src_skills_dir = data_dir / "skills"
    if not src_skills_dir.exists():
        logger.warning(f"Skills directory not found: {src_skills_dir}")
        return

    dest_skills_dir = clone_path / ".claude" / "skills"
    if dest_skills_dir.exists():
        logger.info(f"Skills already exist in repo: {dest_skills_dir}")
        return

    dest_skills_dir.mkdir(parents=True, exist_ok=True)

    for skill in src_skills_dir.iterdir():
        if skill.is_dir():
            dest_skill = dest_skills_dir / skill.name
            if not dest_skill.exists():
                shutil.copytree(skill, dest_skill)
                logger.info(f"Copied skill: {skill.name}")

    logger.info(f"Skills copied to: {dest_skills_dir}")


async def run_agent(
    prompt: str, session_id: str | None, model: str, tools: list[str]
) -> str:
    """Run agent and return new session ID."""
    options = ClaudeAgentOptions(
        model=model,
        allowed_tools=tools,
        resume=session_id,
        setting_sources=["user", "project"]
    )

    result_session_id = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result_session_id = message.session_id

    return result_session_id


def main():
    parser = argparse.ArgumentParser(description="Run Claude Agent")
    parser.add_argument("--prompt", required=True, help="Task prompt")
    parser.add_argument("--session-id", help="Session ID to resume")
    parser.add_argument(
        "--model", default="claude-sonnet-4-5-20250929", help="Model to use"
    )
    parser.add_argument(
        "--tools",
        default="Skill,Read,Edit,Write,Bash,Glob,Grep",
        help="Comma-separated tools",
    )
    parser.add_argument(
        "--data-dir", required=True, help="Base data directory for repos"
    )
    parser.add_argument(
        "--repo", required=True, help="Full repo name (org/repo)"
    )
    parser.add_argument(
        "--issue", required=True, type=int, help="Issue/PR number"
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Ensure repo is cloned
    data_dir = Path(args.data_dir)
    repo_path = ensure_clone(data_dir, args.repo)

    # Change to repo directory
    os.chdir(repo_path)
    logger.info(f"Working directory: {repo_path}")

    # Set environment variables for agent context
    os.environ["GITHUB_REPO"] = args.repo
    os.environ["GITHUB_ISSUE"] = str(args.issue)

    # Run agent
    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    session_id = asyncio.run(
        run_agent(args.prompt, args.session_id, args.model, tools)
    )

    # Output session ID to stdout for caller to capture
    print(session_id)


if __name__ == "__main__":
    main()