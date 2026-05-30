"""Local-first agent routing — the general primitive behind the coding checks.

The same shape that makes the engineering review cheap generalizes to ANY
personal-agent stack (Hermes, OpenClaw, ...):

    user request
      -> parent agent (frontier, sparing)
      -> local/on-device subagents (cheap, private)   <- where most calls go
      -> private context + memory (RLM-externalized)
      -> cheap verification loops
      -> cloud escalation ONLY when needed
      -> final action

One user request can fan into dozens of hidden subagent calls (plan, search,
memory lookup, tool use, file inspect, CI/security/test checks, email draft,
calendar action, retries). If each goes to a frontier model, the bill balloons.
This module routes each subtask local-first and escalates to the cloud only on
low confidence / failed verification / high stakes, tallying the savings.
"""

from .tasks import SubtaskKind, RoutingPolicy, DEFAULT_POLICY  # noqa: F401
from .ledger import CostLedger, PRICES  # noqa: F401
from .escalation import EscalationRouter, Subtask, RouteOutcome, Tier  # noqa: F401
from .local import LocalModel, LocalSubagents  # noqa: F401
from .orchestrator import LocalFirstOrchestrator, ContextPacker, AgentRun, default_pipeline  # noqa: F401
from .state_backend import make_state_backend, LocalStateBackend, ButterbaseStateBackend  # noqa: F401
from .memory_backend import make_memory_backend, LocalMemoryBackend, EverMindMemoryBackend  # noqa: F401
