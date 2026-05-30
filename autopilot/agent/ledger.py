"""Cost ledger: tally local vs cloud subagent calls and compute $ saved vs an
all-frontier baseline. Prices are USD per 1M tokens (RECEIPTS.md / v2).

The point: make the hidden inference bill visible. Every local call is $0; the
ledger reports what the same work would have cost if every subtask had gone to
the frontier model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# USD per 1M tokens (input, output). Local = on-device MLX = $0.
PRICES: dict[str, tuple[float, float]] = {
    "local": (0.0, 0.0),                 # MLX on-device
    "claude-opus-4-8": (5.0, 25.0),      # frontier
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "glm-5.1": (0.95, 3.15),             # Z.ai (teacher / cheap-cloud escalation)
}

# The model the "all-frontier" baseline assumes every subtask would have used.
BASELINE_FRONTIER = "claude-sonnet-4-6"


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model, PRICES[BASELINE_FRONTIER])
    return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout


@dataclass
class CallRecord:
    kind: str
    tier: str          # "local" | "cloud"
    model: str
    tokens_in: int
    tokens_out: int
    escalated: bool = False

    @property
    def cost(self) -> float:
        return cost_usd(self.model, self.tokens_in, self.tokens_out)


@dataclass
class CostLedger:
    records: list[CallRecord] = field(default_factory=list)
    baseline_model: str = BASELINE_FRONTIER

    def record(self, kind: str, tier: str, model: str, tokens_in: int, tokens_out: int, escalated: bool = False) -> None:
        self.records.append(CallRecord(kind, tier, model, tokens_in, tokens_out, escalated))

    @property
    def actual_cost(self) -> float:
        return round(sum(r.cost for r in self.records), 6)

    @property
    def baseline_cost(self) -> float:
        """What it would have cost if every call went to the frontier model."""
        return round(
            sum(cost_usd(self.baseline_model, r.tokens_in, r.tokens_out) for r in self.records),
            6,
        )

    @property
    def saved(self) -> float:
        return round(self.baseline_cost - self.actual_cost, 6)

    @property
    def saved_pct(self) -> float:
        b = self.baseline_cost
        return round(100 * self.saved / b, 1) if b > 0 else 0.0

    def summary(self) -> dict:
        local = [r for r in self.records if r.tier == "local"]
        cloud = [r for r in self.records if r.tier == "cloud"]
        return {
            "calls": len(self.records),
            "local_calls": len(local),
            "cloud_calls": len(cloud),
            "escalations": sum(1 for r in self.records if r.escalated),
            "local_share_pct": round(100 * len(local) / len(self.records), 1) if self.records else 0.0,
            "actual_cost_usd": self.actual_cost,
            "all_frontier_baseline_usd": self.baseline_cost,
            "saved_usd": self.saved,
            "saved_pct": self.saved_pct,
            "baseline_model": self.baseline_model,
        }
