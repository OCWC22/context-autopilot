"""Modal app: serve the personal coding model as an OpenAI-compatible vLLM
endpoint, SERVERLESS / scale-to-zero, with per-user LoRA hot-swap, plus a
sandboxed CPU test-runner for RL rollouts / route verification.

Deploy:

    modal deploy autopilot/serve/modal_app.py

Then point any OpenAI client at the printed URL:

    from openai import OpenAI
    client = OpenAI(base_url="https://<workspace>--autopilot-serve.modal.run/v1",
                    api_key="EMPTY")
    client.chat.completions.create(model="Qwen/Qwen2.5-Coder-7B-Instruct", ...)
    # per-user personal model => model="<lora-adapter-name>" once loaded.

Economics honesty (RECEIPTS.md clusters 3, 7):
  * Modal is genuine pay-per-second with $0 while idle, but "turnkey" is only
    true because WE ship and maintain this file (cluster 3) — there is no
    one-flag magic, and cold starts are seconds-to-minutes without weight
    caching.
  * This serves SCALE-TO-ZERO on purpose. An always-on A100-80GB is ~$1,800/mo
    (cluster 7), which costs MORE than the $20-200 flat plan it would replace.
    The only honest savings here accrue against METERED API spend, routed
    conservatively (see autopilot/serve/router.py), not against a subscription.

Why a Volume cache (cluster 3): weights are pulled once into a modal.Volume so
subsequent cold starts read from the cache (seconds) instead of re-downloading
from the Hub (minutes).

LoRA hot-swap (cluster 4): vLLM serves `--enable-lora` adapters addressable by
name in the OpenAI `model` field, with multi-LoRA batching (`--max-loras`) and
runtime load/unload via `/v1/load_lora_adapter`. So each user's personal model
is just another routable model name on the same warm container.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import modal

# Import the offline core's defaults. This is stdlib-only and safe to import at
# module top — it does NOT pull torch/vllm (those live inside the image).
from ..config import DEFAULT

APP_NAME = "autopilot-serve"

# Default served model is the runnable student (single-GPU). See the comment on
# `serve()` for switching to the 80B target across 4x80GB.
SERVED_MODEL = os.environ.get("AUTOPILOT_SERVED_MODEL", DEFAULT.models.student)

# How many distinct LoRA adapters may be batched / resident at once. Each
# adapter is one user's personal model (cluster 4).
MAX_LORAS = int(os.environ.get("AUTOPILOT_MAX_LORAS", "8"))
MAX_LORA_RANK = max(int(DEFAULT.train.lora_r), 16)

VLLM_PORT = 8000

# vLLM version is pinned so the deployed image is reproducible; bump deliberately.
VLLM_VERSION = os.environ.get("AUTOPILOT_VLLM_VERSION", "0.7.3")

app = modal.App(APP_NAME)

# --- Image -----------------------------------------------------------------
# vllm installed here; torch comes in as a vllm dependency. Nothing GPU-heavy is
# imported at module top — it all lives in this image and runs inside the
# container.
vllm_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        f"vllm=={VLLM_VERSION}",
        "huggingface_hub[hf_transfer]",
    )
    # hf_transfer accelerates the one-time weight pull into the Volume.
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "VLLM_USE_V1": "1"})
)

# CPU image for the sandboxed reward runner. The offline core is stdlib-only, so
# this image needs nothing beyond Python + git (for patch/diff tooling) and our
# own package mounted in.
sandbox_image = modal.Image.debian_slim(python_version="3.12").apt_install("git")

# --- Volumes ---------------------------------------------------------------
# Weight cache so cold starts are seconds not minutes (cluster 3).
HF_CACHE = "/root/.cache/huggingface"
hf_cache_vol = modal.Volume.from_name("autopilot-hf-cache", create_if_missing=True)

# Where trained LoRA adapters are published (Stage A / Stage B output). The serve
# container reads adapters from here so a freshly trained personal model can be
# hot-loaded by name without rebuilding the image.
LORA_DIR = "/loras"
lora_vol = modal.Volume.from_name("autopilot-loras", create_if_missing=True)


@app.function(
    image=vllm_image,
    gpu=DEFAULT.serve.gpu,  # "A100-80GB" — student fits comfortably on one GPU.
    # Serverless scale-to-zero economics (cluster 7): min_containers=0 means $0
    # while idle; scaledown_window controls how long a warm container lingers
    # after the last request before it is reclaimed.
    scaledown_window=DEFAULT.serve.scaledown_window_s,  # 120s default
    min_containers=DEFAULT.serve.min_containers,  # 0 => scale to zero
    volumes={HF_CACHE: hf_cache_vol, LORA_DIR: lora_vol},
    timeout=30 * 60,  # generous cold-boot budget for the first weight pull
)
@modal.concurrent(max_inputs=64)  # one warm GPU handles many concurrent requests
@modal.web_server(port=VLLM_PORT, startup_timeout=20 * 60)
def serve() -> None:
    """Subprocess-launch the vLLM OpenAI-compatible server with LoRA hot-swap.

    The personal model for each user is a LoRA adapter (cluster 4): once loaded
    (statically via --lora-modules or at runtime via POST /v1/load_lora_adapter)
    it is addressable by name in the OpenAI `model` field, e.g.
    `model="user-42-personal"`.

    Switching to the 80B target (cluster 4): the student is single-GPU, but
    Qwen3-Coder-Next (80B-A3B) needs 4x80GB in bf16. To serve the target,
    request 4 GPUs on this function (gpu="A100-80GB:4") and add
    `--tensor-parallel-size 4` to the args below (or serve an FP8 quant at
    tp=4). Do NOT do this casually: 4x80GB always-on is well past the ~$1,800/mo
    single-A100 figure (cluster 7), so it only makes sense scale-to-zero for
    bursty, verified, metered-spend-displacing traffic.
    """
    args = [
        "vllm",
        "serve",
        SERVED_MODEL,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--download-dir",
        HF_CACHE,  # land weights in the cached Volume (cluster 3)
        "--served-model-name",
        SERVED_MODEL,
    ]

    if DEFAULT.serve.enable_lora:
        args += [
            "--enable-lora",
            "--max-loras",
            str(MAX_LORAS),  # multi-LoRA batching (cluster 4)
            "--max-lora-rank",
            str(MAX_LORA_RANK),
        ]
        # Statically register any adapters already published to the Volume so
        # they are routable immediately on cold start. Additional adapters can
        # be hot-loaded later via POST /v1/load_lora_adapter without a restart.
        lora_root = Path(LORA_DIR)
        if lora_root.is_dir():
            for adapter in sorted(p for p in lora_root.iterdir() if p.is_dir()):
                args += ["--lora-modules", f"{adapter.name}={adapter}"]

    # For the 80B target, uncomment and request gpu="A100-80GB:4" above:
    # args += ["--tensor-parallel-size", "4"]

    print(f"[autopilot] launching: {' '.join(args)}", flush=True)
    subprocess.Popen(args)


@app.function(
    image=sandbox_image,
    cpu=2.0,
    memory=4096,
    timeout=10 * 60,
    volumes={LORA_DIR: lora_vol},
)
def run_tests(
    task_dict: dict,
    diff_text: str,
    repo_tar_bytes: bytes | None = None,
    test_cmd: str = "",
    typecheck_cmd: str = "",
    lint_cmd: str = "",
    memory_dict: dict | None = None,
) -> dict:
    """Sandboxed reward runner for RL rollouts / route verification.

    Applies `diff_text` against the task's repo in an isolated container copy and
    runs the verifiable checks, reusing the offline core's pure sandbox. This is
    the same oracle Stage B GRPO scores rollouts against and the router uses to
    verify personal output before shipping it.

    Honest reward framing (RECEIPTS.md cluster 6): the tests reward stays BINARY
    upstream in reward_funcs; here we just report whether tests ran and passed —
    pass-rate is a miscalibrated surrogate in critic-free RL, so we never smuggle
    it back in as a continuous score.

    Args:
        task_dict: an RLTask.to_dict() payload (round-trips back via RLTask).
        diff_text: candidate unified-diff patch to evaluate.
        repo_tar_bytes: optional .tar.gz of the repo to extract into a temp dir.
            If omitted, the task's embedded repo_snapshot/checks are used as-is.
        test_cmd / typecheck_cmd / lint_cmd: optional check commands.
        memory_dict: optional MemoryProfile.__dict__ for follows-memory checks.

    Returns:
        a dict with the PatchOutcome fields plus the scalar reward, so the
        caller (trainer / router) does not need the heavy package.
    """
    # Imported inside the function: keeps `import autopilot.cli` light and lets
    # the offline-core (stdlib-only) deps resolve only where they are used.
    import io
    import tarfile
    import tempfile

    from ..rewards.reward_funcs import reward_to_scalar
    from ..rewards.sandbox import run_checks
    from ..types import EvalCheck, MemoryProfile, RLTask

    # RLTask.to_dict() uses asdict(), so `checks` arrives as plain dicts; rebuild
    # them into EvalCheck objects so run_checks can read .kind/.command/.args.
    fields = dict(task_dict)
    fields["checks"] = [EvalCheck(**c) for c in fields.get("checks", [])]
    task = RLTask(**fields)

    memory: MemoryProfile | None = None
    if memory_dict:
        memory = MemoryProfile(**memory_dict)

    repo_root: Path | None = None
    tmp: tempfile.TemporaryDirectory | None = None
    try:
        if repo_tar_bytes:
            tmp = tempfile.TemporaryDirectory(prefix="autopilot-repo-")
            repo_root = Path(tmp.name)
            with tarfile.open(fileobj=io.BytesIO(repo_tar_bytes), mode="r:gz") as tar:
                tar.extractall(repo_root)

        outcome = run_checks(
            diff_text=diff_text,
            task=task,
            repo_root=repo_root,
            test_cmd=test_cmd,
            typecheck_cmd=typecheck_cmd,
            lint_cmd=lint_cmd,
            memory=memory,
        )
        scalar = reward_to_scalar(outcome, task)
        result = dict(outcome.__dict__)
        result["reward"] = scalar
        return result
    finally:
        if tmp is not None:
            tmp.cleanup()


@app.local_entrypoint()
def main() -> None:
    """`modal run autopilot/serve/modal_app.py` smoke-print of the config.

    For real serving use `modal deploy autopilot/serve/modal_app.py`, which
    publishes the @web_server endpoint at a stable HTTPS URL. Then:

        from openai import OpenAI
        client = OpenAI(
            base_url="https://<workspace>--autopilot-serve-serve.modal.run/v1",
            api_key="EMPTY",
        )
        client.chat.completions.create(
            model="Qwen/Qwen2.5-Coder-7B-Instruct",   # base, or a LoRA name
            messages=[{"role": "user", "content": "write a python quicksort"}],
        )
    """
    print(f"app={APP_NAME} model={SERVED_MODEL} gpu={DEFAULT.serve.gpu}")
    print(
        f"enable_lora={DEFAULT.serve.enable_lora} max_loras={MAX_LORAS} "
        f"min_containers={DEFAULT.serve.min_containers} "
        f"scaledown_window_s={DEFAULT.serve.scaledown_window_s}"
    )
    print("deploy: modal deploy autopilot/serve/modal_app.py")
