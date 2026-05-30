"""Launch a local OpenAI-compatible server for the distilled student via
`mlx_lm.server` (RECEIPTS.md v2). This is the cheap ($0) sub-LM that the RLM
engineering checks hammer; Claude stays the parent orchestrator only.

Run:
    python -m autopilot.mlx_serve.server --model <fused-or-adapter> --port 8080
or use the printed `mlx_lm.server` command directly. On a 16GB Mac, prefer a 3B
or 7B-4bit student; serving the base + a LoRA adapter avoids re-downloading.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from ..config import DEFAULT


def serve_command(
    model: str,
    host: str,
    port: int,
    adapter_path: str | None = None,
    draft_model: str | None = None,
) -> list[str]:
    cmd = ["mlx_lm.server", "--model", model, "--host", host, "--port", str(port)]
    if adapter_path:
        cmd += ["--adapter-path", adapter_path]
    if draft_model:
        cmd += ["--draft-model", draft_model]  # speculative decoding (perf)
    return cmd


def main(argv: list[str] | None = None) -> int:
    cfg = DEFAULT
    p = argparse.ArgumentParser(description="Serve the distilled student on MLX (OpenAI-compatible).")
    p.add_argument("--model", default=cfg.mlx.fused_path or cfg.mlx.student)
    p.add_argument("--adapter-path", default=None, help="serve base + LoRA adapter instead of a fused model")
    p.add_argument("--host", default=cfg.mlx.serve_host)
    p.add_argument("--port", type=int, default=cfg.mlx.serve_port)
    p.add_argument("--draft-model", default=cfg.mlx.draft_model)
    p.add_argument("--print-only", action="store_true", help="print the command, don't launch")
    args = p.parse_args(argv)

    cmd = serve_command(args.model, args.host, args.port, args.adapter_path, args.draft_model)
    print("$ " + " ".join(cmd))
    if args.print_only:
        return 0
    if shutil.which("mlx_lm.server") is None:
        print(
            "mlx_lm.server not found. Install MLX (Apple Silicon only):\n"
            "  pip install mlx-lm\n"
            "Then re-run, or use --print-only to copy the command.",
            file=sys.stderr,
        )
        return 2
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
