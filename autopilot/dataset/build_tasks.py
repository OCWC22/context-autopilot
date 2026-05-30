"""Stage B: turn traces into verifiable RL/eval tasks.

Each task carries the prompt + context and the set of executable checks that
define its reward. The verifiers environment applies the model's patch to a
repo snapshot and runs these checks. Where a repo snapshot isn't available the
task still works as an offline eval against the reference patch.

Reward signal precedent (RECEIPTS.md cluster 6): binary tests-pass is the
primary oracle (SWE-bench / CodeRL / RLEF / SWE-RL). Auxiliary checks
(typecheck, lint, unrelated-files, unwanted-dep, follows-memory) shape it.
"""

from __future__ import annotations

from ..types import CodingTrace, EvalCheck, MemoryProfile, RLTask


def _default_checks(trace: CodingTrace) -> list[EvalCheck]:
    checks: list[EvalCheck] = []
    # Primary: tests. Command is a placeholder the runner fills per-repo.
    checks.append(EvalCheck(kind="tests", command="{TEST_CMD}"))
    checks.append(EvalCheck(kind="typecheck", command="{TYPECHECK_CMD}"))
    checks.append(EvalCheck(kind="lint", command="{LINT_CMD}"))
    # Verifiable static checks that need no test suite:
    checks.append(
        EvalCheck(
            kind="no_unrelated_files",
            args={"allowed_files": list(trace.files_touched)},
        )
    )
    checks.append(EvalCheck(kind="no_unwanted_dep", args={"manifest_globs": ["package.json", "pyproject.toml", "requirements*.txt"]}))
    checks.append(EvalCheck(kind="follows_memory", args={}))
    return checks


def build_tasks(
    traces: list[CodingTrace],
    memory: MemoryProfile,
    only_personal_ok: tuple[str, ...] | None = None,
) -> list[RLTask]:
    mem = memory.coding_preferences[:4] + memory.repo_conventions[:4] + memory.avoid_patterns[:2]
    tasks: list[RLTask] = []
    for t in traces:
        if only_personal_ok and t.task_type not in only_personal_ok:
            continue
        ref_patch = "\n\n".join(
            (e.structured_patch or e.new_string) for e in t.edits if (e.structured_patch or e.new_string)
        )
        tasks.append(
            RLTask(
                id=t.id,
                prompt=t.user_prompt,
                task_type=t.task_type,
                risk_level=t.risk_level,
                repo_context=[f"Touched: {f}" for f in t.files_touched[:6]],
                memory_context=mem,
                checks=_default_checks(t),
                reference_patch=ref_patch,
            )
        )
    return tasks
