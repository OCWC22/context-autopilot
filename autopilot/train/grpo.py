"""Stage B: verifiable-reward GRPO over the exported coding traces.

This is the reinforcement half of the recipe (RECEIPTS.md cluster 6: accepted
diffs are supervision, *tests are rewards*; rule-based / RLVR + GRPO is
established, peer-reviewed technique, not marketing). Stage A (`sft_lora`)
warms the student on convention/style; Stage B nudges it toward patches that
actually build, type-check, lint, and pass tests inside the sandbox.

Two runnable backends, selected by the `AUTOPILOT_RL_BACKEND` env var:

  - ``trl``  (default): drive `trl.GRPOTrainer` in-process with a Python
    reward function that runs `sandbox.run_checks` + `reward_funcs` per
    completion. Generation is offloaded to a *separate* vLLM server
    (`use_vllm=True`, `vllm_mode="server"`) — that server must run on its own
    GPU(s); see the comment by the `GRPOConfig` below.
  - ``prime``: do not execute training here. Print the exact `prime-rl`
    commands that point the trainer at the `verifiers` environment
    (`autopilot.rewards.verifiers_env`) via the TOML config. prime-rl is the
    right tool for the MoE *target* model, which needs expert parallelism (EP).

Honest framing carried from RECEIPTS.md:
- The tests reward stays BINARY. Pass-rate is a miscalibrated surrogate in
  critic-free RL (cluster 6, arXiv 2605.02944); the scalar here is
  `reward_to_scalar(...)`, which folds the binary tests signal plus
  convention/penalty shaping — never a per-test pass fraction.
- Reward quality is bounded by test coverage (cluster 6 caveat). The sandbox
  runs whatever `test_cmd` the caller supplies; weak/flaky tests silently
  reward wrong code.
- A few hundred diffs buys convention/style adaptation under strong reward
  shaping, not new capability (cluster 5). Keep a held-out eval gate and a
  conservative router downstream.

Heavy deps (`trl`, `transformers`, `datasets`, `torch`) are imported lazily
inside `run_grpo` so that `import autopilot.train.grpo` (and the CLI) never
pulls them. The offline core it leans on (`sandbox.run_checks`,
`reward_funcs.reward_to_scalar`, `verifiers_env`) is stdlib-only.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..config import DEFAULT
from ..rewards import reward_funcs, sandbox, verifiers_env

# The id the `verifiers` / prime-rl tooling uses to load our environment. It is
# the import path of the module exposing `load_environment(...)`.
VERIFIERS_ENV_ID = "autopilot.rewards.verifiers_env"

# Where prime-rl TOML configs live, relative to this package.
_CONFIG_DIR = Path(__file__).resolve().parent / "configs"


def run_grpo(dataset_path: Path, model: str | None = None) -> int:
    """Run Stage B GRPO over ``rl_train.jsonl`` under ``dataset_path``.

    Args:
        dataset_path: directory holding ``rl_train.jsonl`` (and ``memory.json``
            alongside it). Usually ``DEFAULT.paths.dataset``.
        model: HF model id to train. Defaults to ``DEFAULT.models.student``
            (the single-GPU-runnable dense Qwen2.5-Coder-7B-Instruct).

    Returns:
        Process-style exit code: 0 on success, non-zero on failure.

    Backend is chosen by ``AUTOPILOT_RL_BACKEND`` ("trl" default, or "prime").
    """
    model_id = model or DEFAULT.models.student
    backend = os.environ.get("AUTOPILOT_RL_BACKEND", "trl").strip().lower()

    if backend == "prime":
        return _run_prime(dataset_path, model_id)
    if backend == "trl":
        return _run_trl(dataset_path, model_id)

    print(
        f"[grpo] unknown AUTOPILOT_RL_BACKEND={backend!r}; "
        "expected 'trl' (default) or 'prime'.",
        file=sys.stderr,
    )
    return 2


# ---------------------------------------------------------------------------
# TRL backend
# ---------------------------------------------------------------------------


def _build_reward_func(
    dataset_path: Path,
    *,
    repo_root: Path | None,
    test_cmd: str,
    typecheck_cmd: str,
    lint_cmd: str,
):
    """Return a TRL-compatible reward function over (prompts, completions).

    TRL calls ``reward_func(prompts, completions, **kwargs)`` and expects a
    ``list[float]`` of the same length as ``completions``. For each completion
    we recover its RLTask, extract the unified diff, replay it through the
    sandbox, and score it with ``reward_to_scalar`` (binary tests + shaping).

    The RLTask is recovered from TRL's per-sample columns: the dataset rows
    carry the task id (we mirror the column verifiers_env uses, ``answer``,
    plus an ``info`` dict). TRL forwards extra dataset columns as keyword lists.
    """
    memory = verifiers_env._load_memory(dataset_path)
    tasks = {t.id: t for t in verifiers_env._load_tasks(dataset_path)}

    def _task_id_for(index: int, **kwargs) -> str | None:
        # TRL passes through any extra dataset columns as parallel lists.
        answer = kwargs.get("answer")
        if isinstance(answer, list) and index < len(answer):
            val = answer[index]
            if isinstance(val, str):
                return val
        info = kwargs.get("info")
        if isinstance(info, list) and index < len(info):
            item = info[index]
            if isinstance(item, dict) and isinstance(item.get("task_id"), str):
                return item["task_id"]
        return None

    def reward_func(prompts, completions, **kwargs) -> list[float]:
        rewards: list[float] = []
        for i, completion in enumerate(completions):
            task = None
            tid = _task_id_for(i, **kwargs)
            if tid is not None:
                task = tasks.get(tid)
            if task is None:
                # No task => no verifiable signal; give the floor (no credit).
                rewards.append(0.0)
                continue

            diff_text = verifiers_env.extract_diff(completion)
            outcome = sandbox.run_checks(
                diff_text,
                task,
                repo_root,
                test_cmd=test_cmd,
                typecheck_cmd=typecheck_cmd,
                lint_cmd=lint_cmd,
                memory=memory,
            )
            # reward_to_scalar keeps tests BINARY (RECEIPTS.md cluster 6).
            rewards.append(reward_funcs.reward_to_scalar(outcome, task))
        return rewards

    # TRL reads __name__ for logging; make it descriptive.
    reward_func.__name__ = "verifiable_patch_reward"
    return reward_func


def _run_trl(dataset_path: Path, model_id: str) -> int:
    """In-process GRPO via `trl.GRPOTrainer` with a sandbox reward function."""
    try:
        from datasets import load_dataset
        from trl import GRPOConfig, GRPOTrainer
    except ImportError as exc:  # pragma: no cover - exercised only with deps
        print(
            "[grpo] TRL backend needs `trl` + `datasets` "
            f"(import failed: {exc}). Install the training extras, or set "
            "AUTOPILOT_RL_BACKEND=prime for the print-only path.",
            file=sys.stderr,
        )
        return 1

    rl_train = dataset_path / "rl_train.jsonl"
    if not rl_train.exists():
        print(f"[grpo] missing {rl_train}; run `autopilot build` first.", file=sys.stderr)
        return 1

    # Verifiable signals. These are the shell commands the sandbox runs; empty
    # strings mean "skip that check" (reward quality is bounded by coverage —
    # RECEIPTS.md cluster 6). Override via env for a real repo.
    repo_root_env = os.environ.get("AUTOPILOT_REPO_ROOT", "").strip()
    repo_root = Path(repo_root_env) if repo_root_env else None
    test_cmd = os.environ.get("AUTOPILOT_TEST_CMD", "")
    typecheck_cmd = os.environ.get("AUTOPILOT_TYPECHECK_CMD", "")
    lint_cmd = os.environ.get("AUTOPILOT_LINT_CMD", "")

    # Build the prompt dataset. We reuse verifiers_env's prompt rendering so the
    # TRL and prime-rl paths see identical inputs, and carry the task id through
    # so the reward function can recover the RLTask.
    tasks = verifiers_env._load_tasks(dataset_path)

    def _gen():
        for task in tasks:
            yield {
                "prompt": [
                    {"role": "system", "content": verifiers_env.SYSTEM_PROMPT},
                    {"role": "user", "content": verifiers_env._render_user_prompt(task)},
                ],
                "answer": task.id,
                "info": {"task_id": task.id, "task_type": task.task_type},
            }

    from datasets import Dataset  # local import; same dep as load_dataset

    train_ds = Dataset.from_list(list(_gen()))

    reward_func = _build_reward_func(
        dataset_path,
        repo_root=repo_root,
        test_cmd=test_cmd,
        typecheck_cmd=typecheck_cmd,
        lint_cmd=lint_cmd,
    )

    output_dir = DEFAULT.paths.models / "grpo"
    output_dir.mkdir(parents=True, exist_ok=True)

    # NOTE: use_vllm + vllm_mode="server" offloads generation to a *separate*
    # vLLM server that must run on its OWN GPU(s) — co-locating it with the
    # trainer will OOM. Launch it first, on different devices, e.g.:
    #   CUDA_VISIBLE_DEVICES=1 trl vllm-serve --model <model_id>
    # then run this trainer on CUDA_VISIBLE_DEVICES=0.
    cfg = GRPOConfig(
        output_dir=str(output_dir),
        use_vllm=True,
        vllm_mode="server",
        num_generations=DEFAULT.train.grpo_num_generations,
        max_steps=DEFAULT.train.grpo_max_steps,
        beta=DEFAULT.train.grpo_kl_coef,
        max_completion_length=DEFAULT.train.grpo_max_completion_len,
        max_prompt_length=DEFAULT.train.max_seq_len - DEFAULT.train.grpo_max_completion_len,
        logging_steps=1,
        save_strategy="steps",
        save_steps=max(1, DEFAULT.train.grpo_max_steps // 4),
        report_to="none",
    )

    print(
        f"[grpo] TRL GRPO: model={model_id} tasks={len(tasks)} "
        f"num_generations={cfg.num_generations} max_steps={cfg.max_steps} "
        f"beta={cfg.beta} -> {output_dir}",
    )
    print(
        "[grpo] reminder: a vLLM generation server must be running on separate "
        "GPUs, e.g. `trl vllm-serve --model "
        f"{model_id}`.",
    )

    trainer = GRPOTrainer(
        model=model_id,
        reward_funcs=reward_func,
        args=cfg,
        train_dataset=train_ds,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    print(f"[grpo] done; adapter/checkpoints under {output_dir}")
    return 0


# ---------------------------------------------------------------------------
# prime-rl backend (print exact commands; do not fake execution)
# ---------------------------------------------------------------------------


def _run_prime(dataset_path: Path, model_id: str) -> int:
    """Print the exact prime-rl commands; do not execute training here.

    prime-rl is the right tool for the MoE *target* model. GRPO over a
    Mixture-of-Experts coder (Qwen3-Coder-Next, 80B-A3B; RECEIPTS.md cluster 4)
    needs **expert parallelism (EP)** so the experts shard across the 4x80GB
    inference GPUs rather than replicating — without EP the MoE weights will not
    fit and routing collapses. The dense student does not need EP.
    """
    # Pick the template that matches the model. The student is dense (1-2 GPU);
    # the target is MoE and needs the EP/FSDP2 template.
    if model_id == DEFAULT.models.student:
        config = _CONFIG_DIR / "student-7b.toml"
        ep_note = "dense student: no expert parallelism needed (single node, 1-2 GPU)."
    else:
        config = _CONFIG_DIR / "target-coder-next.toml"
        ep_note = (
            "MoE target: expert parallelism (EP) REQUIRED so 80B-A3B experts "
            "shard across 4x80GB (RECEIPTS.md cluster 4); without EP the MoE "
            "weights do not fit and routing collapses."
        )

    rl_train = dataset_path / "rl_train.jsonl"
    print("[grpo] prime-rl backend (print-only). Run these by hand:\n")
    print(f"  # 0. dataset (built by `autopilot build`): {rl_train}")
    print(f"  # verifiers environment id: {VERIFIERS_ENV_ID}")
    print(f"  # model: {model_id}")
    print(f"  # {ep_note}\n")
    print("  # 1. install prime-rl + the autopilot verifiers env into the uv project")
    print("  uv add prime-rl verifiers")
    print(f"  # ensure the env import path resolves: python -c 'import {VERIFIERS_ENV_ID}'\n")
    print("  # 2. launch the GRPO run against the TOML config")
    print(f"  uv run rl --trainer @ {config}")
    print()
    print("  # 3. (target only) prime-rl orchestrates the FSDP2 trainer + the")
    print("  #    vLLM inference workers with EP/TP per the [inference] block in")
    print(f"  #    {config.name}. The inference workers must own their own GPUs.")
    print()
    print(
        "[grpo] note: this path intentionally does not execute training — it "
        "prints the exact commands so the GPU topology stays explicit.",
    )
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage B verifiable-reward GRPO")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT.paths.dataset,
        help="directory holding rl_train.jsonl (default: DEFAULT.paths.dataset)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="HF model id to train (default: DEFAULT.models.student)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    return run_grpo(args.dataset, args.model)


if __name__ == "__main__":
    raise SystemExit(main())
