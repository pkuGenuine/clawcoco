# ClawCoco
Claw Code Copilot, work with Openclaw via GitHub, with minimal trust

## What is this?
ClawCoco provides the glue between your GitHub repository and an AI agent:

- **Webhook Service** - Receives GitHub events and spawns the agent
- **Agent Skill** - Guides agent behavior and collaboration workflow
- **Multiple Backends** - Supports OpenClaw and Claude Agent SDK

## Running
1. Copy `config.example.toml` and configure it
2. Set `CLAWCOCO_CONFIG` environment variable to your config path
3. Install with your backend:
   - OpenClaw: `uv sync`
   - Claude Agent SDK: `uv sync --extra claude` (requires `claude` CLI installed)
4. Run `uv run clawcoco` to start the webhook server

## Triggering the Agent
The agent is triggered by GitHub webhook events when:
- Sender is an **authorized user** (configured in `authorized_users`)
- Message contains `@your-agent-name` mention

### Supported Events

| Event | Action | Description |
|-------|--------|-------------|
| `issue_comment` | `created` | Comment on issue or PR with @mention |
| `issues` | `opened` | New issue created with @mention in body |
| `pull_request_review` | `submitted` | PR review requesting changes with @mention |

### Examples

**Comment on an issue/PR:**
```
@claude-bot please help investigate this bug
```

**New issue:**
```
Title: Login fails on mobile
Body: @claude-bot users can't log in from Safari on iOS
```

**Request changes on a PR:**
```
Review comment: @claude-bot the error handling needs improvement
```
(Select "Request changes" when submitting the review)

## Philosophy
In worst cases, your claw could be fully compromised by an attacker and allow RCE
in your claw's execution environment. Thus, I would like to treat the agent as a kind,
enthusiastic contributor—but never fully trust him.

Create a dedicated GitHub account for your claw and let it work with its own fork.

All changes to your repo go through PR and your review.

## Threat Model
### Trusted
- The **authorized GitHub user** - your github accout and whoever you trust
### Untrusted
- The **agent account** - may be compromised or behave unexpectedly
### Trust Boundary Enforcement
- GitHub permissions: agent account has **NO write access** to origin repo
- Agent must work on its own fork
- All changes go through **fork → PR → human review**
### Webhook's Role
- Verify request comes from GitHub (signature, IP)
- Filter messages: only from authorized user AND with explicit `@your-agent-name`
- Spawn agent to handle the request

The webhook does not enforce the trust boundary — GitHub permissions do.


## Why not GitHub App?
Currently, the open source LLM (GLM-5) can not understand the permission system of
Github App even with official documentation.It seems that the permission control
of Github App is quite coarse-grained. We can not, for example, allow it to work on
a feat/xxx branch but prevent it from tamper other collaborators' branches.

I tentatively believe that the permission control of Github App is not enough to secure
the claw.
