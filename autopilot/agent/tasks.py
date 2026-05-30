"""Subtask taxonomy + the default local-first routing policy.

Generalizes the coding RiskPolicy to the full personal-agent surface. The policy
is deliberately conservative and auditable (rules, not a model): routine,
verifiable, read-mostly subtasks run local; hard reasoning and irreversible /
high-stakes actions escalate or require human/cloud confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SubtaskKind(str, Enum):
    # read-mostly / routine -> local-first
    search = "search"
    memory_lookup = "memory_lookup"
    file_inspect = "file_inspect"
    summarize = "summarize"
    classify = "classify"
    ci_check = "ci_check"
    security_review = "security_review"
    code_review = "code_review"
    test_run = "test_run"
    dependency_scan = "dependency_scan"
    deploy_validate = "deploy_validate"
    email_draft = "email_draft"        # DRAFT only is local; sending is an action
    tool_use = "tool_use"
    verify = "verify"
    retry = "retry"
    plan = "plan"                      # local-first; escalates only if complex/low-confidence
    state_update = "state_update"      # write to external state/memory (mostly deterministic)
    # hard / stakes -> escalate
    hard_reasoning = "hard_reasoning"
    synthesis = "synthesis"            # the final high-value report handed to the frontier model
    # mutating / irreversible -> never silently local; cloud-verify + human gate
    email_send = "email_send"
    calendar_action = "calendar_action"
    payment = "payment"
    deploy_apply = "deploy_apply"
    delete = "delete"


@dataclass
class RoutingPolicy:
    """Which kinds run local-first, which always escalate, which are gated."""

    local_first: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                SubtaskKind.search.value,
                SubtaskKind.memory_lookup.value,
                SubtaskKind.file_inspect.value,
                SubtaskKind.summarize.value,
                SubtaskKind.classify.value,
                SubtaskKind.ci_check.value,
                SubtaskKind.security_review.value,
                SubtaskKind.code_review.value,
                SubtaskKind.test_run.value,
                SubtaskKind.dependency_scan.value,
                SubtaskKind.deploy_validate.value,
                SubtaskKind.email_draft.value,
                SubtaskKind.tool_use.value,
                SubtaskKind.verify.value,
                SubtaskKind.retry.value,
                SubtaskKind.plan.value,          # local plans first; escalate only if shaky
                SubtaskKind.state_update.value,
            }
        )
    )
    # Reserve the frontier model for genuinely hard reasoning and the final
    # high-value synthesis/report — the parts where quality matters most.
    always_escalate: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {SubtaskKind.hard_reasoning.value, SubtaskKind.synthesis.value}
        )
    )
    # mutating / irreversible: require cloud verification AND a human gate before action
    gated_actions: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                SubtaskKind.email_send.value,
                SubtaskKind.calendar_action.value,
                SubtaskKind.payment.value,
                SubtaskKind.deploy_apply.value,
                SubtaskKind.delete.value,
            }
        )
    )
    # accept a local result only at/above this self-reported+verified confidence
    min_local_confidence: float = 0.7
    # how many local retries before escalating
    max_local_retries: int = 1

    def disposition(self, kind: str) -> str:
        if kind in self.gated_actions:
            return "gate"
        if kind in self.always_escalate:
            return "escalate"
        if kind in self.local_first:
            return "local_first"
        return "escalate"  # unknown -> safe default is the frontier model


DEFAULT_POLICY = RoutingPolicy()
