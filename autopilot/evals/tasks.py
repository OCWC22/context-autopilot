"""Seeded benchmark tasks with gold context files (ContextBench-style).

Each task seeds a small repo with a real bug + a real failing test + distractor
files, and declares the GOLD files needed to solve it. The harness measures
whether each config retrieves those gold files and at what token cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalTask:
    id: str
    kind: str                      # "fix" | "qa"
    prompt: str
    repo: str
    gold_files: list[str] = field(default_factory=list)
    test_cmd: str = ""             # for kind="fix": command that passes once fixed
    fix: tuple[str, str, str] | None = None  # (relpath, old, new) seed fix to verify success


_FILES = {
    # the file with the bug (gold)
    "calc.py": "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n",
    # the failing test (gold)
    "test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    # distractors (should NOT be retrieved for the add bug)
    "utils.py": "def slugify(s):\n    return s.lower().replace(' ', '-')\n",
    "models.py": "class User:\n    def __init__(self, name):\n        self.name = name\n",
    "api.py": "def handler(req):\n    return {'ok': True}\n",
    "README.md": "# Demo project\n\nA tiny package for the autopilot eval harness.\n",
    "config.toml": "[tool]\nname = 'demo'\n",
    # project rules the local layer can load instead of relearning
    ".autopilot/SKILL.md": (
        "---\nname: demo-repo-rules\ndescription: project rules\n---\n\n"
        "# Demo repo rules\n- Tests live in test_*.py and run with `pytest -q`.\n"
        "- Arithmetic helpers live in calc.py.\n- Keep changes minimal and type-safe.\n"
    ),
}


def _large_distractors() -> dict[str, str]:
    """Big, irrelevant files — a realistic repo the baseline would dump wholesale
    into the frontier prompt, but which selective retrieval correctly skips."""
    out: dict[str, str] = {}
    for i in range(6):
        out[f"vendor/module_{i}.py"] = "\n".join(
            f"def feature_{i}_{j}(x, y, z):\n"
            f"    # unrelated business logic block {i}.{j}\n"
            f"    result = (x * {j}) + (y - {i}) + z\n"
            f"    return result if result > 0 else 0\n"
            for j in range(40)
        )
    out["CHANGELOG.md"] = "# Changelog\n\n" + "\n".join(f"- 1.0.{k}: unrelated change {k}" for k in range(400))
    return out


def seed_eval_repo(base: Path) -> list[EvalTask]:
    """Write the seed repo under `base` and return the tasks pointing at it."""
    repo = Path(base) / "eval_repo"
    for rel, content in {**_FILES, **_large_distractors()}.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    repo_s = str(repo)
    return [
        EvalTask(
            id="fix-add-bug",
            kind="fix",
            prompt="Fix the failing test for the add function in calc.py so add(2,3)==5",
            repo=repo_s,
            gold_files=["calc.py", "test_calc.py"],
            test_cmd="python3 -m pytest -q test_calc.py",
            fix=("calc.py", "return a - b", "return a + b"),
        ),
        EvalTask(
            id="qa-where-add",
            kind="qa",
            prompt="Which file defines the add function and what does it return?",
            repo=repo_s,
            gold_files=["calc.py"],
        ),
    ]


def bundled_tasks(base: Path) -> list[EvalTask]:
    return seed_eval_repo(base)
