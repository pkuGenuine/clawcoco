"""Event handlers for ClawCoco webhook."""

from typing import Awaitable, Callable

from clawcoco.session_store import SessionStore

from .issue_comment import handle_issue_comment
from .issues import handle_issues
from .pull_request import handle_pull_request
from .pull_request_review import handle_pull_request_review

HandlerFunc = Callable[[dict, SessionStore], Awaitable[dict]]

HANDLERS: dict[str, HandlerFunc] = {
    "issue_comment": handle_issue_comment,
    "issues": handle_issues,
    "pull_request": handle_pull_request,
    "pull_request_review": handle_pull_request_review,
}

__all__ = [
    "HANDLERS",
    "handle_issue_comment",
    "handle_issues",
    "handle_pull_request",
    "handle_pull_request_review",
]
