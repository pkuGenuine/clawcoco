"""Tests for webhook module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from clawcoco.agent import TriggerInfo
from clawcoco.webhook import app, should_trigger, verify_signature


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


class TestShouldTrigger:
    """Tests for webhook trigger logic."""

    def test_issue_comment_trigger(
        self, webhook_payload_issue_comment: dict, _setup_webhook_globals
    ) -> None:
        """Should trigger for valid issue comment."""
        should, result = should_trigger(webhook_payload_issue_comment, "issue_comment")
        assert should is True
        assert isinstance(result, TriggerInfo)
        assert result.number == 42

    def test_pr_comment_trigger(
        self, webhook_payload_pr_comment: dict, _setup_webhook_globals
    ) -> None:
        """Should trigger for PR comment (issue_comment with pull_request field)."""
        should, result = should_trigger(webhook_payload_pr_comment, "issue_comment")
        assert should is True
        assert isinstance(result, TriggerInfo)
        assert result.number == 1

    def test_reject_unauthorized(
        self, webhook_payload_unauthorized: dict, _setup_webhook_globals
    ) -> None:
        """Should not trigger for unauthorized user."""
        should, result = should_trigger(webhook_payload_unauthorized, "issue_comment")
        assert should is False
        assert isinstance(result, str)
        assert "not authorized" in result

    def test_pr_review_changes_requested(
        self, webhook_payload_pr_review_changes: dict, _setup_webhook_globals
    ) -> None:
        """Should trigger for PR review with changes_requested and mention."""
        should, result = should_trigger(
            webhook_payload_pr_review_changes, "pull_request_review"
        )
        assert should is True
        assert isinstance(result, TriggerInfo)
        assert result.number == 1


class TestWebhookEndpoint:
    """Integration tests for webhook endpoint."""

    @pytest.fixture
    def client(self, _setup_webhook_globals) -> TestClient:
        return TestClient(app)

    def test_webhook_valid_request(
        self,
        client: TestClient,
        test_config,
        webhook_payload_issue_comment: dict,
        compute_signature_fn,
        _setup_webhook_globals,
    ) -> None:
        """Should accept valid webhook and trigger agent."""
        payload_bytes = json.dumps(webhook_payload_issue_comment).encode()
        signature = compute_signature_fn(payload_bytes, test_config.webhook.secret)

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_spawn:
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
