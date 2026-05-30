"""Code-quality check: inspect linter/type-checker output and source for
complexity smells, dead code, and style violations."""

from __future__ import annotations

from .base import EngineeringCheck
from .evidence import Severity


class CodeQualityCheck(EngineeringCheck):
    name = "code_quality"
    globs = (
        "**/eslint*.json",
        "**/ruff*.txt",
        "**/*lint*.log",
        "**/tsc*.log",
        "**/mypy*.txt",
        "**/*.py",
        "**/*.ts",
        "**/*.tsx",
    )
    prefilter = (
        r"\b(error|warning|TODO|FIXME|HACK|XXX|deprecated)\b",
        r"\b(any\b|# type: ignore|@ts-ignore|eslint-disable|noqa)\b",
        r"\b(complexity|too many|unused|unreachable|redefinition|shadow)\b",
    )
    query = (
        "You are a code-quality reviewer. From this linter/type-checker output or "
        "source, list concrete quality issues — type errors, lint violations, dead/"
        "unused code, suppressed checks (ts-ignore/noqa/any), or high complexity — "
        "one per line with the exact offending text. Reply 'none' if clean."
    )
    default_severity = Severity.low
