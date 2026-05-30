"""EscalationRouter: route one subtask local-first, verify cheaply, escalate to
the cloud only when needed, and gate irreversible actions behind a human.

Framework-agnostic: you plug in callables for the local model, a cheap verifier,
the cloud model, and (for mutating actions) a human gate. Hermes / OpenClaw /
any personal agent can adopt this directly. The router records every call in a
CostLedger so the hidden inference bill is visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .ledger import CostLedger, BASELINE_FRONTIER
from .tasks import DEFAULT_POLICY, RoutingPolicy


class Tier(str, Enum):
    local = "local"
    cloud = "cloud"
    gate = "gate"


@dataclass
class Subtask:
    kind: str                 # a SubtaskKind value
    prompt: str
    context_refs: list[str] = field(default_factory=list)  # RLM-externalized, not inlined
    stakes: str = "low"       # low | medium | high (raises escalation/gating)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalResult:
    text: str
    confidence: float            # 0..1, self-reported + verifier-adjusted
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class CloudResult:
    text: str
    model: str = BASELINE_FRONTIER
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class RouteOutcome:
    kind: str
    tier: str                    # Tier value that produced the accepted result
    result: str
    confidence: float = 0.0
    verified: bool = False
    escalated: bool = False
    attempts: int = 1
    gate_required: bool = False
    gate_approved: Optional[bool] = None
    reason: str = ""


# Pluggable callables (all optional; offline-safe stubs are provided).
LocalFn = Callable[[Subtask], LocalResult]
VerifyFn = Callable[[Subtask, str], bool]
CloudFn = Callable[[Subtask], CloudResult]
HumanGateFn = Callable[[Subtask, str], bool]


class EscalationRouter:
    def __init__(
        self,
        local_fn: LocalFn | None = None,
        verify_fn: VerifyFn | None = None,
        cloud_fn: CloudFn | None = None,
        human_gate_fn: HumanGateFn | None = None,
        policy: RoutingPolicy = DEFAULT_POLICY,
        ledger: CostLedger | None = None,
    ) -> None:
        self.local_fn = local_fn or _stub_local
        self.verify_fn = verify_fn or _stub_verify
        self.cloud_fn = cloud_fn or _stub_cloud
        self.human_gate_fn = human_gate_fn  # None => gated actions are NOT auto-approved
        self.policy = policy
        self.ledger = ledger or CostLedger()

    def route(self, task: Subtask) -> RouteOutcome:
        disp = self.policy.disposition(task.kind)
        if task.stakes == "high" and disp == "local_first":
            disp = "escalate"  # high stakes pulls routine work up to the frontier

        if disp == "escalate":
            return self._cloud(task, escalated=False, reason="policy: hard/high-stakes")
        if disp == "gate":
            return self._gate(task)
        return self._local_first(task)

    # --- tiers ---

    def _local_first(self, task: Subtask) -> RouteOutcome:
        attempts = 0
        last: LocalResult | None = None
        while attempts <= self.policy.max_local_retries:
            attempts += 1
            res = self.local_fn(task)
            last = res
            self.ledger.record(task.kind, Tier.local.value, "local", res.tokens_in, res.tokens_out)
            verified = self.verify_fn(task, res.text)
            if verified and res.confidence >= self.policy.min_local_confidence:
                return RouteOutcome(
                    kind=task.kind, tier=Tier.local.value, result=res.text,
                    confidence=res.confidence, verified=True, escalated=False,
                    attempts=attempts, reason="local accepted (verified, confident)",
                )
        # local exhausted -> escalate
        out = self._cloud(task, escalated=True, reason=f"local low-confidence/failed-verify after {attempts} tries")
        out.attempts = attempts
        out.confidence = last.confidence if last else 0.0
        return out

    def _cloud(self, task: Subtask, escalated: bool, reason: str) -> RouteOutcome:
        res = self.cloud_fn(task)
        self.ledger.record(task.kind, Tier.cloud.value, res.model, res.tokens_in, res.tokens_out, escalated=escalated)
        return RouteOutcome(
            kind=task.kind, tier=Tier.cloud.value, result=res.text,
            confidence=1.0, verified=True, escalated=escalated, reason=reason,
        )

    def _gate(self, task: Subtask) -> RouteOutcome:
        # Propose locally (cheap), but an irreversible action needs a human OK.
        proposal = self.local_fn(task)
        self.ledger.record(task.kind, Tier.local.value, "local", proposal.tokens_in, proposal.tokens_out)
        approved = self.human_gate_fn(task, proposal.text) if self.human_gate_fn else None
        return RouteOutcome(
            kind=task.kind, tier=Tier.gate.value, result=proposal.text,
            confidence=proposal.confidence, verified=False, escalated=False,
            gate_required=True, gate_approved=approved,
            reason="irreversible action: proposed locally, awaiting human gate"
            if approved is None else ("approved by gate" if approved else "rejected by gate"),
        )


# --- offline-safe stubs (so the router runs + tests without any model) ---

def _stub_local(task: Subtask) -> LocalResult:
    # confidence shrinks with stakes; deterministic for tests
    conf = {"low": 0.85, "medium": 0.6, "high": 0.4}.get(task.stakes, 0.85)
    return LocalResult(text=f"[local:{task.kind}] {task.prompt[:60]}", confidence=conf, tokens_in=400, tokens_out=120)


def _stub_verify(task: Subtask, result: str) -> bool:
    return bool(result) and "error" not in result.lower()


def _stub_cloud(task: Subtask) -> CloudResult:
    return CloudResult(text=f"[cloud:{task.kind}] {task.prompt[:60]}", model=BASELINE_FRONTIER, tokens_in=1800, tokens_out=500)
