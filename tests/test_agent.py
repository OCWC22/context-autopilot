"""Local-first escalation router tests (offline, stdlib only)."""

from __future__ import annotations

from autopilot.agent import EscalationRouter, Subtask, CostLedger, SubtaskKind
from autopilot.agent.escalation import LocalResult, CloudResult, Tier


def test_routine_runs_local():
    r = EscalationRouter(ledger=CostLedger())
    o = r.route(Subtask(SubtaskKind.search.value, "find docs"))
    assert o.tier == Tier.local.value
    assert o.verified and not o.escalated


def test_hard_reasoning_goes_cloud():
    r = EscalationRouter(ledger=CostLedger())
    o = r.route(Subtask(SubtaskKind.hard_reasoning.value, "prove the plan"))
    assert o.tier == Tier.cloud.value


def test_irreversible_action_is_gated_not_auto_run():
    r = EscalationRouter(ledger=CostLedger())  # no human_gate_fn => not approved
    o = r.route(Subtask(SubtaskKind.calendar_action.value, "book meeting", stakes="high"))
    assert o.tier == Tier.gate.value
    assert o.gate_required and o.gate_approved is None


def test_low_confidence_escalates():
    def shaky_local(t: Subtask) -> LocalResult:
        return LocalResult(text="unsure", confidence=0.3, tokens_in=300, tokens_out=80)

    r = EscalationRouter(local_fn=shaky_local, ledger=CostLedger())
    o = r.route(Subtask(SubtaskKind.summarize.value, "summarize"))
    assert o.tier == Tier.cloud.value and o.escalated
    assert o.attempts >= 2  # tried local (+retry) before escalating


def test_high_stakes_pulls_routine_to_cloud():
    r = EscalationRouter(ledger=CostLedger())
    o = r.route(Subtask(SubtaskKind.file_inspect.value, "inspect prod secret", stakes="high"))
    assert o.tier == Tier.cloud.value


def test_ledger_reports_savings():
    r = EscalationRouter(ledger=CostLedger())
    for kind in (SubtaskKind.search, SubtaskKind.memory_lookup, SubtaskKind.ci_check):
        r.route(Subtask(kind.value, "x"))
    r.route(Subtask(SubtaskKind.hard_reasoning.value, "y"))
    s = r.ledger.summary()
    assert s["calls"] == 4 and s["local_calls"] == 3 and s["cloud_calls"] == 1
    assert s["saved_usd"] > 0 and 0 < s["local_share_pct"] <= 100
