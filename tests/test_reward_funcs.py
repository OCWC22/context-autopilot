"""Tests for the pure reward functions (RECEIPTS.md cluster 6).

These exercise ``autopilot.rewards.reward_funcs`` with the real ``RewardWeights``
defaults from ``autopilot.config``. They are deliberately stdlib-only: the reward
core is a verifiable, learned-model-free oracle, so it must be testable with no
heavy ML deps installed.

Two honest-framing invariants are asserted directly:
- the tests reward is BINARY (cluster 6: pass-rate is a miscalibrated surrogate
  in critic-free RL), so it contributes exactly 0 or its full weight; and
- when no test command ran, the breakdown carries a note about the missing
  test signal and the tests term is 0.
"""

from __future__ import annotations

import pytest

from autopilot.config import DEFAULT, RewardWeights
from autopilot.rewards.reward_funcs import (
    PatchOutcome,
    compute_reward,
    reward_to_scalar,
)
from autopilot.types import EvalCheck, RLTask


def _task(allowed_files: list[str] | None = None) -> RLTask:
    """A minimal task. If allowed_files is given, attach a no_unrelated_files
    check so the unrelated-files penalty has an allow-list to compare against."""
    checks: list[EvalCheck] = []
    if allowed_files is not None:
        checks.append(
            EvalCheck(
                kind="no_unrelated_files",
                args={"allowed_files": list(allowed_files)},
            )
        )
    return RLTask(
        id="t-reward-1",
        prompt="fix the bug in src/app.py",
        task_type="other",
        risk_level="low",
        checks=checks,
    )


def _good_outcome() -> PatchOutcome:
    """A fully-passing patch: applied, build ok, tests+typecheck+lint pass,
    minimal diff (well under the 60-line bare threshold), only the allowed file
    changed, no added deps, no violated preferences."""
    return PatchOutcome(
        applied=True,
        build_ok=True,
        tests_passed=True,
        tests_ran=True,
        typecheck_passed=True,
        lint_passed=True,
        files_changed=["src/app.py"],
        added_dependencies=[],
        diff_lines=12,
        reference_diff_lines=10,
        violated_preferences=[],
    )


def test_fully_passing_outcome_scores_max_and_tests_pass_true() -> None:
    task = _task(allowed_files=["src/app.py"])
    breakdown = compute_reward(_good_outcome(), task)

    # 1.0 tests + 0.5 typecheck + 0.3 lint + 0.2 minimal_diff + 0.2 follows_memory
    # = 2.2, with no penalties firing.
    assert breakdown.total == pytest.approx(2.2)
    assert breakdown.tests_pass is True
    assert breakdown.components["tests_pass"] == pytest.approx(1.0)
    assert breakdown.components["build_breaks"] == pytest.approx(0.0)
    assert breakdown.components["edits_unrelated_files"] == pytest.approx(0.0)
    # The convenience scalar agrees with the breakdown total.
    assert reward_to_scalar(_good_outcome(), task) == pytest.approx(2.2)


def test_build_breaking_outcome_is_negative_and_worse_than_good() -> None:
    task = _task(allowed_files=["src/app.py"])
    good = compute_reward(_good_outcome(), task).total

    broken = PatchOutcome(
        applied=True,
        build_ok=False,
        tests_passed=False,
        tests_ran=True,
        typecheck_passed=False,
        lint_passed=False,
        files_changed=["src/app.py"],
        diff_lines=12,
        reference_diff_lines=10,
    )
    bad = compute_reward(broken, task)

    # build_breaks weight is -1.0; with no positive terms surviving, total is < 0.
    assert bad.total < 0.0
    assert bad.total < good
    assert bad.tests_pass is False
    assert bad.components["build_breaks"] == pytest.approx(DEFAULT.reward.build_breaks)
    assert "patch broke the build" in bad.notes


def test_unwanted_dependency_reduces_score() -> None:
    task = _task(allowed_files=["src/app.py"])
    baseline = compute_reward(_good_outcome(), task).total

    with_dep = _good_outcome()
    with_dep.added_dependencies = ["left-pad"]
    scored = compute_reward(with_dep, task)

    assert scored.total < baseline
    # adds_unwanted_dependency default weight is -0.5.
    assert scored.components["adds_unwanted_dependency"] == pytest.approx(
        DEFAULT.reward.adds_unwanted_dependency
    )
    assert scored.total == pytest.approx(baseline + DEFAULT.reward.adds_unwanted_dependency)


def test_editing_unrelated_files_reduces_score() -> None:
    task = _task(allowed_files=["src/app.py"])
    baseline = compute_reward(_good_outcome(), task).total

    sprawl = _good_outcome()
    sprawl.files_changed = ["src/app.py", "src/unrelated_module.py"]
    scored = compute_reward(sprawl, task)

    assert scored.total < baseline
    # edits_unrelated_files default weight is -0.5.
    assert scored.components["edits_unrelated_files"] == pytest.approx(
        DEFAULT.reward.edits_unrelated_files
    )


def test_missing_test_signal_contributes_zero_and_adds_note() -> None:
    task = _task(allowed_files=["src/app.py"])

    no_test_signal = _good_outcome()
    no_test_signal.tests_ran = False
    no_test_signal.tests_passed = False
    scored = compute_reward(no_test_signal, task)

    # Tests reward is binary and gated on tests_ran: contributes exactly 0.
    assert scored.components["tests_pass"] == pytest.approx(0.0)
    assert scored.tests_pass is False
    assert any("no test command available" in n for n in scored.notes)
    # Everything else (typecheck/lint/minimal_diff/follows_memory) still scores:
    # 0.5 + 0.3 + 0.2 + 0.2 = 1.2.
    assert scored.total == pytest.approx(1.2)


def test_weights_default_matches_config_default() -> None:
    # The reward core's internal default must equal the shipped config weights,
    # otherwise tests that pass weights=None would drift from production.
    explicit = compute_reward(_good_outcome(), _task(["src/app.py"]), weights=RewardWeights())
    implicit = compute_reward(_good_outcome(), _task(["src/app.py"]))
    assert explicit.total == pytest.approx(implicit.total)
    assert RewardWeights() == DEFAULT.reward
