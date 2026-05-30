"""Heuristic task-type and risk classification from prompt text + touched files.

Deliberately rule-based and transparent (not a model) so the routing decision
is auditable. Risk defaults conservative: code generation is the worst routing
case in the literature, so anything ambiguous leans toward fallback.
"""

from __future__ import annotations

import re

from ..types import RiskLevel, TaskType

_PATTERNS: list[tuple[TaskType, list[str]]] = [
    (TaskType.security_change, [r"\bauth\b", r"password", r"secret", r"token", r"crypto", r"permission", r"rbac", r"cors"]),
    (TaskType.schema_migration, [r"migration", r"schema", r"alter table", r"drizzle", r"prisma", r"\bddl\b", r"supabase migration"]),
    (TaskType.production_bug, [r"prod(uction)? (bug|incident|outage)", r"hotfix", r"500 error", r"crash", r"regression"]),
    (TaskType.architecture_refactor, [r"refactor", r"re-?architect", r"restructure", r"extract (module|service)", r"rewrite"]),
    (TaskType.test_generation, [r"\btest(s|ing)?\b", r"unit test", r"spec", r"coverage", r"jest", r"pytest", r"vitest"]),
    (TaskType.typescript_fix, [r"type error", r"\btsc\b", r"typescript", r"\btype(s|d)?\b", r"mypy", r"pyright"]),
    (TaskType.api_scaffold, [r"api route", r"endpoint", r"handler", r"scaffold", r"\bcrud\b", r"controller"]),
    (TaskType.react_ui_edit, [r"component", r"\bui\b", r"tailwind", r"button", r"page", r"loading state", r"error state", r"css", r"react"]),
]

_FILE_HINTS: list[tuple[TaskType, list[str]]] = [
    (TaskType.react_ui_edit, [".tsx", ".jsx", ".css", "components/"]),
    (TaskType.test_generation, ["test", "spec", "__tests__"]),
    (TaskType.schema_migration, ["migration", "schema", ".sql"]),
]


def classify_task_type(prompt: str, files_touched: list[str]) -> TaskType:
    text = (prompt or "").lower()
    for ttype, pats in _PATTERNS:
        if any(re.search(p, text) for p in pats):
            return ttype
    files = " ".join(files_touched).lower()
    for ttype, hints in _FILE_HINTS:
        if any(h in files for h in hints):
            return ttype
    return TaskType.other


def infer_risk(task_type: str, files_touched: list[str]) -> RiskLevel:
    high = {
        TaskType.security_change.value,
        TaskType.schema_migration.value,
        TaskType.production_bug.value,
    }
    medium = {
        TaskType.architecture_refactor.value,
        TaskType.other.value,
    }
    if task_type in high:
        return RiskLevel.high
    # Touching many files or config/infra paths raises risk.
    risky_paths = (".env", "dockerfile", "ci", ".github/", "infra", "terraform")
    if any(any(rp in f.lower() for rp in risky_paths) for f in files_touched):
        return RiskLevel.high
    if len(files_touched) > 6:
        return RiskLevel.medium
    if task_type in medium:
        return RiskLevel.medium
    return RiskLevel.low
