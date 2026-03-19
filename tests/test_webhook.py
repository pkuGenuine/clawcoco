"""Tests for webhook module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from clawcoco.agent import Trigger
from clawcoco.config import config
from clawcoco.webhook import (
    app,
    handle_issue_comment,
    handle_issues,
    handle_pr_review,
    verify_signature,
)


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

    def test_handle_issue_comment(self, webhook_payload_issue_comment: dict) -> None:
        """Should return Trigger for valid issue comment."""
        result = handle_issue_comment(webhook_payload_issue_comment, "claude-bot")
        assert isinstance(result, Trigger)
        assert result.number == 42
        assert result.repo == "testowner/testrepo"
        assert "Test Issue Title" in result.prompt

    def test_handle_pr_comment(self, webhook_payload_pr_comment: dict) -> None:
        """Should return Trigger for PR comment."""
        result = handle_issue_comment(webhook_payload_pr_comment, "claude-bot")
        assert isinstance(result, Trigger)
        assert result.number == 1

    def test_handle_issues(self, webhook_payload_issue_opened: dict) -> None:
        """Should return Trigger for new issue."""
        result = handle_issues(webhook_payload_issue_opened, "claude-bot")
        assert isinstance(result, Trigger)
        assert result.number == 5
        assert "New Bug Report" in result.prompt

    def test_handle_pr_review(self, webhook_payload_pr_review_changes: dict) -> None:
        """Should return Trigger for PR review with changes_requested."""
        result = handle_pr_review(webhook_payload_pr_review_changes, "claude-bot")
        assert isinstance(result, Trigger)
        assert result.number == 1


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
                "clawcoco.webhook.ensure_clone", new_callable=AsyncMock
            ) as mock_clone,
            patch("clawcoco.webhook.copy_skills", new_callable=AsyncMock),
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
