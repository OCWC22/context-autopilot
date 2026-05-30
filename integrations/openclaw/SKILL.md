---
name: local-first-engineering-review
description: Use when asked to review, audit, or gate a repository or PR before merge/deploy (CI/CD, security, code quality, tests, dependencies, deployment). Runs six RLM-driven checks locally and returns a compact deployment gate instead of reading raw logs into context.
---

# Local-First Engineering Review (OpenClaw)

OpenClaw is local-first and spawns isolated subagents via `sessions_spawn`
(cheaper model recommended for children). This skill adds the RLM context layer:
inspect a repo's logs/configs/scan output through the Autopilot review and get
back a compact deployment gate, instead of pulling raw blobs into the session.

## When to use
- "Review this repo / PR", "is this safe to deploy?", "audit CI/security/deps".
- Anywhere you'd otherwise `read` large logs / scanner output / lockfiles to judge a change.

## How to run (via the `bash` tool)

```bash
# offline (no model needed):
python -m autopilot.cli review <repo> --sub-lm stub --json
# local on-device model (start it first): python -m autopilot.mlx_serve.server
python -m autopilot.cli review <repo> --sub-lm mlx --json
```

`autopilot` must be importable: `export AUTOPILOT_HOME=<checkout>` and
`export PYTHONPATH=$AUTOPILOT_HOME`, or `pip install -e $AUTOPILOT_HOME`.

The command prints a gate (`pass`/`warn`/`fail`), per-check verdicts + findings
(each with a `path:line` evidence ref), and a context->evidence compression
ratio. Its exit code is non-zero on a `fail` gate, so it composes in CI.

## How to act on the result
1. Report the gate + high/critical findings with their evidence refs. Keep it tight.
2. `read` only a specific ref you intend to verify or fix — never reload whole logs.
3. For the genuinely hard call, reason over the compact evidence; that's the step
   worth the frontier model.
4. To parallelize a monorepo, `sessions_spawn` one subagent per subtree, each
   running the review with `--checks ...`, then synthesize the gates. Keep
   children on a cheaper model (`agents.defaults.subagents.model`).

## Pitfalls
- Reading raw logs "to be sure" defeats the purpose — the checks already
  summarized them.
- `--sub-lm mlx` needs the local server running; otherwise use `stub`.
- `warn` is non-blocking; `fail` (or any high/critical finding) is the real stop.
