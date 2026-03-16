"""Tests for repo cloning in run_claude_agent script."""

import subprocess
from pathlib import Path

import pytest

from clawcoco.scripts.run_claude_agent import ensure_clone

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
        clone_path = ensure_clone(temp_data_dir, REPO)

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
        clone_path1 = ensure_clone(temp_data_dir, REPO)
        clone_path2 = ensure_clone(temp_data_dir, REPO)

        assert clone_path1 == clone_path2
        assert clone_path1.exists()
