"""Multi-subagent engineering review.

Six subagents, each owning one check (CI/CD, security, code quality, test
execution, dependency analysis, deployment validation). Each externalizes its
long context (files/logs/configs/traces) through an RLM (depth=1) and returns
COMPACT evidence to the parent orchestrator. The RLM sub-LM is the local MLX
model; the parent (synthesis / gate) is Claude. See RECEIPTS.md v2.
"""

from .evidence import CheckEvidence, Finding, Severity  # noqa: F401
