#!/usr/bin/env python3
"""
GitHub Webhook Receiver for OpenClaw Agent

Receives GitHub webhooks, filters for @mentions from authorized user,
and spawns isolated OpenClaw sessions to handle each issue/PR.
"""

import argparse
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict, cast

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from .config import Config, load_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default GitHub IP ranges for webhook delivery (fallback if fetch fails)
# https://api.github.com/meta
DEFAULT_GITHUB_IP_RANGES = [
    "192.30.252.0/22",
    "185.199.108.0/22",
    "140.82.112.0/20",
    "143.55.64.0/20",
]

GITHUB_META_URL = "https://api.github.com/meta"
IP_REFRESH_INTERVAL = timedelta(hours=24)


class GitHubIPManager:
    """Manages GitHub IP ranges with automatic refresh."""

    def __init__(self) -> None:
        self._ranges: list[str] = DEFAULT_GITHUB_IP_RANGES.copy()
        self._last_fetch: datetime | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._shutdown = False

    async def initialize(self, http_client: httpx.AsyncClient) -> None:
        """Initialize with HTTP client and fetch initial ranges."""
        self._http_client = http_client
        await self.fetch()
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def shutdown(self) -> None:
        """Stop background refresh task."""
        self._shutdown = True
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

    async def fetch(self) -> bool:
        """Fetch latest IP ranges from GitHub API."""
        if not self._http_client:
            logger.warning("HTTP client not initialized, using default ranges")
            return False

        try:
            response = await self._http_client.get(GITHUB_META_URL, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            # Extract webhook IP ranges
            if "hooks" in data and isinstance(data["hooks"], list):
                self._ranges = data["hooks"]
                self._last_fetch = datetime.now(timezone.utc)
                logger.info(f"Fetched {len(self._ranges)} GitHub IP ranges")
                return True
            else:
                logger.warning("No 'hooks' field in GitHub meta response")
                return False

        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch GitHub IP ranges: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error fetching GitHub IP ranges: {e}")
            return False

    async def _refresh_loop(self) -> None:
        """Background task to periodically refresh IP ranges."""
        while not self._shutdown:
            await asyncio.sleep(IP_REFRESH_INTERVAL.total_seconds())
            if not self._shutdown:
                success = await self.fetch()
                if not success:
                    logger.warning("IP range refresh failed, keeping current ranges")

    def get_ranges(self) -> list[str]:
        """Get current IP ranges."""
        return self._ranges

    @property
    def last_fetch(self) -> datetime | None:
        """Get timestamp of last successful fetch."""
        return self._last_fetch


# Global instances (set during startup)
config: Config
ip_manager: GitHubIPManager = GitHubIPManager()


class TriggerInfo(TypedDict):
    """Info about a webhook event that triggers the agent."""

    url: str
    title: str
    number: int
    sender: str
    repo: str
    event_type: str
    mention_text: str


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

    # Check action is "created" or "opened" (not edit/delete)
    action = payload.get("action", "")
    if action not in ("created", "opened"):
        return False, f"Action '{action}' ignored (only 'created'/'opened' trigger)"

    # Check sender is authorized
    sender = payload.get("sender", {}).get("login", "")
    if sender != github_config.authorized_user:
        return False, f"Sender '{sender}' not authorized"

    # Check for @mention based on event type

    if event_type == "issue_comment":
        # This event occurs when there is activity relating to a comment on an issue
        # or pull request
        comment_body = payload.get("comment", {}).get("body", "") or ""
        mention_pattern = f"@{github_config.assistant_account}"
        if mention_pattern not in comment_body:
            return False, f"No {mention_pattern} mention found"
        issue_url = payload.get("issue", {}).get("html_url", "")
        issue_title = payload.get("issue", {}).get("title", "")
        issue_number = payload.get("issue", {}).get("number")
        mention_text = comment_body

    elif event_type == "issues":
        # This event occurs when there is activity relating to an issue
        # Action "opened" means a new issue was created
        issue_body = payload.get("issue", {}).get("body", "") or ""
        mention_pattern = f"@{github_config.assistant_account}"
        if mention_pattern not in issue_body:
            return False, f"No {mention_pattern} mention found"
        issue_url = payload.get("issue", {}).get("html_url", "")
        issue_title = payload.get("issue", {}).get("title", "")
        issue_number = payload.get("issue", {}).get("number")
        mention_text = issue_body

    elif event_type == "pull_request":
        # This event occurs when there is activity relating to a pull request
        # Action "opened" means a new PR was created
        pr_body = payload.get("pull_request", {}).get("body", "") or ""
        mention_pattern = f"@{github_config.assistant_account}"
        if mention_pattern not in pr_body:
            return False, f"No {mention_pattern} mention found"
        issue_url = payload.get("pull_request", {}).get("html_url", "")
        issue_title = payload.get("pull_request", {}).get("title", "")
        issue_number = payload.get("pull_request", {}).get("number")
        mention_text = pr_body

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

async def spawn_agent_session(trigger_info: TriggerInfo) -> bool:
    """Spawn an OpenClaw agent session via CLI to handle the issue."""
    agent_id = config.openclaw.agent_id

    # Build session ID: github-{repo_name}-issue-{issue_number}
    repo_name = trigger_info["repo"].split("/")[1]
    issue_number = trigger_info["number"]
    session_id = f"github-{repo_name}-issue-{issue_number}"

    logger.info(f"Session ID: {session_id}")

    # Build task prompt
    task = f"""You have been summoned via GitHub mention.

**Issue/PR:** {trigger_info['title']}
**Repository:** {trigger_info['repo']}
**From:** @{trigger_info['sender']}
**URL:** {trigger_info['url']}

Please:
1. Read the issue/PR at the URL above using `gh issue view` or `gh pr view`
2. Understand what is being asked
3. Respond appropriately (answer questions, implement changes, etc.)
4. Post your response as a comment using `gh issue comment` or `gh pr comment`

Use the `gh` CLI which is already authenticated as `{config.github.assistant_account}`.
"""

    # Build CLI command
    cmd = [
        "openclaw",
        "agent",
        "--agent",
        agent_id,
        "--session-id",
        session_id,
        "--message",
        task,
        "--timeout",
        "0",  # No timeout
    ]

    logger.info(f"Running: {' '.join(cmd[:6])}... (message truncated)")

    try:
        # Run in background, discard output to avoid pipe buffer deadlock
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        logger.info(f"Spawned process PID: {process.pid}")
        return True
    except Exception as e:
        logger.error(f"Failed to spawn agent: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    # Startup: initialize IP manager with HTTP client
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
        success = await spawn_agent_session(trigger_info)
        if success:
            logger.info("Successfully spawned agent session")
        else:
            logger.error("Failed to spawn agent session")
        return {"status": "triggered", "info": result}
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
        "authorized_user": config.github.authorized_user,
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
    parser = argparse.ArgumentParser(description="ClawCoco GitHub Webhook Server")
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        required=False,
        help="Path to config file (defaults to CLAWCOCO_CONFIG env var)",
    )
    args = parser.parse_args()

    # Load and validate config
    global config
    try:
        config = load_config(args.config)
        logger.info(f"Loaded config successfully")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise SystemExit(1)

    # Set log level
    if config.webhook.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    logger.info(f"Starting webhook server on port {config.webhook.port}")
    logger.info(f"Debug mode: {config.webhook.debug}")
    logger.info(f"Authorized user: {config.github.authorized_user}")

    uvicorn.run(app, host="0.0.0.0", port=config.webhook.port)


if __name__ == "__main__":
    main()
