"""Compact evidence types returned by each engineering-check subagent.

The whole point of the RLM layer is that a subagent inspects a large amount of
context (logs, configs, lockfiles, scan output) but returns only a small,
structured, citation-backed summary to the parent — so the parent's context
stays tiny no matter how big the inputs were.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Verdict(str, Enum):
    pass_ = "pass"
    warn = "warn"
    fail = "fail"
    unknown = "unknown"


_SEV_ORDER = {Severity.info: 0, Severity.low: 1, Severity.medium: 2, Severity.high: 3, Severity.critical: 4}


@dataclass
class Finding:
    """One issue, with a pointer back to where the evidence lives (not the full
    blob — a path + locator the parent can re-open if it wants)."""

    title: str
    severity: str  # Severity value
    evidence_ref: str  # e.g. "ci/logs/build.txt:142" or "package-lock.json#left-pad"
    detail: str = ""  # <= ~200 chars; the compact takeaway, not the raw log

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckEvidence:
    """What a subagent returns to the parent. Deliberately small."""

    check: str
    verdict: str  # Verdict value
    confidence: str  # high | medium | low
    summary: str  # 1-3 sentences
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    # provenance / efficiency accounting
    context_chars_seen: int = 0  # how much raw context the RLM externalized
    evidence_chars_returned: int = 0  # how little came back to the parent
    subcalls: int = 0  # number of sub-LM calls the RLM made
    notes: list[str] = field(default_factory=list)

    @property
    def top_severity(self) -> str:
        if not self.findings:
            return Severity.info.value
        return max((f.severity for f in self.findings), key=lambda s: _SEV_ORDER.get(Severity(s), 0))

    @property
    def compression_ratio(self) -> float:
        if self.evidence_chars_returned <= 0:
            return 0.0
        return round(self.context_chars_seen / self.evidence_chars_returned, 1)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["top_severity"] = self.top_severity
        d["compression_ratio"] = self.compression_ratio
        return d


def gate_from_evidence(evidences: list[CheckEvidence]) -> dict[str, Any]:
    """Aggregate the six checks into one deployment-gate decision. Deterministic
    (the parent LLM can override with judgment, but this is the floor)."""
    any_fail = any(e.verdict == Verdict.fail.value for e in evidences)
    any_warn = any(e.verdict == Verdict.warn.value for e in evidences)
    has_critical = any(
        Severity(f.severity) in (Severity.high, Severity.critical)
        for e in evidences
        for f in e.findings
    )
    if any_fail or has_critical:
        gate = Verdict.fail.value
    elif any_warn:
        gate = Verdict.warn.value
    else:
        gate = Verdict.pass_.value
    return {
        "gate": gate,
        "checks": {e.check: e.verdict for e in evidences},
        "total_findings": sum(len(e.findings) for e in evidences),
        "total_context_chars": sum(e.context_chars_seen for e in evidences),
        "total_evidence_chars": sum(e.evidence_chars_returned for e in evidences),
        "total_subcalls": sum(e.subcalls for e in evidences),
    }
