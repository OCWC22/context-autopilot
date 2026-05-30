"""Hermes integration lives in two places:

- The live, installed integration (native tool + skill) under ~/.hermes — see
  `integrations/hermes/README.md`.
- The local-first task orchestration it calls is `autopilot.agent.orchestrator`
  (local subagents + RLM, escalate only the synthesis to the frontier model).

This package is intentionally thin; import from `autopilot.agent` for the
local-first execution layer.
"""
