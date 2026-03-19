"""Handler for pull_request_review events."""

import logging
from typing import Any

from clawcoco.agent import Trigger, run_agent
from clawcoco.config import config
from clawcoco.session_store import SessionStore

logger = logging.getLogger(__name__)


async def handle_pull_request_review(
    payload: dict[str, Any], session_store: SessionStore
) -> dict[str, Any]:
    """Handle pull_request_review event."""
    if payload.get("action") != "submitted":
        return {
            "status": "ignored",
            "reason": "Action ignored (only 'submitted' triggers)",
        }

    review = payload.get("review", {})
    if review.get("state") != "changes_requested":
        return {
            "status": "ignored",
            "reason": "Review state ignored (only 'changes_requested' triggers)",
        }

    review_body = review.get("body", "") or ""
    mention = f"@{config.github.assistant_account}"
    if mention not in review_body:
        return {
            "status": "ignored",
            "reason": f"No {mention} mention found in review body",
        }

    pr = payload.get("pull_request", {})
    pr_number = pr.get("number")
    pr_title = pr.get("title", "")
    pr_url = pr.get("html_url", "")

    if not pr_number or not pr_url:
        return {"status": "ignored", "reason": "Missing required fields in payload"}

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

Use the `gh` CLI which is already authenticated as `{config.github.assistant_account}`.
"""
    logger.info(f"Triggering on PR review: #{pr_number}")

    trigger = Trigger(repo=repo, number=pr_number, prompt=prompt)
    await run_agent(trigger, session_store)

    return {"status": "triggered", "issue": pr_number}
