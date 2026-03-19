"""Handler for pull_request events."""

import logging
import re
from typing import Any

from clawcoco.session_store import SessionStore

logger = logging.getLogger(__name__)


async def handle_pull_request(
    payload: dict[str, Any], session_store: SessionStore
) -> dict[str, Any]:
    """Handle pull_request event for tracking agent-created PRs."""
    if payload.get("action") != "opened":
        return {
            "status": "ignored",
            "reason": "Action ignored (only 'opened' triggers)",
        }

    pr = payload.get("pull_request", {})
    head = pr.get("head", {})
    branch = head.get("ref", "")

    # Check branch pattern: agent/{issue_number}
    match = re.match(r"^agent/(\d+)$", branch)
    if not match:
        return {
            "status": "ignored",
            "reason": f"Branch '{branch}' doesn't match pattern 'agent/{{issue_number}}'",
        }

    issue_number = int(match.group(1))
    repo = payload.get("repository", {}).get("full_name", "")
    pr_number = pr.get("number")

    if not repo or not pr_number:
        return {"status": "ignored", "reason": "Missing required fields in payload"}

    # Update session store with PR number
    repo_name = repo.split("/")[1]
    session_store.set_pr_number(repo_name, issue_number, pr_number)

    logger.info(f"Tracked PR #{pr_number} for issue #{issue_number} in {repo}")
    return {"status": "pr_tracked", "issue": issue_number, "pr": pr_number}
