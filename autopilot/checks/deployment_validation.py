"""Deployment-validation check: inspect Dockerfiles, k8s/compose manifests, IaC,
and deploy logs for misconfig, missing health checks, secrets in env, and
risky settings."""

from __future__ import annotations

from .base import EngineeringCheck
from .evidence import Severity


class DeploymentValidationCheck(EngineeringCheck):
    name = "deployment_validation"
    globs = (
        "**/Dockerfile*",
        "**/docker-compose*.yml",
        "**/k8s/**/*.yaml",
        "**/k8s/**/*.yml",
        "**/*.tf",
        "**/helm/**/*.yaml",
        "**/deploy*.log",
        "**/*.modal.py",
        "modal_app.py",
    )
    prefilter = (
        r"\b(latest|:latest|privileged|root|0\.0\.0\.0|allowPrivilegeEscalation)\b",
        r"\b(env|ENV|secret|password|api[_-]?key)\b\s*[:=]",
        r"\b(livenessProbe|readinessProbe|healthcheck|resources|limits|replicas)\b",
        r"\b(error|failed|rollback|crashloop|imagepullbackoff|unhealthy)\b",
    )
    query = (
        "You are a deployment reviewer. From this Dockerfile / k8s / compose / IaC "
        "manifest or deploy log, list concrete deployment risks — :latest tags, "
        "running as root / privileged, secrets in plaintext env, missing health "
        "checks or resource limits, 0.0.0.0 binds, or failed/rollback events — one "
        "per line with the exact offending text. Reply 'none' if clean."
    )
    default_severity = Severity.medium
