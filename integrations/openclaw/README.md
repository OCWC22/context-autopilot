# OpenClaw integration

[OpenClaw](https://github.com/openclaw/openclaw) (`hermes claw migrate` migrates
from it) is local-first and uses `sessions_spawn` subagents. It is **not
installed on this machine** (no `~/.openclaw/`), so this is a portable artifact
rather than a live wiring like the Hermes one.

OpenClaw is TypeScript and exposes a `bash` tool rather than Python tool
registration, so the skill drives the Autopilot **CLI** (`python -m
autopilot.cli review`) instead of a native tool. The SKILL.md here follows the
agentskills.io standard (the same standard Hermes skills use), so it drops in
unchanged.

## Install (when OpenClaw is set up)

```bash
mkdir -p ~/.openclaw/workspace/skills/local-first-engineering-review
cp SKILL.md ~/.openclaw/workspace/skills/local-first-engineering-review/SKILL.md
export AUTOPILOT_HOME=/Users/chen/Projects/Touchdown-Labs/personal-coding-autopilot
export PYTHONPATH=$AUTOPILOT_HOME
```

Then ask the assistant to "review <repo> before deploy"; it runs the review via
its `bash` tool and reports the gate. Point children at a cheaper model via
`agents.defaults.subagents.model`, and the main agent at the local MLX endpoint
the same way (`base_url: http://127.0.0.1:8080/v1`, `api_mode: openai`).
