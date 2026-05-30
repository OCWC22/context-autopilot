"""CI/CD check: inspect pipeline configs + build/CI logs for failures, broken
steps, missing caching, and flaky retries."""

from __future__ import annotations

from .base import EngineeringCheck
from .evidence import Severity


class CICDCheck(EngineeringCheck):
    name = "cicd"
    globs = (
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
        ".gitlab-ci.yml",
        "*.circleci/config.yml",
        "ci/**/*.log",
        "ci/**/*.txt",
        "**/build.log",
    )
    prefilter = (
        r"\b(error|failed|failure|exit code [1-9]|cannot|not found|timed out|retry|retries)\b",
        r"\b(npm ERR!|FAILED|##\[error\]|process completed with exit code)\b",
    )
    query = (
        "You are a CI/CD reviewer. From this pipeline config or build log, list "
        "concrete failures, broken/missing steps, missing dependency caching, or "
        "flaky retries — one per line with the exact offending text. Reply 'none' "
        "if clean."
    )
    default_severity = Severity.high
