# ClawCoco
Claw Code Copilot, work with Openclaw via github, with minimal trust

## What is this?
ClawCoco provides the glue between your GitHub repository and Openclaw agent:

- **Webhook Service** - Receives GitHub events and notifies the agent
- **Agent Skill** - Guides Openclaw's behavior and workflow

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
