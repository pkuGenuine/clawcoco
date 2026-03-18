"""Tests for repo cloning in git_utils module."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from clawcoco.git_utils import ensure_clone

# Use current project as test repo
REPO = "pkuGenuine/clawcoco"


class TestEnsureClone:
    """Tests for ensure_clone function."""

    @pytest.fixture
    def temp_data_dir(self, tmp_path: Path) -> Path:
        """Create a temporary data directory."""
        data_dir = tmp_path / "clawcoco"
        data_dir.mkdir()
        return data_dir

    def test_creates_clone(self, temp_data_dir: Path) -> None:
        """Should clone repo if not exists."""
        with patch("clawcoco.git_utils.ensure_fork_exists"):
            clone_path = ensure_clone(
                temp_data_dir, REPO, "claude-bot", "ghp_test_token"
            )

        org, repo_name = REPO.split("/")
        expected_path = temp_data_dir / "repos" / org / repo_name

        # Check clone exists and is a regular repo (not bare)
        assert clone_path == expected_path
        assert clone_path.exists()
        result = subprocess.run(
            ["git", "-C", str(clone_path), "rev-parse", "--is-bare-repository"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "false"

    def test_idempotent(self, temp_data_dir: Path) -> None:
        """Should be safe to call multiple times."""
        with patch("clawcoco.git_utils.ensure_fork_exists"):
            clone_path1 = ensure_clone(
                temp_data_dir, REPO, "claude-bot", "ghp_test_token"
            )
            clone_path2 = ensure_clone(
                temp_data_dir, REPO, "claude-bot", "ghp_test_token"
            )

        assert clone_path1 == clone_path2
        assert clone_path1.exists()
