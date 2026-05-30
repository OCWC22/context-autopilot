"""End-to-end offline distillation: tasks -> GLM-5.1 teacher completions -> MLX
data -> (print/run) QLoRA + fuse. This is the SEPARATE offline process the user
runs on their Mac; it is not in the inference path.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import DEFAULT, Config
from . import teacher_glm, build_distill_data, mlx_distill


def run_distill(
    dataset_dir: Path,
    cfg: Config = DEFAULT,
    model: str | None = None,
    max_tasks: int | None = None,
    print_only: bool = True,
) -> int:
    tasks = teacher_glm.load_tasks(dataset_dir)
    if not tasks:
        print(f"no tasks found in {dataset_dir} (run `autopilot export && autopilot build` first)")
        return 2
    if max_tasks:
        tasks = tasks[:max_tasks]

    print(f"Querying GLM-5.1 (teacher) for {len(tasks)} tasks via Z.ai ...")
    run = teacher_glm.generate(tasks, cfg)
    ok = run.ok
    print(
        json.dumps(
            {
                "tasks": len(tasks),
                "teacher_ok": len(ok),
                "teacher_errors": len(run.results) - len(ok),
                "est_cost_usd": run.cost_usd(cfg.distill.price_in_per_mtok, cfg.distill.price_out_per_mtok),
                "first_error": next((r.error for r in run.results if r.error), ""),
            },
            indent=2,
        )
    )
    if not ok:
        print("no teacher completions (check ZAI_API_KEY / network); aborting before MLX stage.")
        return 2

    out = Path(cfg.paths.out) / "distill"
    records = build_distill_data.to_mlx_records(ok)
    summary = build_distill_data.write_mlx_data(records, out)
    print(json.dumps(summary, indent=2))

    return mlx_distill.run(out, cfg, model=model, print_only=print_only)
