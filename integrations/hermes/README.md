# Hermes integration (real, installed)

This wires the Personal Coding Model Autopilot into the real
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) you
have installed (`~/.local/bin/hermes`, source at `~/.hermes/hermes-agent`). The
result: the Hermes agent can run a **local-first, multi-subagent RLM engineering
review** as a native tool, and can run its own loop on the **local distilled
model** — frontier tokens only for synthesis.

## What's installed (and verified)

1. **Native tool** — `~/.hermes/hermes-agent/tools/autopilot_review.py`
   Auto-discovered by Hermes's `discover_builtin_tools()` (it contains a
   `registry.register(...)` call). Verified: the real registry discovers it
   (`tools.autopilot_review`, toolset `engineering`) and `registry.dispatch(
   "autopilot_review", {"repo": "...", "sub_lm": "stub"})` returns a real gate +
   compact evidence. It locates the autopilot package via `AUTOPILOT_HOME` or the
   default checkout path — no system install needed. Import-fail-safe: if the
   package is missing, Hermes skips the tool with a warning.

2. **Skill** — `~/.hermes/skills/software-development/local-first-engineering-review/SKILL.md`
   Tells the agent when/how to use `autopilot_review` local-first: externalize
   logs/configs via RLM, return compact evidence, open only the `evidence_ref`s
   it will act on, and spend the frontier model only on the hard synthesis.

3. **Local-model provider** — `local-mlx-provider.yaml` (this dir). Additive
   block / `hermes config set` commands to point Hermes at the local MLX server.
   Not auto-applied (your `config.yaml` is hand-maintained); run the commands
   when you want it.

## Use it

In a Hermes chat (or via Telegram/Discord through the gateway):

> "Review /path/to/repo before I deploy"

The agent loads the skill and calls `autopilot_review(repo=..., sub_lm="mlx")`.
If the local server isn't up it falls back to `sub_lm="stub"` (offline).

Run the local model first (Apple Silicon + `pip install mlx-lm`):

```bash
python -m autopilot.mlx_serve.server      # OpenAI endpoint at :8080
# then, to run Hermes itself on the local model:
hermes config set providers.local_mlx.base_url "http://127.0.0.1:8080/v1"
hermes config set providers.local_mlx.api_mode "openai"
hermes chat --provider local_mlx --model mlx-community/Qwen2.5-Coder-3B-Instruct-4bit
```

Make `autopilot` importable to the tool from anywhere (one of):

```bash
export AUTOPILOT_HOME=/Users/chen/Projects/Touchdown-Labs/personal-coding-autopilot
# or
pip install -e /Users/chen/Projects/Touchdown-Labs/personal-coding-autopilot --break-system-packages
```

## Why this is the local-first thesis, in a real agent

Hermes already delegates and parallelizes (its `delegate_task` tool spawns
subagents with cheaper models). `autopilot_review` adds the RLM context layer:
each check holds its logs/configs *outside* the model and returns compact
evidence, so the agent's context — and the bill — stays small no matter how big
the inputs. On the test repo the review externalized ~400KB and returned ~11KB
to the parent (36× compression). Pair it with the `local_mlx` provider and the
routine bulk runs on-device at ~$0, with the frontier model reserved for the
final gate judgment.
