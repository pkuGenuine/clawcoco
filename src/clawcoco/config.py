"""Configuration management for ClawCoco."""

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class WebhookConfig(BaseModel):
    """Webhook server configuration."""

    secret: str = Field(
        ..., description="GitHub webhook secret for signature verification"
    )
    port: int = Field(default=8080, ge=1, le=65535, description="Port to listen on")
    debug: bool = Field(default=False, description="Enable debug logging")
    github_ips_only: bool = Field(
        default=True, description="Only accept requests from GitHub IP ranges"
    )


class GitHubConfig(BaseModel):
    """GitHub integration configuration."""

    authorized_users: list[str] = Field(
        ..., description="GitHub usernames allowed to trigger the agent"
    )
    assistant_account: str = Field(
        ..., description="GitHub username of the agent (for @mentions)"
    )
    assistant_account_token: str = Field(
        ..., description="GitHub token for the agent account (repo scope)"
    )


class OpenClawConfig(BaseModel):
    """OpenClaw agent configuration."""

    agent_id: str = Field(default="coder", description="Agent ID to spawn")


class ClaudeSDKConfig(BaseModel):
    """Claude Agent SDK configuration."""

    model: str = Field(
        default="glm-5", description="Claude model to use"
    )
    allowed_tools: list[str] = Field(
        default=["Read", "Edit", "Write", "Bash", "Glob", "Grep"],
        description="Tools the agent can use",
    )


class Config(BaseModel):
    """Root configuration model."""

    webhook: WebhookConfig
    github: GitHubConfig
    data_dir: Path
    openclaw: OpenClawConfig = Field(default_factory=OpenClawConfig)
    claude_sdk: ClaudeSDKConfig = Field(default_factory=ClaudeSDKConfig)
    backend_type: str = Field(
        default="openclaw", description="Backend: 'openclaw' or 'claude_sdk'"
    )


def load_config(config_path: str | Path | None = None) -> Config:
    """
    Load configuration from TOML file.

    Priority:
    1. Explicit path provided via CLI arg
    2. CLAWCOCO_CONFIG environment variable
    3. Error if neither provided
    """
    # Resolve path
    if config_path is None:
        env_path = os.environ.get("CLAWCOCO_CONFIG")
        if env_path:
            config_path = Path(env_path)
        else:
            raise ValueError(
                "Config path required. Provide via --config flag or CLAWCOCO_CONFIG env var"
            )

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    return Config.model_validate(raw)
