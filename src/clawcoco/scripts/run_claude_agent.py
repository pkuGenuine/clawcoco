#!/usr/bin/env python3
"""Claude Agent SDK runner script."""

import argparse
import asyncio

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage


async def run_agent(
    prompt: str, session_id: str | None, model: str, tools: list[str]
) -> str:
    """Run agent and return new session ID."""
    options = ClaudeAgentOptions(
        model=model,
        allowed_tools=tools,
        resume=session_id,
    )

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            return message.session_id

    return ""


def main():
    parser = argparse.ArgumentParser(description="Run Claude Agent")
    parser.add_argument("--prompt", required=True, help="Task prompt")
    parser.add_argument("--session-id", help="Session ID to resume")
    parser.add_argument(
        "--model", default="claude-sonnet-4-5-20250929", help="Model to use"
    )
    parser.add_argument(
        "--tools",
        default="Read,Edit,Write,Bash,Glob,Grep",
        help="Comma-separated tools",
    )
    args = parser.parse_args()

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    session_id = asyncio.run(
        run_agent(args.prompt, args.session_id, args.model, tools)
    )

    # Output session ID to stdout for caller to capture
    print(session_id)


if __name__ == "__main__":
    main()