"""Handler for issues events."""

import logging
from typing import Any

from clawcoco.agent import Trigger, run_agent
from clawcoco.config import config
from clawcoco.session_store import SessionStore

logger = logging.getLogger(__name__)


async def handle_issues(
    payload: dict[str, Any], session_store: SessionStore
) -> dict[str, Any]:
    """Handle issues event."""
    if payload.get("action") != "opened":
        return {
            "status": "ignored",
            "reason": "Action ignored (only 'opened' triggers)",
        }

    issue = payload.get("issue", {})
    issue_body = issue.get("body", "") or ""
    mention = f"@{config.github.assistant_account}"
    if mention not in issue_body:
        return {"status": "ignored", "reason": f"No {mention} mention found"}

    issue_number = issue.get("number")
    issue_title = issue.get("title", "")
    issue_url = issue.get("html_url", "")

    if not issue_number or not issue_url:
        return {"status": "ignored", "reason": "Missing required fields in payload"}

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

Use the `gh` CLI which is already authenticated as `{config.github.assistant_account}`.
"""
    logger.info(f"Triggering on new issue: #{issue_number}")

    trigger = Trigger(repo=repo, number=issue_number, prompt=prompt)
    await run_agent(trigger, session_store)

    return {"status": "triggered", "issue": issue_number}
