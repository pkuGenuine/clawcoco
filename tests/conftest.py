"""Shared pytest fixtures for ClawCoco tests."""

import hashlib
import hmac
from pathlib import Path
from unittest.mock import patch

import pytest

from clawcoco.github_ip import GitHubIPManager
from clawcoco.session_store import SessionStore


@pytest.fixture
def temp_session_db(tmp_path: Path) -> Path:
    """Create a temporary database path for session storage."""
    return tmp_path / "sessions.db"


@pytest.fixture
def session_store(temp_session_db: Path):
    """Create a session store with temporary database."""
    return SessionStore(temp_session_db)


@pytest.fixture
def mock_ip_manager():
    """Create an IP manager with mocked HTTP client (no actual fetch)."""
    manager = GitHubIPManager()
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
def webhook_payload_pr_review_changes() -> dict:
    """Sample pull_request_review webhook payload with changes_requested."""
    return {
        "action": "submitted",
        "review": {
            "state": "changes_requested",
            "body": "@claude-bot please fix the error handling",
        },
        "pull_request": {
            "number": 1,
            "title": "Add new feature",
            "html_url": "https://github.com/testowner/testrepo/pull/1",
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
def _setup_webhook_globals(mock_ip_manager, temp_session_db):
    """Set up module-level globals for webhook tests."""
    patches = [
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
