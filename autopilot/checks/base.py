"""Base class for the engineering-check subagents.

A check declares (a) what context it inspects (file globs under the repo) and
(b) what to grep for, then runs an RLM inspection and turns the stitched compact
answer into CheckEvidence. Subclasses override the declaration and, optionally,
the verdict logic. The heavy reading happens in the RLM sub-LM (local MLX); the
parent only ever sees the compact CheckEvidence.
"""

from __future__ import annotations

from pathlib import Path

from .evidence import CheckEvidence, Finding, Severity, Verdict
from .rlm_runtime import RLMInspector, SubLM, load_context


class EngineeringCheck:
    name: str = "base"
    # repo-relative globs of files/logs/configs/traces this check inspects
    globs: tuple[str, ...] = ()
    # regex patterns to prefilter the externalized context before any sub-call
    prefilter: tuple[str, ...] = ()
    # the question handed to the RLM sub-LM for each relevant slice
    query: str = "Report concrete problems in this content, one per line, with the exact offending text. If none, reply 'none'."
    # severity assigned to findings this check surfaces (subclasses may refine)
    default_severity: Severity = Severity.medium

    def __init__(self, sub_lm: SubLM, chunk_chars: int = 6000, max_subcalls: int = 24) -> None:
        self.inspector = RLMInspector(sub_lm, chunk_chars=chunk_chars, max_subcalls=max_subcalls)

    # --- overridable hooks ---

    def gather(self, repo: Path) -> list:
        paths: list[Path] = []
        for g in self.globs:
            paths.extend(sorted(repo.glob(g)))
        return load_context(paths)

    def verdict_for(self, findings: list[Finding]) -> str:
        if any(Severity(f.severity) in (Severity.high, Severity.critical) for f in findings):
            return Verdict.fail.value
        if findings:
            return Verdict.warn.value
        return Verdict.pass_.value

    def summarize(self, findings: list[Finding]) -> str:
        if not findings:
            return f"{self.name}: no issues found in inspected context."
        return f"{self.name}: {len(findings)} issue(s); top severity {max(f.severity for f in findings)}."

    # --- main entry ---

    def run(self, repo: Path, evidence_char_budget: int = 1200) -> CheckEvidence:
        context = self.gather(repo)
        if not context:
            return CheckEvidence(
                check=self.name,
                verdict=Verdict.unknown.value,
                confidence="low",
                summary=f"{self.name}: no matching context found ({', '.join(self.globs) or 'no globs'}).",
                notes=["no files matched this check's globs"],
            )
        res = self.inspector.inspect(self.query, context, prefilter=list(self.prefilter))
        findings = self._to_findings(res.slices)
        verdict = self.verdict_for(findings)
        confidence = "high" if not res.truncated and res.subcalls else "medium"
        summary = self.summarize(findings)[:evidence_char_budget]
        return CheckEvidence(
            check=self.name,
            verdict=verdict,
            confidence=confidence,
            summary=summary,
            findings=findings[:20],
            context_chars_seen=res.context_chars,
            evidence_chars_returned=len(summary) + sum(len(f.detail) + len(f.title) for f in findings[:20]),
            subcalls=res.subcalls,
            notes=(["RLM hit max_subcalls stopping cap"] if res.truncated else []),
        )

    def _to_findings(self, slices: list[tuple[str, str]]) -> list[Finding]:
        findings: list[Finding] = []
        for ref, ans in slices:
            for line in ans.splitlines():
                line = line.strip(" -•\t")
                if not line or line.lower() in ("none", "n/a"):
                    continue
                findings.append(
                    Finding(
                        title=line[:120],
                        severity=self._severity_for(line).value,
                        evidence_ref=ref,
                        detail=line[:200],
                    )
                )
        return findings

    def _severity_for(self, line: str) -> Severity:
        low = line.lower()
        if any(k in low for k in ("critical", "cve-", "rce", "secret leaked", "exposed key")):
            return Severity.critical
        if any(k in low for k in ("vulnerab", "high", "exception", "traceback", "failed", "denied")):
            return Severity.high
        if any(k in low for k in ("warn", "deprecat", "timeout", "flaky")):
            return Severity.medium
        return self.default_severity
