"""PrimeIntellect `verifiers` Environment wrapping the sandbox + reward funcs.

This adapts the Stage B RL tasks (one proposed unified diff per task) into a
`verifiers` SingleTurnEnv so prime-rl / GRPO can train against verifiable
rewards (RECEIPTS.md cluster 6: accepted diffs are supervision, tests are
rewards; the rule-based / RLVR + GRPO recipe is established technique, not
marketing).

Honest framing carried over from RECEIPTS.md:
- The tests reward is kept BINARY on purpose. Pass-rate is a miscalibrated
  surrogate in critic-free RL (RECEIPTS.md cluster 6, arXiv 2605.02944), so the
  scalar reward here is `compute_reward(...).total`, which folds in the binary
  tests signal plus convention/penalty shaping — not a per-test pass fraction.
- Reward quality is bounded by test coverage; weak or flaky tests silently
  reward wrong code (RECEIPTS.md cluster 6 caveat). The sandbox runs whatever
  `test_cmd` the task/caller supplies; garbage in, garbage out.
- A solo repo yields far fewer clean fail-to-pass instances than the 19k-PR
  precedent, so this is convention/style adaptation under strong reward shaping,
  not new capability acquisition.

Heavy deps (`verifiers`, `datasets`) are imported lazily inside
`load_environment` so that `import autopilot.rewards.verifiers_env` (and the
CLI) never pulls them. The offline core it leans on
(`sandbox.run_checks`, `reward_funcs.compute_reward`) is stdlib-only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import DEFAULT
from ..types import EvalCheck, MemoryProfile, RLTask
from . import reward_funcs, sandbox

# Module-level registry: task id -> rehydrated RLTask. The verifiers dataset
# only carries the task id (in the "answer" column) so the reward function can
# look the full task back up without serializing EvalChecks into HF columns.
_TASK_REGISTRY: dict[str, RLTask] = {}

SYSTEM_PROMPT = (
    "You are a precise coding agent. You are given a task and repository "
    "context. Propose the smallest correct change as a SINGLE unified diff "
    "(git diff / `diff -u` format) and OUTPUT ONLY THAT DIFF.\n"
    "Rules:\n"
    "- Output must start with `diff --git` or `--- ` and contain `@@` hunks.\n"
    "- Do not include prose, explanations, or markdown outside the diff.\n"
    "- Edit only the files the task requires; do not touch unrelated files.\n"
    "- Do not add new dependencies unless explicitly asked.\n"
    "- Honor the stated coding preferences and repo conventions."
)

# Fenced-block extractor: ```diff ... ``` or plain ``` ... ```.
_FENCE_RE = re.compile(r"```(?:diff|patch|udiff)?\s*\n(.*?)```", re.DOTALL)
# A line that looks like the start of a real unified diff.
_DIFF_START_RE = re.compile(r"^(diff --git |--- |Index: )", re.MULTILINE)


def _rehydrate_task(raw: dict[str, Any]) -> RLTask:
    """Rebuild an RLTask (and its EvalCheck list) from a to_dict() record."""
    checks = [
        EvalCheck(
            kind=c.get("kind", ""),
            command=c.get("command", ""),
            args=dict(c.get("args", {})),
        )
        for c in raw.get("checks", [])
    ]
    return RLTask(
        id=raw["id"],
        prompt=raw.get("prompt", ""),
        task_type=raw.get("task_type", ""),
        risk_level=raw.get("risk_level", ""),
        repo_context=list(raw.get("repo_context", [])),
        memory_context=list(raw.get("memory_context", [])),
        repo_snapshot=raw.get("repo_snapshot", ""),
        checks=checks,
        reference_patch=raw.get("reference_patch", ""),
    )


def _load_tasks(dataset_path: Path) -> list[RLTask]:
    """Read rl_train.jsonl from dataset_path and rehydrate each line."""
    rl_file = dataset_path / "rl_train.jsonl"
    if not rl_file.exists():
        raise FileNotFoundError(
            f"RL task file not found: {rl_file}. Run `autopilot build` first."
        )
    tasks: list[RLTask] = []
    for line in rl_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        tasks.append(_rehydrate_task(json.loads(line)))
    return tasks


def _load_memory(dataset_path: Path) -> MemoryProfile | None:
    """Load a MemoryProfile from dataset_path/../memory.json or
    dataset_path/memory.json if present, else return None."""
    for candidate in (dataset_path.parent / "memory.json", dataset_path / "memory.json"):
        if candidate.exists():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            return MemoryProfile(
                coding_preferences=list(raw.get("coding_preferences", [])),
                repo_conventions=list(raw.get("repo_conventions", [])),
                repeated_patterns=list(raw.get("repeated_patterns", [])),
                avoid_patterns=list(raw.get("avoid_patterns", [])),
                generated_by=raw.get("generated_by", "heuristic"),
            )
    return None


def _render_user_prompt(task: RLTask) -> str:
    """Embed the task prompt + memory_context + repo_context into one user turn."""
    parts: list[str] = [task.prompt.strip()]
    if task.memory_context:
        mem = "\n".join(f"- {m}" for m in task.memory_context)
        parts.append(f"\nKnown preferences / conventions:\n{mem}")
    if task.repo_context:
        ctx = "\n\n".join(task.repo_context)
        parts.append(f"\nRepository context:\n{ctx}")
    parts.append("\nReturn ONLY a unified diff.")
    return "\n".join(parts)


def extract_diff(completion: Any) -> str:
    """Pull the unified-diff text out of a model completion.

    Accepts a raw string, or a chat-style list of {role, content} messages
    (verifiers may hand either depending on env type); returns the best-effort
    diff body. Prefers a fenced ```diff block, then a region starting at the
    first real diff header, then the whole string.
    """
    text = _completion_to_text(completion)
    if not text:
        return ""

    fenced = _FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip("\n")

    m = _DIFF_START_RE.search(text)
    if m:
        return text[m.start():].strip("\n")

    return text.strip()


def _completion_to_text(completion: Any) -> str:
    """Normalize a verifiers completion into a plain string."""
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list):
        chunks: list[str] = []
        for msg in completion:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    chunks.append(content)
                elif isinstance(content, list):
                    for piece in content:
                        if isinstance(piece, dict) and isinstance(piece.get("text"), str):
                            chunks.append(piece["text"])
            elif isinstance(msg, str):
                chunks.append(msg)
        return "\n".join(chunks)
    if isinstance(completion, dict):
        content = completion.get("content", "")
        return content if isinstance(content, str) else str(content)
    return str(completion)


def _task_for(answer: Any) -> RLTask | None:
    """Resolve the RLTask for a given verifiers `answer` (the task id)."""
    if isinstance(answer, str):
        return _TASK_REGISTRY.get(answer)
    return None


def load_environment(
    dataset_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    test_cmd: str = "",
    typecheck_cmd: str = "",
    lint_cmd: str = "",
) -> "vf.Environment":  # noqa: F821 - vf imported lazily below
    """Build the verifiers SingleTurnEnv for GRPO / prime-rl.

    Args:
        dataset_path: directory holding rl_train.jsonl (DEFAULT.paths.dataset if
            None). memory.json is looked up next to it.
        repo_root: repository the patches are applied against in the sandbox.
            If None, sandbox.run_checks copies/uses an empty/temp root and the
            tests typically will not run — pass a real repo for live reward.
        test_cmd / typecheck_cmd / lint_cmd: shell commands the sandbox runs to
            produce the verifiable signals (RECEIPTS.md cluster 6: tests are the
            correctness oracle; reward quality is bounded by their coverage).

    Returns:
        A `vf.SingleTurnEnv` whose Rubric scalar reward is
        `compute_reward(run_checks(...), task).total`.
    """
    import verifiers as vf
    from datasets import Dataset

    ds_path = Path(dataset_path) if dataset_path is not None else DEFAULT.paths.dataset
    repo_path = Path(repo_root) if repo_root is not None else None

    tasks = _load_tasks(ds_path)
    memory = _load_memory(ds_path)

    _TASK_REGISTRY.clear()
    rows: list[dict[str, Any]] = []
    for task in tasks:
        _TASK_REGISTRY[task.id] = task
        rows.append(
            {
                "prompt": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _render_user_prompt(task)},
                ],
                "answer": task.id,  # lookup key into _TASK_REGISTRY
                "info": {"task_id": task.id, "task_type": task.task_type},
            }
        )
    dataset = Dataset.from_list(rows)

    def _outcome(completion: Any, answer: Any) -> tuple[reward_funcs.PatchOutcome, RLTask | None]:
        task = _task_for(answer)
        if task is None:
            return reward_funcs.PatchOutcome(applied=False, build_ok=True), None
        diff_text = extract_diff(completion)
        outcome = sandbox.run_checks(
            diff_text,
            task,
            repo_path,
            test_cmd=test_cmd,
            typecheck_cmd=typecheck_cmd,
            lint_cmd=lint_cmd,
            memory=memory,
        )
        return outcome, task

    def reward_patch(completion: Any, answer: Any, **kwargs: Any) -> float:
        """Primary scalar reward = compute_reward(...).total (RECEIPTS.md c6)."""
        outcome, task = _outcome(completion, answer)
        if task is None:
            return 0.0
        return float(reward_funcs.compute_reward(outcome, task).total)

    def metric_tests_pass(completion: Any, answer: Any, **kwargs: Any) -> float:
        """BINARY tests signal for logging only (kept binary per cluster 6)."""
        outcome, _task = _outcome(completion, answer)
        return 1.0 if (outcome.tests_ran and outcome.tests_passed) else 0.0

    def metric_typecheck(completion: Any, answer: Any, **kwargs: Any) -> float:
        outcome, _task = _outcome(completion, answer)
        return 1.0 if outcome.typecheck_passed else 0.0

    def metric_lint(completion: Any, answer: Any, **kwargs: Any) -> float:
        outcome, _task = _outcome(completion, answer)
        return 1.0 if outcome.lint_passed else 0.0

    rubric = vf.Rubric(
        funcs=[reward_patch, metric_tests_pass, metric_typecheck, metric_lint],
        # Only the patch reward shapes the gradient; the rest are logged at 0
        # weight so GRPO advantages come from compute_reward(...).total alone.
        weights=[1.0, 0.0, 0.0, 0.0],
    )

    return vf.SingleTurnEnv(
        dataset=dataset,
        system_prompt=SYSTEM_PROMPT,
        rubric=rubric,
    )


if __name__ == "__main__":
    # GPU-free smoke check: load and count tasks, no model / no verifiers needed.
    ds = DEFAULT.paths.dataset
    try:
        _tasks = _load_tasks(ds)
    except FileNotFoundError as exc:
        print(f"[verifiers_env] {exc}")
    else:
        _mem = _load_memory(ds)
        print(f"[verifiers_env] dataset_path = {ds}")
        print(f"[verifiers_env] loaded {len(_tasks)} RL tasks from rl_train.jsonl")
        print(f"[verifiers_env] memory profile present: {_mem is not None}")
        if _tasks:
            sample = _tasks[0]
            print(
                f"[verifiers_env] sample task id={sample.id!r} "
                f"type={sample.task_type!r} checks={len(sample.checks)}"
            )
