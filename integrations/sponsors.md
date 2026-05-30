# Hackathon sponsors: Butterbase (state) + EverMind/"Revermind" (memory)

Two sponsor backends slot into the local-first agent stack at exactly the two
places that should live **outside** the frontier model: durable state and
long-context memory. Both are optional and **auto-selected by env keys** — with
no keys the agent runs on offline local backends, so nothing breaks in a demo.

| Layer | Sponsor | What it stores | Local fallback |
|---|---|---|---|
| Agent database / state | **Butterbase** (`docs.butterbase.ai`) | per-run event log, run records, KV agent state (the `state_update` subtask) | `LocalStateBackend` (jsonl + kv.json) |
| Long-context memory | **EverMind / EverOS** (`docs.evermind.ai`; the "Revermind" sponsor) | cross-session episode summaries + profile (the `memory_lookup` subtask) | `LocalMemoryBackend` (keyword recall) |

> Naming: the brief said "Revermind"; the matching product is **EverMind / EverOS**
> (`pip install everos`, `https://api.evermind.ai`). If Revermind is a distinct
> product, only `memory_backend.py`'s REST shape changes — the interface is the same.

## Why these two, here

- **EverMind returns compact summaries, not raw logs** — the same compact-context
  principle as the RLM checks. `memory_lookup` is a cheap retrieval (an API call),
  never a frontier-model call. Recall accumulates across runs, so repeated work
  stops re-deriving context (demoed: a second run's `memory_lookup` stays local).
- **Butterbase holds the externalized state** the agent reads/writes between
  steps and across sessions, so the frontier model never reloads it. Its Durable
  Objects are literally pitched for "long-running AI agents."

## Turn them on

```bash
export BUTTERBASE_APP_ID=app_...        # Butterbase app
export BUTTERBASE_API_KEY=bb_sk_...      # service key
export EVEROS_API_KEY=...                # EverMind/EverOS (or EVERMIND_API_KEY)
```

The orchestrator (`autopilot.agent.LocalFirstOrchestrator`) auto-selects:
`make_state_backend()` → Butterbase when keyed, `make_memory_backend()` → EverMind
when keyed. The run output prints which backends are active.

Butterbase schema to apply once (via its schema tools / dashboard):

```
agent_events(id uuid pk default gen_random_uuid(), run_id text, kind text, tier text, payload jsonb, created_at timestamptz default now())
agent_runs(id uuid pk default gen_random_uuid(), run_id text unique, payload jsonb, created_at timestamptz default now())
agent_state(key text primary, value jsonb)
```

## Applied to Hermes

The Hermes tool `autopilot_local_task` runs the orchestrator, so it picks up both
sponsors automatically when the env keys are set — Hermes's internal subtasks
then log state to Butterbase and recall memory from EverMind, while Hermes (the
frontier model) only synthesizes. Set the keys in `~/.hermes/.env`. (Hermes also
has its own `memory` tool; the sponsor path replaces the *backing store* with
EverMind without changing the agent loop.)

## Applied to OpenClaw

OpenClaw runs the CLI via its `bash` tool; export the same env vars in the
OpenClaw workspace environment and `python -m autopilot.cli ...` / the local task
path uses Butterbase + EverMind identically. OpenClaw's own `sessions_spawn`
subagents inherit the env, so each child's state/memory lands in the same shared
Butterbase app and EverMind user space — giving the swarm shared state + memory.
