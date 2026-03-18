#!/usr/bin/env python3
"""Claude Agent SDK runner script."""

import argparse
import asyncio
import logging
import os
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from clawcoco.git_utils import ensure_clone, copy_skills

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
    parser.add_argument("--model", default="glm-5", help="Model to use")
    parser.add_argument(
        "--tools",
        default="Skill,Read,Edit,Write,Bash,Glob,Grep",
        help="Comma-separated tools",
    )
    parser.add_argument(
        "--data-dir", required=True, help="Base data directory for repos"
    )
    parser.add_argument("--repo", required=True, help="Full repo name (org/repo)")
    parser.add_argument("--issue", required=True, type=int, help="Issue/PR number")
    parser.add_argument(
        "--assistant-account", required=True, help="Agent's GitHub username"
    )
    parser.add_argument(
        "--github-token", required=True, help="GitHub token for agent account"
    )
    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Ensure repo is cloned
    data_dir = Path(args.data_dir)
    repo_path = ensure_clone(
        data_dir, args.repo, args.assistant_account, args.github_token
    )
    copy_skills(data_dir, repo_path)

    # Change to repo directory
    os.chdir(repo_path)
    logger.info(f"Working directory: {repo_path}")

    # Set environment variables for agent context
    os.environ["GITHUB_REPO"] = args.repo
    os.environ["GITHUB_ISSUE"] = str(args.issue)

    # Run agent
    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    session_id = asyncio.run(run_agent(args.prompt, args.session_id, args.model, tools))

    # Output session ID to stdout for caller to capture
    print(session_id)


if __name__ == "__main__":
    main()
