"""Pure, standard-library reward functions.

Each takes a `PatchOutcome` (the result of applying a model patch in the sandbox
and running the checks) plus the task, and returns a float. `compute_reward`
combines them with the configured weights into a RewardBreakdown.

Design notes from the research (RECEIPTS.md cluster 6):
- Binary tests-pass is the primary verifiable oracle; we keep it binary rather
  than pass-rate because pass-rate is a miscalibrated surrogate in critic-free
  RL (arXiv 2605.02944).
- Auxiliary checks are verifiable (no learned reward model => no reward hacking
  from a neural RM).
- `follows_memory` is a soft, rule-checkable signal (no banned deps, respects
  avoid-patterns), NOT a model judge, to stay verifiable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import RewardWeights
from ..types import RLTask, RewardBreakdown


@dataclass
class PatchOutcome:
    """Result of applying a candidate patch and running checks in the sandbox."""

    applied: bool = False
    build_ok: bool = True
    tests_passed: bool = False
    tests_ran: bool = False
    typecheck_passed: bool | None = None
    lint_passed: bool | None = None
    files_changed: list[str] = field(default_factory=list)
    added_dependencies: list[str] = field(default_factory=list)
    diff_lines: int = 0
    reference_diff_lines: int = 0
    violated_preferences: list[str] = field(default_factory=list)


# --- individual reward terms (each returns a float in a small range) ---

def r_tests(o: PatchOutcome) -> float:
    return 1.0 if (o.tests_ran and o.tests_passed) else 0.0


def r_typecheck(o: PatchOutcome) -> float:
    return 1.0 if o.typecheck_passed else 0.0


def r_lint(o: PatchOutcome) -> float:
    return 1.0 if o.lint_passed else 0.0


def r_minimal_diff(o: PatchOutcome) -> float:
    """Reward staying close to the reference patch size. 1.0 if within 1.5x."""
    if o.reference_diff_lines <= 0:
        return 1.0 if o.diff_lines <= 60 else 0.0
    ratio = o.diff_lines / max(1, o.reference_diff_lines)
    return 1.0 if ratio <= 1.5 else max(0.0, 1.0 - (ratio - 1.5))


def r_follows_memory(o: PatchOutcome) -> float:
    return 0.0 if o.violated_preferences else 1.0


def p_build_breaks(o: PatchOutcome) -> float:
    return 1.0 if (o.applied and not o.build_ok) else 0.0


def p_unrelated_files(o: PatchOutcome, task: RLTask) -> float:
    allowed = {
        a
        for c in task.checks
        if c.kind == "no_unrelated_files"
        for a in c.args.get("allowed_files", [])
    }
    if not allowed:
        return 0.0
    extra = [f for f in o.files_changed if f not in allowed]
    return 1.0 if extra else 0.0


def p_unwanted_dep(o: PatchOutcome) -> float:
    return 1.0 if o.added_dependencies else 0.0


def p_violates_preference(o: PatchOutcome) -> float:
    return 1.0 if o.violated_preferences else 0.0


def compute_reward(
    outcome: PatchOutcome,
    task: RLTask,
    weights: RewardWeights | None = None,
) -> RewardBreakdown:
    w = weights or RewardWeights()
    comps: dict[str, float] = {}

    comps["tests_pass"] = w.tests_pass * r_tests(outcome)
    comps["typecheck_pass"] = w.typecheck_pass * r_typecheck(outcome)
    comps["lint_pass"] = w.lint_pass * r_lint(outcome)
    comps["minimal_diff"] = w.minimal_diff * r_minimal_diff(outcome)
    comps["follows_memory"] = w.follows_memory * r_follows_memory(outcome)
    # penalties (weights are negative)
    comps["build_breaks"] = w.build_breaks * p_build_breaks(outcome)
    comps["edits_unrelated_files"] = w.edits_unrelated_files * p_unrelated_files(outcome, task)
    comps["adds_unwanted_dependency"] = w.adds_unwanted_dependency * p_unwanted_dep(outcome)
    comps["violates_preference"] = w.violates_preference * p_violates_preference(outcome)

    total = round(sum(comps.values()), 4)
    notes: list[str] = []
    if not outcome.tests_ran:
        notes.append("no test command available — tests reward is 0 (weak-coverage risk)")
    if outcome.applied and not outcome.build_ok:
        notes.append("patch broke the build")
    return RewardBreakdown(
        total=total,
        components=comps,
        tests_pass=bool(outcome.tests_ran and outcome.tests_passed),
        notes=notes,
    )


def reward_to_scalar(outcome: PatchOutcome, task: RLTask, weights: RewardWeights | None = None) -> float:
    """Convenience for GRPO reward_funcs: returns just the scalar total."""
    return compute_reward(outcome, task, weights).total
