#!/usr/bin/env python3
"""Claude Agent SDK runner script."""

import argparse
import asyncio
import logging
import os

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from clawcoco.config import config

logger = logging.getLogger(__name__)


async def run_agent(
    prompt: str, session_id: str | None, model: str, tools: list[str]
) -> str:
    """Run agent and return new session ID."""
    options = ClaudeAgentOptions(
        model=model,
        allowed_tools=tools,
        resume=session_id,
        setting_sources=["user", "project"],
    )

    result_session_id = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result_session_id = message.session_id

    return result_session_id


def main():
    parser = argparse.ArgumentParser(description="Run Claude Agent")
    parser.add_argument("--prompt", required=True, help="Task prompt")
    parser.add_argument("--session-id", help="Session ID to resume")
    parser.add_argument("--repo", required=True, help="Full repo name (org/repo)")
    parser.add_argument("--issue", required=True, type=int, help="Issue/PR number")
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Set environment variables for agent context
    os.environ["GITHUB_REPO"] = args.repo
    os.environ["GITHUB_ISSUE"] = str(args.issue)
    os.environ["GH_TOKEN"] = config.github.assistant_account_token

    # Run agent
    tools = config.claude_sdk.allowed_tools
    session_id = asyncio.run(
        run_agent(args.prompt, args.session_id, config.claude_sdk.model, tools)
    )

    # Output session ID to stdout for caller to capture
    print(session_id)


if __name__ == "__main__":
    main()
