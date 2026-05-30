"""Apply a candidate patch to a throwaway copy of a repo and run the verifiable
checks. Standard library only (subprocess + tempfile + shutil).

This is the executable backbone of "your tests are rewards": the model proposes
a unified diff, we apply it in an isolated copy, run typecheck/lint/tests, and
report a PatchOutcome the reward functions score.

Safety: runs in a temp copy, never the live repo; commands are caller-provided
and time-limited. For untrusted code this should run inside a container — see
serve/modal_app.py for the sandboxed-on-Modal path.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..types import MemoryProfile, RLTask
from .reward_funcs import PatchOutcome


def _run(cmd: str, cwd: Path, timeout: int = 120) -> tuple[bool, str]:
    if not cmd or cmd.startswith("{"):  # unfilled placeholder like {TEST_CMD}
        return False, "no command"
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except OSError as e:
        return False, str(e)


def _apply_patch(diff_text: str, repo: Path) -> bool:
    """Try git apply, then patch(1). Returns True on success."""
    if not diff_text.strip():
        return False
    patch_file = repo / ".autopilot_candidate.diff"
    patch_file.write_text(diff_text)
    for cmd in ("git apply --whitespace=nowarn", "patch -p1 -i"):
        ok, _ = _run(f"{cmd} {patch_file.name}", repo, timeout=30)
        if ok:
            patch_file.unlink(missing_ok=True)
            return True
    patch_file.unlink(missing_ok=True)
    return False


def _changed_files(repo: Path) -> list[str]:
    ok, out = _run("git diff --name-only", repo, timeout=20)
    if not ok:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _added_dependencies(repo: Path, manifest_globs: list[str]) -> list[str]:
    """Heuristic: a manifest changed and the diff has added dependency lines."""
    added: list[str] = []
    for glob in manifest_globs:
        for manifest in repo.glob(glob):
            ok, out = _run(f"git diff -- {manifest.name}", repo, timeout=20)
            if ok and out:
                for line in out.splitlines():
                    if line.startswith("+") and not line.startswith("+++"):
                        s = line[1:].strip()
                        # crude dependency-line detector
                        if (":" in s or "==" in s or '"' in s) and len(s) < 120:
                            added.append(s)
    return added


def _check_preferences(diff_text: str, memory: MemoryProfile | None) -> list[str]:
    if not memory:
        return []
    violated: list[str] = []
    low = diff_text.lower()
    for avoid in memory.avoid_patterns:
        a = avoid.lower()
        if "dependenc" in a and ("import " in low or "require(" in low):
            # presence of a brand-new import is a soft signal only; left lenient
            pass
        if "unrelated" in a:
            pass  # handled by no_unrelated_files structurally
    return violated


def run_checks(
    diff_text: str,
    task: RLTask,
    repo_root: Path | None,
    test_cmd: str = "",
    typecheck_cmd: str = "",
    lint_cmd: str = "",
    memory: MemoryProfile | None = None,
) -> PatchOutcome:
    """Apply `diff_text` in a throwaway copy of `repo_root` and run the checks.

    If `repo_root` is None (no snapshot available) we still report applied=False
    and rely on offline static signals — the reward then reflects the missing
    test signal honestly (tests reward 0, with a note).
    """
    ref_lines = task.reference_patch.count("\n") + 1 if task.reference_patch else 0
    cand_lines = diff_text.count("\n") + 1 if diff_text else 0

    if repo_root is None or not Path(repo_root).is_dir():
        return PatchOutcome(
            applied=False,
            tests_ran=False,
            diff_lines=cand_lines,
            reference_diff_lines=ref_lines,
            violated_preferences=_check_preferences(diff_text, memory),
        )

    with tempfile.TemporaryDirectory(prefix="autopilot_sbx_") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(repo_root, work, dirs_exist_ok=True, symlinks=True)
        if not (work / ".git").exists():
            _run("git init -q && git add -A && git commit -qm base --allow-empty", work, timeout=30)

        applied = _apply_patch(diff_text, work)
        outcome = PatchOutcome(
            applied=applied,
            diff_lines=cand_lines,
            reference_diff_lines=ref_lines,
        )
        if not applied:
            outcome.build_ok = False
            return outcome

        outcome.files_changed = _changed_files(work)

        if typecheck_cmd:
            ok, _ = _run(typecheck_cmd, work)
            outcome.typecheck_passed = ok
            outcome.build_ok = outcome.build_ok and ok
        if lint_cmd:
            ok, _ = _run(lint_cmd, work)
            outcome.lint_passed = ok
        if test_cmd:
            ok, _ = _run(test_cmd, work)
            outcome.tests_ran = True
            outcome.tests_passed = ok
            outcome.build_ok = outcome.build_ok and ok

        for c in task.checks:
            if c.kind == "no_unwanted_dep":
                outcome.added_dependencies = _added_dependencies(
                    work, c.args.get("manifest_globs", [])
                )
        outcome.violated_preferences = _check_preferences(diff_text, memory)
        return outcome
