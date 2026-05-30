"""Run (or print) the MLX QLoRA distillation + fuse on the local student.

On a 16GB Mac the student is a 4-bit Qwen2.5-Coder-3B/7B; passing a quantized
base to `mlx_lm.lora --train` automatically does QLoRA. Memory knobs (RECEIPTS
v2): --num-layers 8 (or 4), --batch-size 1, --grad-checkpoint, --max-seq-len.
Then `mlx_lm.fuse` produces a self-contained model the local server loads.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import DEFAULT, Config


def lora_command(data_dir: Path, cfg: Config, model: str | None = None) -> list[str]:
    m = model or cfg.mlx.student
    return [
        "mlx_lm.lora",
        "--model", m,
        "--train",
        "--data", str(data_dir),
        "--adapter-path", cfg.mlx.adapter_path,
        "--num-layers", str(cfg.mlx.lora_layers),
        "--batch-size", str(cfg.mlx.batch_size),
        "--iters", str(cfg.mlx.iters),
        "--learning-rate", str(cfg.mlx.learning_rate),
        "--max-seq-length", str(cfg.mlx.max_seq_len),
    ] + (["--grad-checkpoint"] if cfg.mlx.grad_checkpoint else [])


def fuse_command(cfg: Config, model: str | None = None) -> list[str]:
    return [
        "mlx_lm.fuse",
        "--model", model or cfg.mlx.student,
        "--adapter-path", cfg.mlx.adapter_path,
        "--save-path", cfg.mlx.fused_path,
    ]


def run(data_dir: Path, cfg: Config = DEFAULT, model: str | None = None, print_only: bool = False) -> int:
    lora = lora_command(data_dir, cfg, model)
    fuse = fuse_command(cfg, model)
    print("# Stage A (distill): QLoRA on the local student")
    print("$ " + " ".join(lora))
    print("# Fuse the adapter into a self-contained model")
    print("$ " + " ".join(fuse))
    if print_only:
        return 0
    if shutil.which("mlx_lm.lora") is None:
        print(
            "\nmlx-lm not found (Apple Silicon only). Install with `pip install mlx-lm`, "
            "or run with --print-only to copy the commands to a Mac.",
            file=sys.stderr,
        )
        return 2
    rc = subprocess.call(lora)
    if rc != 0:
        return rc
    return subprocess.call(fuse)


def main(argv: list[str] | None = None) -> int:
    cfg = DEFAULT
    p = argparse.ArgumentParser(description="MLX QLoRA distillation + fuse on the local student.")
    p.add_argument("--data", default=str(Path(cfg.paths.out) / "distill"))
    p.add_argument("--model", default=cfg.mlx.student)
    p.add_argument("--print-only", action="store_true")
    args = p.parse_args(argv)
    return run(Path(args.data), cfg, model=args.model, print_only=args.print_only)


if __name__ == "__main__":
    raise SystemExit(main())
