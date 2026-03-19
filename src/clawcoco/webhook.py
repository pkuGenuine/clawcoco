#!/usr/bin/env python3
"""
GitHub Webhook Receiver for ClawCoco Agent

Receives GitHub webhooks, filters for @mentions from authorized user,
and spawns agent sessions to handle each issue/PR.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from .config import config
from .github_ip import GitHubIPManager
from .handlers import HANDLERS
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
    handler = HANDLERS.get(event_type)
    if not handler:
        logger.info(f"Not triggering: event type '{event_type}' not supported")
        return {
            "status": "ignored",
            "reason": f"Event type '{event_type}' not supported",
        }

    # Run handler
    return await handler(payload, session_store)


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
