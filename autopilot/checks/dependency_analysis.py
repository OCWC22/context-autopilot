"""Dependency-analysis check: inspect manifests, lockfiles, and audit output for
vulnerable, outdated, unpinned, or unexpected dependencies."""

from __future__ import annotations

from .base import EngineeringCheck
from .evidence import Severity


class DependencyAnalysisCheck(EngineeringCheck):
    name = "dependency_analysis"
    globs = (
        "**/package.json",
        "**/package-lock.json",
        "**/pnpm-lock.yaml",
        "**/yarn.lock",
        "**/requirements*.txt",
        "**/pyproject.toml",
        "**/poetry.lock",
        "**/*npm-audit*.json",
        "**/*pip-audit*.json",
        "**/Cargo.lock",
        "**/go.sum",
    )
    prefilter = (
        r"\b(vulnerab|advisory|GHSA-|CVE-|critical|high severity|deprecated)\b",
        r'"?(version|severity)"?\s*[:=]',
        r"[><~^]=?\s*\d|\*|latest",  # unpinned / loose version specifiers
    )
    query = (
        "You are a dependency reviewer. From this manifest, lockfile, or audit "
        "report, list concrete dependency risks — known vulnerabilities (CVE/GHSA "
        "with severity), unpinned or wildcard versions, deprecated packages, or "
        "suspicious/unexpected additions — one per line with the package and exact "
        "text. Reply 'none' if clean."
    )
    default_severity = Severity.medium
