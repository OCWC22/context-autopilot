"""Security check: inspect source + scanner output + configs for hardcoded
secrets, injection, unsafe calls, and known CVEs."""

from __future__ import annotations

from .base import EngineeringCheck
from .evidence import Severity, Verdict, Finding


class SecurityCheck(EngineeringCheck):
    name = "security"
    globs = (
        "**/*.py",
        "**/*.ts",
        "**/*.js",
        "**/*.env*",
        "security/**/*",
        "**/semgrep*.json",
        "**/trivy*.json",
        "**/bandit*.txt",
    )
    prefilter = (
        r"\b(api[_-]?key|secret|password|token|private[_-]?key|aws_secret)\b\s*[=:]",
        r"\b(eval\(|exec\(|os\.system|subprocess\.(call|run|Popen)\(|pickle\.loads|yaml\.load\()",
        r"\b(cve-\d{4}-\d+|sql injection|xss|rce|insecure|hardcoded)\b",
        r"verify\s*=\s*False|ssl[._]verify\s*=\s*false|InsecureRequestWarning",
    )
    query = (
        "You are a security reviewer. From this code or scanner output, list "
        "concrete security issues — hardcoded secrets/keys, injection (eval/exec/"
        "os.system/SQL), disabled TLS verification, unsafe deserialization, or "
        "named CVEs — one per line with the exact offending text. Reply 'none' if "
        "clean."
    )
    default_severity = Severity.high

    def verdict_for(self, findings: list[Finding]) -> str:
        # Security is strict: any high/critical fails the gate.
        if any(Severity(f.severity) in (Severity.high, Severity.critical) for f in findings):
            return Verdict.fail.value
        return Verdict.warn.value if findings else Verdict.pass_.value
