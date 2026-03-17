# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run tests
uv run pytest

# Run single test file
uv run pytest tests/test_webhook.py

# Run with verbose output
uv run pytest -v

# Install dependencies
uv sync

# Install with Claude Agent SDK support
uv sync --extra claude

# Run webhook server (requires CLAWCOCO_CONFIG env var)
uv run clawcoco
```

## Architecture

ClawCoco is a GitHub webhook service that spawns AI agents to handle issues/PRs.

```
GitHub Webhook → FastAPI Server → Agent Backend → Spawned Agent Process
                      ↓
              Session Store (SQLite)
                      ↓
              GitHub IP Manager (validates request source)
```

### Key Components

- **webhook.py** - FastAPI endpoints, signature/IP verification, triggers agent spawn
- **agent.py** - `AgentBackend` abstraction with `OpenClawBackend` and `ClaudeSDKBackend` implementations
- **config.py** - Pydantic models for TOML config, loaded via `CLAWCOCO_CONFIG` env var
- **session_store.py** - SQLite-backed session persistence (maps repo+issue → session_id)
- **github_ip.py** - Fetches/refreshes GitHub IP ranges for webhook verification
- **scripts/run_claude_agent.py** - Subprocess script for ClaudeSDKBackend; clones repo, copies skills, runs agent

### Data Directory Structure

```
data_dir/
├── skills/           # Copied to cloned repos
├── repos/{org}/{repo}/  # Cloned repositories
└── db/sessions.db    # Session persistence
```

### Agent Workflow

1. Webhook receives `issue_comment` event with `@agent-name` mention
2. Validates: GitHub IP, HMAC signature, authorized user
3. Looks up existing session for repo+issue
4. Spawns agent process via configured backend
5. Agent runs in cloned repo with `github-collaboration` skill

## Code Style

- Uses `uv` for package management (not pip)
- Pydantic models for configuration validation
- SQLModel for database models
- Tests mock external calls (subprocess, HTTP) rather than executing them