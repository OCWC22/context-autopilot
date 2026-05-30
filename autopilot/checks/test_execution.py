"""Test-execution check: inspect test runner output / JUnit XML / coverage for
failures, errors, skips, and low coverage."""

from __future__ import annotations

from .base import EngineeringCheck
from .evidence import Severity, Verdict, Finding


class TestExecutionCheck(EngineeringCheck):
    name = "test_execution"
    globs = (
        "**/pytest*.log",
        "**/test*.log",
        "**/junit*.xml",
        "**/*test-results*.xml",
        "**/coverage*.xml",
        "**/coverage*.txt",
        "**/jest*.log",
        "**/vitest*.log",
    )
    prefilter = (
        r"\b(FAILED|ERROR|failed|errors?|assert|Traceback|exception)\b",
        r"\b(\d+ failed|\d+ error|\d+ skipped|xfail|flaky)\b",
        r"\b(coverage|TOTAL|missing|stmts|miss)\b",
        r'<(failure|error|skipped)\b',
    )
    query = (
        "You are a test reviewer. From this test runner output / JUnit XML / "
        "coverage report, list concrete problems — failing or erroring tests "
        "(with names), skipped/xfail tests, and coverage below ~80% — one per line "
        "with the exact offending text. Reply 'none' if all green."
    )
    default_severity = Severity.high

    def verdict_for(self, findings: list[Finding]) -> str:
        # Any failing/erroring test fails the gate; skips/coverage warn.
        if any(Severity(f.severity) in (Severity.high, Severity.critical) for f in findings):
            return Verdict.fail.value
        return Verdict.warn.value if findings else Verdict.pass_.value
