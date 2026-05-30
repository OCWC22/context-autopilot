# Submission — Beta Fund x EverMind Hackathon (2026-05-30)

**Track:** Next-Gen Infrastructure & Context · **Submission code:** `build0530`

## One-liner
A **$0 local repo-context model + skills + memory + subagents** that cuts frontier
token usage, cost, and latency while preserving task success — and an **eval harness
that proves it**. Inference optimization for coding agents, not a new code model.

## Slide 1 — Team / problem fit
Touchdown Labs. Coding agents (Claude Code/Codex) re-index the repo and re-send
context every session, paying frontier prices for repo discovery. We make the
cheap, repetitive work local and escalate to the frontier model only when needed.

## Slide 2 — Product
- **$0 local indexer** keeps a commit-versioned **DAG + SKILL.md** fresh on every change.
- **Selective retrieval + compression** (Repoformer/GraphCoder/LLavaCode-grounded).
- **Local subagents + RLM** do routing/search/checks/summarize; frontier only synthesizes.
- **Eval harness** measures tokens/time/accuracy vs normal Claude Code.

## Proof (measured by `autopilot eval`)
- Tokens saved: **98.7%**  ·  Time saved: **97.8%**  ·  Cost saved: **93.9%**
- Frontier calls avoided: **1**  ·  Retrieval F1: **+0.32**  ·  Task success preserved: **True**

## Sponsor usage
- **EverMind / EverOS** — built on it as the agent-memory brain: repo decisions, the
  architecture DAG, eval results, and coding-style traces become agent memory the
  system recalls across sessions (`autopilot/agent/memory_backend.py`).
- **Butterbase** — the backend + judging surface: projects, eval_runs, and bundle
  artifacts persist via the Data API; submitted via Butterbase MCP (`build0530`).

## Run it
```bash
autopilot index     # build the $0 versioned DAG + SKILL.md bundle
autopilot eval      # the proof: local-first vs normal Claude Code
autopilot submit    # push to Butterbase + EverMind (set keys; promo BUILD0530)
```
