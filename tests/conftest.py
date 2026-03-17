"""Shared pytest fixtures for ClawCoco tests."""

import hashlib
import hmac
from pathlib import Path
from unittest.mock import patch

import pytest

from clawcoco.config import (
    ClaudeSDKConfig,
    Config,
    GitHubConfig,
    OpenClawConfig,
    WebhookConfig,
)
from clawcoco.github_ip import GitHubIPManager
from clawcoco.session_store import SessionStore


@pytest.fixture
def test_config() -> Config:
    """Create a test configuration."""
    return Config(
        webhook=WebhookConfig(
            secret="test-secret-key",
            port=8080,
            debug=True,
            github_ips_only=False,  # Disable IP check for tests
        ),
        github=GitHubConfig(
            authorized_users=["testuser"],
            assistant_account="claude-bot",
        ),
        data_dir=Path("/tmp/clawcoco-test"),
        openclaw=OpenClawConfig(
            agent_id="coder",
        ),
        claude_sdk=ClaudeSDKConfig(
            model="claude-sonnet-4-5-20250929",
            allowed_tools=["Read", "Edit", "Write", "Bash", "Glob", "Grep"],
        ),
        backend_type="openclaw",
    )


@pytest.fixture
def temp_session_db(tmp_path: Path) -> Path:
    """Create a temporary database path for session storage."""
    return tmp_path / "sessions.db"


@pytest.fixture
def session_store(temp_session_db: Path) -> SessionStore:
    """Create a session store with temporary database."""
    return SessionStore(temp_session_db)


@pytest.fixture
def mock_ip_manager() -> GitHubIPManager:
    """Create an IP manager with mocked HTTP client (no actual fetch)."""
    manager = GitHubIPManager()
    # Skip initialization, just use defaults
    return manager


@pytest.fixture
def webhook_payload_issue_comment() -> dict:
    """Sample issue_comment webhook payload for regular issue."""
    return {
        "action": "created",
        "issue": {
            "number": 42,
            "title": "Test Issue Title",
            "html_url": "https://github.com/testowner/testrepo/issues/42",
        },
        "comment": {
            "body": "@claude-bot please help fix this bug",
        },
        "repository": {
            "full_name": "testowner/testrepo",
        },
        "sender": {
            "login": "testuser",
        },
    }


@pytest.fixture
def webhook_payload_pr_comment() -> dict:
    """Sample issue_comment webhook payload for PR (has pull_request field)."""
    return {
        "action": "created",
        "issue": {
            "number": 1,
            "title": "Restructure as multi-package monorepo",
            "html_url": "https://github.com/testowner/testrepo/pull/1",
            "pull_request": {
                "url": "https://api.github.com/repos/testowner/testrepo/pulls/1",
            },
        },
        "comment": {
            "body": "@claude-bot please review this PR",
        },
        "repository": {
            "full_name": "testowner/testrepo",
        },
        "sender": {
            "login": "testuser",
        },
    }


@pytest.fixture
def webhook_payload_issue_opened() -> dict:
    """Sample issues webhook payload for new issue."""
    return {
        "action": "opened",
        "issue": {
            "number": 5,
            "title": "New Bug Report",
            "html_url": "https://github.com/testowner/testrepo/issues/5",
            "body": "@claude-bot there's a bug in the login flow",
        },
        "repository": {
            "full_name": "testowner/testrepo",
        },
        "sender": {
            "login": "testuser",
        },
    }


@pytest.fixture
def webhook_payload_unauthorized() -> dict:
    """Payload from unauthorized user."""
    return {
        "action": "created",
        "issue": {
            "number": 42,
            "title": "Test Issue",
            "html_url": "https://github.com/testowner/testrepo/issues/42",
        },
        "comment": {
            "body": "@claude-bot do something",
        },
        "repository": {
            "full_name": "testowner/testrepo",
        },
        "sender": {
            "login": "randomuser",  # Not authorized
        },
    }


def compute_signature(payload: bytes, secret: str) -> str:
    """Compute GitHub webhook signature."""
    computed = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={computed}"


@pytest.fixture
def compute_signature_fn():
    """Provide signature computation function."""
    return compute_signature


@pytest.fixture
def _setup_webhook_globals(test_config: Config, mock_ip_manager, temp_session_db):
    """Set up module-level globals for webhook tests."""
    patches = [
        patch("clawcoco.webhook.config", test_config, create=True),
        patch("clawcoco.webhook.ip_manager", mock_ip_manager, create=True),
        patch(
            "clawcoco.webhook.session_store", SessionStore(temp_session_db), create=True
        ),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()
