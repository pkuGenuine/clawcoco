"""Git utilities for repo cloning and management."""

import asyncio
import logging
import shutil
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


async def ensure_fork_exists(
    repo: str, assistant_account: str, token: str
) -> None:
    """
    Ensure the agent's fork exists, creating it if necessary.

    Args:
        repo: Full repo name (e.g., "pkuGenuine/clawcoco")
        assistant_account: Agent's GitHub username
        token: GitHub token with repo scope
    """
    org, repo_name = repo.split("/")
    fork_full_name = f"{assistant_account}/{repo_name}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    async with httpx.AsyncClient() as client:
        check_url = f"https://api.github.com/repos/{fork_full_name}"
        response = await client.get(check_url, headers=headers)

        if response.status_code == 200:
            logger.info(f"Fork already exists: {fork_full_name}")
            return

        if response.status_code == 404:
            logger.info(f"Creating fork: {fork_full_name}")
            create_url = f"https://api.github.com/repos/{repo}/forks"
            create_response = await client.post(create_url, headers=headers)

            if create_response.status_code in (200, 202):
                logger.info(f"Fork created: {fork_full_name}")
            else:
                raise RuntimeError(
                    f"Failed to create fork: {create_response.status_code} - {create_response.text}"
                )
        else:
            raise RuntimeError(
                f"Failed to check fork existence: {response.status_code} - {response.text}"
            )


async def _run_git(args: list[str]) -> str:
    """Run a git command asynchronously."""
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"Git command failed: {stderr.decode()}")

    return stdout.decode()


async def ensure_clone(
    data_dir: Path,
    repo: str,
    assistant_account: str,
    token: str,
) -> Path:
    """
    Ensure repo is cloned and fork remote is configured.

    Args:
        data_dir: Base data directory (e.g., /var/lib/clawcoco)
        repo: Full repo name (e.g., "pkuGenuine/claw-infra-kit")
        assistant_account: Agent's GitHub username
        token: GitHub token with repo scope

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
        await _run_git(["clone", clone_url, str(clone_path)])
        logger.info(f"Repo cloned to: {clone_path}")
    else:
        logger.info(f"Fetching latest from remote")
        await _run_git(["-C", str(clone_path), "fetch"])

    # Ensure fork exists
    await ensure_fork_exists(repo, assistant_account, token)

    # Add fork remote if not present
    result = await _run_git(["-C", str(clone_path), "remote"])
    remotes = result.strip().split("\n")

    if "fork" not in remotes:
        fork_url = f"https://{token}@github.com/{assistant_account}/{repo_name}.git"
        await _run_git(["-C", str(clone_path), "remote", "add", "fork", fork_url])
        logger.info(f"Added fork remote: {assistant_account}/{repo_name}")

    return clone_path


async def copy_skills(data_dir: Path, clone_path: Path) -> None:
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
                # Run shutil.copytree in executor to avoid blocking
                await asyncio.to_thread(shutil.copytree, skill, dest_skill)
                logger.info(f"Copied skill: {skill.name}")

    logger.info(f"Skills copied to: {dest_skills_dir}")