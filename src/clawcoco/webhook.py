#!/usr/bin/env python3
"""
GitHub Webhook Receiver for ClawCoco Agent

Receives GitHub webhooks, filters for @mentions from authorized user,
and spawns agent sessions to handle each issue/PR.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, cast

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from .agent import TriggerInfo, get_backend
from .config import config
from .git_utils import copy_skills, ensure_clone
from .github_ip import GitHubIPManager
from .session_store import SessionStore

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Global instances (set during startup)
ip_manager: GitHubIPManager
session_store: SessionStore


def verify_github_ip(client_ip: str) -> bool:
    """Check if request comes from GitHub's IP range."""
    if not config.webhook.github_ips_only:
        logger.debug("IP verification disabled, allowing all IPs")
        return True

    try:
        client_addr = ipaddress.ip_address(client_ip)
        for cidr in ip_manager.get_ranges():
            if client_addr in ipaddress.ip_network(cidr):
                logger.debug(f"IP {client_ip} matches GitHub range {cidr}")
                return True
    except ValueError as e:
        logger.warning(f"Invalid IP address '{client_ip}': {e}")
        return False

    logger.warning(f"IP {client_ip} not in GitHub ranges")
    return False


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature using HMAC-SHA256."""
    if not signature or not signature.startswith("sha256="):
        logger.warning("Invalid signature format")
        return False

    expected = signature[7:]  # Remove "sha256=" prefix
    computed = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    return hmac.compare_digest(computed, expected)


def should_trigger(
    payload: dict[str, Any], event_type: str
) -> tuple[bool, str | TriggerInfo]:
    """
    Determine if this webhook should trigger the agent.
    Returns (should_trigger, info_dict_or_reason_string).
    """
    github_config = config.github

    # Check sender is authorized
    sender = payload.get("sender", {}).get("login", "")
    if sender not in github_config.authorized_users:
        return False, f"Sender '{sender}' not authorized"

    # Check for @mention based on event type
    action = payload.get("action", "")
    mention_pattern = f"@{github_config.assistant_account}"

    if event_type == "issue_comment":
        # Comment on an issue/PR - only trigger on "created" action
        if action != "created":
            return False, f"Action '{action}' ignored for issue_comment (only 'created' triggers)"
        comment_body = payload.get("comment", {}).get("body", "") or ""
        if mention_pattern not in comment_body:
            return False, f"No {mention_pattern} mention found"
        issue_url = payload.get("issue", {}).get("html_url", "")
        issue_title = payload.get("issue", {}).get("title", "")
        issue_number = payload.get("issue", {}).get("number")
        mention_text = comment_body

    elif event_type == "issues":
        # New issue created - only trigger on "opened" action
        if action != "opened":
            return False, f"Action '{action}' ignored for issues (only 'opened' triggers)"
        issue_body = payload.get("issue", {}).get("body", "") or ""
        if mention_pattern not in issue_body:
            return False, f"No {mention_pattern} mention found"
        issue_url = payload.get("issue", {}).get("html_url", "")
        issue_title = payload.get("issue", {}).get("title", "")
        issue_number = payload.get("issue", {}).get("number")
        mention_text = issue_body

    elif event_type == "pull_request_review":
        # PR review submitted - only trigger on "submitted" with "changes_requested" state
        if action != "submitted":
            return False, f"Action '{action}' ignored for pull_request_review (only 'submitted' triggers)"
        review_state = payload.get("review", {}).get("state", "")
        if review_state != "changes_requested":
            return False, f"Review state '{review_state}' ignored (only 'changes_requested' triggers)"
        review_body = payload.get("review", {}).get("body", "") or ""
        if mention_pattern not in review_body:
            return False, f"No {mention_pattern} mention found in review body"
        pr = payload.get("pull_request", {})
        issue_url = pr.get("html_url", "")
        issue_title = pr.get("title", "")
        issue_number = pr.get("number")
        mention_text = review_body

    else:
        return False, f"Event type '{event_type}' not supported"

    # Ensure we have required fields (should always be present from GitHub)
    if not issue_url or not issue_title or issue_number is None:
        return False, "Missing required fields in payload"

    # Get repo name
    repo_full_name = payload.get("repository", {}).get("full_name", "")

    logger.info(f"Will trigger! Issue #{issue_number}: {issue_title}")
    return True, TriggerInfo(
        url=issue_url,
        title=issue_title,
        number=issue_number,
        sender=sender,
        repo=repo_full_name,
        event_type=event_type,
        mention_text=mention_text[:500],
    )


async def run_agent(trigger_info: TriggerInfo) -> None:
    """Run agent in background. Called as asyncio task."""
    repo_name = trigger_info.repo.split("/")[1]
    issue_number = trigger_info.number

    # Setup repo before spawning agent
    repo_path = await ensure_clone(
        config.data_dir,
        trigger_info.repo,
        config.github.assistant_account,
        config.github.assistant_account_token,
    )
    await copy_skills(config.data_dir, repo_path)

    # Get existing session or None
    existing_session_id = session_store.get_session_id(repo_name, issue_number)

    # Spawn agent
    backend = get_backend()
    new_session_id = await backend.spawn(
        trigger_info, existing_session_id, repo_path
    )

    # Store session ID for future webhooks
    session_store.set_session_id(repo_name, issue_number, new_session_id)
    logger.info(f"Session saved: {repo_name}/{issue_number} -> {new_session_id}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    global ip_manager, session_store

    # Initialize session store under data_dir
    session_db_path = config.data_dir / "db" / "sessions.db"
    session_db_path.parent.mkdir(parents=True, exist_ok=True)
    session_store = SessionStore(session_db_path)

    # Startup: initialize IP manager with HTTP client
    ip_manager = GitHubIPManager()
    async with httpx.AsyncClient() as http_client:
        await ip_manager.initialize(http_client)

        if ip_manager.last_fetch:
            logger.info(
                f"GitHub IP ranges initialized (last fetch: {ip_manager.last_fetch.isoformat()})"
            )
        else:
            logger.warning("Using fallback GitHub IP ranges (fetch failed)")

        yield  # Application runs here

    # Shutdown: cleanup
    await ip_manager.shutdown()
    logger.info("GitHub IP manager shut down")


app = FastAPI(title="ClawCoco GitHub Webhook", lifespan=lifespan)


@app.post("/webhook")
async def handle_webhook(request: Request):
    """Handle incoming GitHub webhook."""
    logger.info("=" * 60)
    logger.info("Received webhook request")

    # Get client IP
    client_ip = request.client.host if request.client else "unknown"
    logger.info(f"Client IP: {client_ip}")

    # Get headers
    signature = request.headers.get("x-hub-signature-256", "")
    event_type = request.headers.get("x-github-event", "")
    delivery_id = request.headers.get("x-github-delivery", "")

    logger.info(f"Event type: {event_type}, Delivery ID: {delivery_id}")

    # Get raw body for signature verification
    payload_bytes = await request.body()
    logger.info(f"Payload size: {len(payload_bytes)} bytes")

    if len(payload_bytes) == 0:
        logger.error("Empty payload received")
        raise HTTPException(status_code=400, detail="Empty payload")

    # Parse payload based on content type
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        try:
            form_data = urllib.parse.parse_qs(payload_bytes.decode("utf-8"))
            if "payload" in form_data:
                payload = json.loads(form_data["payload"][0])
            else:
                logger.error("No 'payload' field in form data")
                raise HTTPException(status_code=400, detail="Missing payload field")
        except Exception as e:
            logger.error(f"Failed to parse form data: {e}")
            raise HTTPException(status_code=400, detail="Invalid form data")
    else:
        try:
            payload = json.loads(payload_bytes)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON")

    # Verify IP comes from GitHub
    if not verify_github_ip(client_ip):
        logger.warning(f"Rejected request from non-GitHub IP: {client_ip}")
        raise HTTPException(status_code=403, detail="IP not allowed")

    # Verify signature
    if not verify_signature(payload_bytes, signature, config.webhook.secret):
        logger.warning(f"Invalid signature for delivery {delivery_id}")
        raise HTTPException(status_code=401, detail="Invalid signature")

    logger.info("Signature verified OK")

    # Check if we should trigger
    should, result = should_trigger(payload, event_type)

    if should:
        trigger_info = cast(TriggerInfo, result)
        logger.info(f"Triggering agent spawn for: {trigger_info}")

        # Spawn agent as background task
        asyncio.create_task(run_agent(trigger_info))

        return {"status": "triggered", "issue": trigger_info.number}
    else:
        logger.info(f"Not triggering: {result}")
        return {"status": "ignored", "reason": result}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/")
async def root():
    """Root endpoint with basic info."""
    return {
        "service": "ClawCoco GitHub Webhook",
        "authorized_users": config.github.authorized_users,
        "assistant": config.github.assistant_account,
        "github_ip_ranges": {
            "count": len(ip_manager.get_ranges()),
            "last_fetch": (
                ip_manager.last_fetch.isoformat() if ip_manager.last_fetch else None
            ),
        },
    }


def main():
    """Run the webhook server."""
    # Set log level
    if config.webhook.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    logger.info(f"Starting webhook server on port {config.webhook.port}")
    logger.info(f"Debug mode: {config.webhook.debug}")
    logger.info(f"Authorized users: {config.github.authorized_users}")

    uvicorn.run(app, host="0.0.0.0", port=config.webhook.port)


if __name__ == "__main__":
    main()