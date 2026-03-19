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
from typing import Any, Callable

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from .agent import Trigger, get_backend
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


def handle_issue_comment(
    payload: dict[str, Any], assistant_account: str
) -> Trigger | str:
    """Handle issue_comment event. Returns Trigger or skip reason."""
    if payload.get("action") != "created":
        return "Action ignored (only 'created' triggers)"

    comment = payload.get("comment", {})
    comment_body = comment.get("body", "") or ""
    mention = f"@{assistant_account}"
    if mention not in comment_body:
        return f"No {mention} mention found"

    issue = payload.get("issue", {})
    issue_number = issue.get("number")
    issue_title = issue.get("title", "")
    issue_url = issue.get("html_url", "")

    if not issue_number or not issue_url:
        return "Missing required fields in payload"

    repo = payload.get("repository", {}).get("full_name", "")
    sender = payload.get("sender", {}).get("login", "")

    prompt = f"""You have been mentioned in a comment on an issue/PR.

**Issue/PR:** {issue_title}
**Repository:** {repo}
**From:** @{sender}
**URL:** {issue_url}

Please:
1. Read the issue/PR using `gh issue view` or `gh pr view`
2. Understand what is being asked
3. Respond appropriately (answer questions, implement changes, etc.)
4. Post your response as a comment using `gh issue comment` or `gh pr comment`

Use the `gh` CLI which is already authenticated as `{assistant_account}`.
"""
    logger.info(f"Triggering on issue_comment: #{issue_number}")
    return Trigger(repo=repo, number=issue_number, prompt=prompt)


def handle_issues(payload: dict[str, Any], assistant_account: str) -> Trigger | str:
    """Handle issues event. Returns Trigger or skip reason."""
    if payload.get("action") != "opened":
        return "Action ignored (only 'opened' triggers)"

    issue = payload.get("issue", {})
    issue_body = issue.get("body", "") or ""
    mention = f"@{assistant_account}"
    if mention not in issue_body:
        return f"No {mention} mention found"

    issue_number = issue.get("number")
    issue_title = issue.get("title", "")
    issue_url = issue.get("html_url", "")

    if not issue_number or not issue_url:
        return "Missing required fields in payload"

    repo = payload.get("repository", {}).get("full_name", "")
    sender = payload.get("sender", {}).get("login", "")

    prompt = f"""A new issue was opened mentioning you.

**Issue:** {issue_title}
**Repository:** {repo}
**From:** @{sender}
**URL:** {issue_url}

Please:
1. Read the issue using `gh issue view {issue_number}`
2. Understand what is being asked
3. Respond appropriately (answer questions, implement changes, etc.)
4. Post your response as a comment using `gh issue comment {issue_number}`

Use the `gh` CLI which is already authenticated as `{assistant_account}`.
"""
    logger.info(f"Triggering on new issue: #{issue_number}")
    return Trigger(repo=repo, number=issue_number, prompt=prompt)


def handle_pr_review(payload: dict[str, Any], assistant_account: str) -> Trigger | str:
    """Handle pull_request_review event. Returns Trigger or skip reason."""
    if payload.get("action") != "submitted":
        return "Action ignored (only 'submitted' triggers)"

    review = payload.get("review", {})
    if review.get("state") != "changes_requested":
        return "Review state ignored (only 'changes_requested' triggers)"

    review_body = review.get("body", "") or ""
    mention = f"@{assistant_account}"
    if mention not in review_body:
        return f"No {mention} mention found in review body"

    pr = payload.get("pull_request", {})
    pr_number = pr.get("number")
    pr_title = pr.get("title", "")
    pr_url = pr.get("html_url", "")

    if not pr_number or not pr_url:
        return "Missing required fields in payload"

    repo = payload.get("repository", {}).get("full_name", "")
    sender = payload.get("sender", {}).get("login", "")

    prompt = f"""Changes were requested on a PR mentioning you.

**PR:** {pr_title}
**Repository:** {repo}
**From:** @{sender}
**URL:** {pr_url}

Please:
1. Read the PR and review feedback using `gh pr view {pr_number}`
2. Understand what changes are requested
3. Make the necessary changes in the code
4. Push your changes and respond to the review

Use the `gh` CLI which is already authenticated as `{assistant_account}`.
"""
    logger.info(f"Triggering on PR review: #{pr_number}")
    return Trigger(repo=repo, number=pr_number, prompt=prompt)


# Event handlers registry
EVENT_HANDLERS: dict[str, Callable] = {
    "issue_comment": handle_issue_comment,
    "issues": handle_issues,
    "pull_request_review": handle_pr_review,
}


async def run_agent(trigger: Trigger) -> None:
    """Run agent in background. Called as asyncio task."""
    repo_name = trigger.repo.split("/")[1]
    issue_number = trigger.number

    # Setup repo before spawning agent
    repo_path = await ensure_clone(
        config.data_dir,
        trigger.repo,
        config.github.assistant_account,
        config.github.assistant_account_token,
    )
    await copy_skills(config.data_dir, repo_path)

    # Get existing session or None
    existing_session_id = session_store.get_session_id(repo_name, issue_number)

    # Spawn agent
    backend = get_backend()
    new_session_id = await backend.spawn(trigger, existing_session_id, repo_path)

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

    # Check sender is authorized
    sender = payload.get("sender", {}).get("login", "")
    if sender not in config.github.authorized_users:
        logger.info(f"Not triggering: sender '{sender}' not authorized")
        return {"status": "ignored", "reason": f"Sender '{sender}' not authorized"}

    # Get handler for event type
    handler = EVENT_HANDLERS.get(event_type)
    if not handler:
        logger.info(f"Not triggering: event type '{event_type}' not supported")
        return {
            "status": "ignored",
            "reason": f"Event type '{event_type}' not supported",
        }

    # Run handler
    result = handler(payload, config.github.assistant_account)

    if isinstance(result, Trigger):
        logger.info(f"Triggering agent spawn for: {result}")
        asyncio.create_task(run_agent(result))
        return {"status": "triggered", "issue": result.number}
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
