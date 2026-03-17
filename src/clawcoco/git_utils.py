"""Git utilities for repo cloning and management."""

import logging
import shutil
import subprocess
from pathlib import Path

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

    return clone_path


def copy_skills(data_dir: Path, clone_path: Path) -> None:
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
