"""The routing policy: decide whether a coding task may go to the personal model
or must fall back to Claude/Codex, and verify the personal model's output before
accepting it.

Honest economics (RECEIPTS.md cluster 7): routing is a proven 30-80% cost lever,
but only against METERED API spend, and code generation is the worst routing
case (~22% in the literature) because correctness errors are costly. So the
policy is deliberately conservative: high-risk and below-gate task types never
route, and personal-model output is verified (typecheck/lint) before it counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..config import RiskPolicy
from ..types import RiskLevel


@dataclass
class CodingTask:
    id: str
    prompt: str
    task_type: str
    risk: str  # low | medium | high
    files_touched: list[str] = field(default_factory=list)
    eval_pass_rate: Optional[float] = None  # this task type's held-out eval pass rate


@dataclass
class RouteDecision:
    route: str  # "personal" | "fallback"
    reason: str
    verified: bool = False


@dataclass
class RouteResult:
    decision: RouteDecision
    output: Optional[str] = None
    model_used: str = ""


# A personal-model call: (task) -> (text, typecheck_passed, lint_passed)
PersonalFn = Callable[[CodingTask], tuple[str, bool, bool]]
FallbackFn = Callable[[CodingTask], str]


def decide(task: CodingTask, policy: RiskPolicy) -> RouteDecision:
    if task.risk == RiskLevel.high.value or task.task_type in policy.always_fallback:
        return RouteDecision("fallback", "high-risk or fallback-only task type")
    if task.task_type not in policy.personal_ok:
        return RouteDecision("fallback", "task type not approved for personal model")
    if (task.eval_pass_rate or 0.0) < policy.min_eval_pass_rate:
        return RouteDecision(
            "fallback",
            f"eval pass rate {task.eval_pass_rate} below gate {policy.min_eval_pass_rate}",
        )
    return RouteDecision("personal", "low-risk, verifiable, above eval gate")


def route_task(
    task: CodingTask,
    policy: RiskPolicy,
    run_personal: PersonalFn,
    run_fallback: FallbackFn,
    personal_model_name: str = "personal-coder",
    fallback_model_name: str = "claude-code",
) -> RouteResult:
    """Mirror of the demo's routeCodingTask, with a verify-before-accept gate."""
    d = decide(task, policy)
    if d.route == "fallback":
        return RouteResult(d, run_fallback(task), fallback_model_name)

    text, typecheck_ok, lint_ok = run_personal(task)
    if not typecheck_ok or not lint_ok:
        # personal output failed verification -> fall back, don't ship bad code
        d2 = RouteDecision("fallback", "personal output failed typecheck/lint", verified=False)
        return RouteResult(d2, run_fallback(task), fallback_model_name)

    d.verified = True
    return RouteResult(d, text, personal_model_name)
