"""Core data types shared across the pipeline. Standard library only.

These mirror the real extractable shapes from Claude Code / Codex local logs
(RECEIPTS.md cluster 2): every tool call, Edit oldString/newString, and
structuredPatch is on disk as plaintext JSONL. `patch_accepted` is INFERRED
heuristically — there is no labeled accept/reject field.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    react_ui_edit = "react_ui_edit"
    typescript_fix = "typescript_fix"
    test_generation = "test_generation"
    api_scaffold = "api_scaffold"
    schema_migration = "schema_migration"
    architecture_refactor = "architecture_refactor"
    production_bug = "production_bug"
    security_change = "security_change"
    other = "other"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


@dataclass
class FileEdit:
    """One Edit tool result: a before/after on a single file."""

    file_path: str
    old_string: str
    new_string: str
    structured_patch: str = ""  # unified diff if available


@dataclass
class CodingTrace:
    """One coding interaction reconstructed from a session transcript."""

    id: str
    source: str  # claude_code | codex | git | demo
    session_id: str
    task_title: str
    task_type: str  # TaskType value
    user_prompt: str
    files_read: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    edits: list[FileEdit] = field(default_factory=list)
    patch_accepted: bool = False  # INFERRED, not labeled
    accept_confidence: float = 0.0  # how sure the heuristic is
    tests_passed: bool | None = None
    lint_passed: bool | None = None
    typecheck_passed: bool | None = None
    risk_level: str = RiskLevel.medium.value
    estimated_cost_usd: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryProfile:
    """Stable knowledge the model keeps relearning — retrieved before generation."""

    coding_preferences: list[str] = field(default_factory=list)
    repo_conventions: list[str] = field(default_factory=list)
    repeated_patterns: list[str] = field(default_factory=list)
    avoid_patterns: list[str] = field(default_factory=list)
    generated_by: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SFTExample:
    """Stage A supervision: an accepted diff turned into an instruction pair."""

    instruction: str
    memory_context: list[str]
    repo_context: list[str]
    accepted_patch: str
    rejected_patch: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalCheck:
    """A single verifiable check that can be executed in the sandbox."""

    kind: str  # tests | typecheck | lint | no_unrelated_files | no_unwanted_dep | follows_memory
    command: str = ""  # shell command, if executable
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class RLTask:
    """Stage B environment task: a prompt + repo context + the verifiable checks
    that define its reward. The env applies the model's patch and runs these."""

    id: str
    prompt: str
    task_type: str
    risk_level: str
    repo_context: list[str] = field(default_factory=list)
    memory_context: list[str] = field(default_factory=list)
    repo_snapshot: str = ""  # path to a checked-out repo state, if available
    checks: list[EvalCheck] = field(default_factory=list)
    reference_patch: str = ""  # the accepted diff, for offline credit assignment

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class RewardBreakdown:
    """Per-component reward for one model patch attempt."""

    total: float
    components: dict[str, float] = field(default_factory=dict)
    tests_pass: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
