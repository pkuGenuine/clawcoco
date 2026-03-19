"""Tests for webhook module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from clawcoco.config import config
from clawcoco.handlers import (
    handle_issue_comment,
    handle_issues,
    handle_pull_request,
    handle_pull_request_review,
)
from clawcoco.webhook import app, verify_signature


class TestVerifySignature:
    """Tests for signature verification."""

    def test_valid_signature(self, compute_signature_fn) -> None:
        """Should verify valid HMAC signature."""
        payload = b'{"test": "data"}'
        assert (
            verify_signature(payload, compute_signature_fn(payload, "secret"), "secret")
            is True
        )

    def test_invalid_signature(self) -> None:
        """Should reject invalid signature."""
        assert verify_signature(b"{}", "sha256=invalid", "secret") is False


class TestHandlers:
    """Tests for event handlers."""

    def test_handle_issue_comment(
        self, webhook_payload_issue_comment: dict, session_store
    ) -> None:
        """Should return triggered for valid issue comment."""
        with (
            patch("clawcoco.handlers.issue_comment.run_agent", new_callable=AsyncMock),
            patch("clawcoco.agent.ensure_clone", new_callable=AsyncMock),
            patch("clawcoco.agent.copy_skills", new_callable=AsyncMock),
        ):
            import asyncio

            result = asyncio.run(handle_issue_comment(webhook_payload_issue_comment, session_store))
        assert result["status"] == "triggered"
        assert result["issue"] == 42

    def test_handle_pr_comment(
        self, webhook_payload_pr_comment: dict, session_store
    ) -> None:
        """Should return triggered for PR comment."""
        with (
            patch("clawcoco.handlers.issue_comment.run_agent", new_callable=AsyncMock),
            patch("clawcoco.agent.ensure_clone", new_callable=AsyncMock),
            patch("clawcoco.agent.copy_skills", new_callable=AsyncMock),
        ):
            import asyncio

            result = asyncio.run(handle_issue_comment(webhook_payload_pr_comment, session_store))
        assert result["status"] == "triggered"
        assert result["issue"] == 1

    def test_handle_issues(
        self, webhook_payload_issue_opened: dict, session_store
    ) -> None:
        """Should return triggered for new issue."""
        with (
            patch("clawcoco.handlers.issues.run_agent", new_callable=AsyncMock),
            patch("clawcoco.agent.ensure_clone", new_callable=AsyncMock),
            patch("clawcoco.agent.copy_skills", new_callable=AsyncMock),
        ):
            import asyncio

            result = asyncio.run(handle_issues(webhook_payload_issue_opened, session_store))
        assert result["status"] == "triggered"
        assert result["issue"] == 5

    def test_handle_pr_review(
        self, webhook_payload_pr_review_changes: dict, session_store
    ) -> None:
        """Should return triggered for PR review with changes_requested."""
        with (
            patch(
                "clawcoco.handlers.pull_request_review.run_agent", new_callable=AsyncMock
            ),
            patch("clawcoco.agent.ensure_clone", new_callable=AsyncMock),
            patch("clawcoco.agent.copy_skills", new_callable=AsyncMock),
        ):
            import asyncio

            result = asyncio.run(handle_pull_request_review(webhook_payload_pr_review_changes, session_store))
        assert result["status"] == "triggered"
        assert result["issue"] == 1


class TestPullRequestTracking:
    """Tests for PR tracking handler."""

    def test_pr_tracking_matching_branch(self, session_store) -> None:
        """Should track PR with matching branch pattern."""
        # Create a session record first (simulating agent was triggered)
        session_store.set_session_id("testrepo", 42, "test-session-id")

        payload = {
            "action": "opened",
            "pull_request": {
                "number": 123,
                "head": {"ref": "agent/42"},
            },
            "repository": {"full_name": "testowner/testrepo"},
        }
        import asyncio

        result = asyncio.run(handle_pull_request(payload, session_store))
        assert result["status"] == "pr_tracked"
        assert result["issue"] == 42
        assert result["pr"] == 123

        # Verify session store was updated
        assert session_store.get_pr_number("testrepo", 42) == 123

    def test_pr_tracking_non_matching_branch(self, session_store) -> None:
        """Should ignore PR with non-matching branch pattern."""
        payload = {
            "action": "opened",
            "pull_request": {
                "number": 123,
                "head": {"ref": "feature/some-feature"},
            },
            "repository": {"full_name": "testowner/testrepo"},
        }
        import asyncio

        result = asyncio.run(handle_pull_request(payload, session_store))
        assert result["status"] == "ignored"


class TestWebhookEndpoint:
    """Integration tests for webhook endpoint."""

    @pytest.fixture
    def client(self, _setup_webhook_globals) -> TestClient:
        return TestClient(app)

    def test_webhook_valid_request(
        self,
        client: TestClient,
        webhook_payload_issue_comment: dict,
        compute_signature_fn,
        _setup_webhook_globals,
    ) -> None:
        """Should accept valid webhook and trigger agent."""
        payload_bytes = json.dumps(webhook_payload_issue_comment).encode()
        signature = compute_signature_fn(payload_bytes, config.webhook.secret)

        with (
            patch(
                "clawcoco.agent.ensure_clone", new_callable=AsyncMock
            ) as mock_clone,
            patch("clawcoco.agent.copy_skills", new_callable=AsyncMock),
            patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock
            ) as mock_spawn,
        ):
            mock_clone.return_value = "/tmp/test/repo"
            mock_spawn.return_value = MagicMock(pid=12345)
            response = client.post(
                "/webhook",
                content=payload_bytes,
                headers={
                    "content-type": "application/json",
                    "x-github-event": "issue_comment",
                    "x-hub-signature-256": signature,
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "triggered"

    def test_webhook_invalid_signature(
        self,
        client: TestClient,
        webhook_payload_issue_comment: dict,
        _setup_webhook_globals,
    ) -> None:
        """Should reject webhook with invalid signature."""
        response = client.post(
            "/webhook",
            json=webhook_payload_issue_comment,
            headers={
                "x-github-event": "issue_comment",
                "x-hub-signature-256": "sha256=invalid",
            },
        )
        assert response.status_code == 401


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, _setup_webhook_globals) -> None:
        """Should return ok status."""
        response = TestClient(app).get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"