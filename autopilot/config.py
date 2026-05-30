"""Central configuration for the autopilot pipeline.

Model choices reflect the locked decision: train a small dense student now
(cheap, RL-able on 1-2 GPUs), with Qwen3-Coder-Next-80B-A3B wired as the
configured target / teacher for the Modal multi-GPU scale run.

Sources baked into the defaults (see RECEIPTS.md):
- Qwen3-Coder-Next: 80B total / 3B active MoE, Apache-2.0 (arXiv 2603.00729).
- Qwen3-Coder-30B-A3B: 30.5B/3.3B MoE, Apache-2.0.
- Reward shape: binary tests-pass primary (CodeRL/RLEF/SWE-RL) + auxiliary
  verifiable signals. Partial/pass-rate rewards need careful credit assignment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class ModelConfig:
    # Runnable default: dense, single-GPU RL-able student.
    student: str = "Qwen/Qwen2.5-Coder-7B-Instruct"
    # Configured target for the Modal multi-GPU scale run (MoE, 4x80GB bf16).
    target: str = "Qwen/Qwen3-Coder-Next"
    # Mid MoE option if you want to exercise the expert-parallel path tractably.
    target_small: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    # Teacher / fallback for hard tasks routed off the personal model.
    teacher: str = "Qwen/Qwen3-Coder-Next"
    fallback: str = "claude-code"  # interactive Claude Code / Codex


@dataclass
class RewardWeights:
    """Multi-component verifiable reward. `tests_pass` is the primary binary
    signal; the rest are auxiliary verifiable shaping terms. Mirrors the demo's
    reward table and the CodeRL/RLEF precedent (RECEIPTS.md cluster 6)."""

    tests_pass: float = 1.0
    typecheck_pass: float = 0.5
    lint_pass: float = 0.3
    minimal_diff: float = 0.2
    follows_memory: float = 0.2
    build_breaks: float = -1.0
    edits_unrelated_files: float = -0.5
    adds_unwanted_dependency: float = -0.5
    violates_preference: float = -0.5


@dataclass
class TrainConfig:
    # Small-dataset reality (RECEIPTS.md cluster 5): ~hundreds of diffs => style/
    # convention adaptation, not new capability. Use strong regularization, few
    # epochs, and a held-out eval. SFT warm-up THEN GRPO (ExecVerify template).
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.1
    sft_epochs: int = 2
    sft_lr: float = 1e-4
    max_seq_len: int = 4096
    # GRPO
    grpo_num_generations: int = 8  # rollouts per prompt
    grpo_max_steps: int = 500
    grpo_kl_coef: float = 0.0
    grpo_max_completion_len: int = 2048


@dataclass
class ServeConfig:
    # Serverless scale-to-zero is the ONLY config where solo-volume economics
    # work (RECEIPTS.md cluster 7): pay per-second, $0 idle. Always-on A100
    # (~$1800/mo) costs more than the flat plan it would replace.
    provider: str = "modal"
    gpu: str = "A100-80GB"  # student fits comfortably; target needs 4x for bf16
    engine: str = "vllm"
    scaledown_window_s: int = 120  # tune 2s-20min; lower = cheaper, more cold starts
    min_containers: int = 0  # scale to zero
    enable_lora: bool = True  # per-user personal models as hot-swappable LoRA


@dataclass
class RiskPolicy:
    """Task types that may route to the personal model vs must stay on fallback.
    Code generation is the worst routing case in the literature (~22% savings,
    classifiers keep most coding on frontier models) — so default conservative."""

    personal_ok: tuple[str, ...] = (
        "react_ui_edit",
        "typescript_fix",
        "test_generation",
        "api_scaffold",
    )
    always_fallback: tuple[str, ...] = (
        "schema_migration",
        "architecture_refactor",
        "production_bug",
        "security_change",
    )
    min_eval_pass_rate: float = 0.85  # gate before a task type may route


@dataclass
class Paths:
    root: Path = field(default_factory=lambda: Path.cwd())
    # Where the exporter reads from (the user's own local installs).
    claude_home: Path = field(
        default_factory=lambda: Path(os.path.expanduser("~/.claude"))
    )
    codex_home: Path = field(
        default_factory=lambda: Path(os.path.expanduser("~/.codex"))
    )

    @property
    def out(self) -> Path:
        return self.root / "autopilot_out"

    @property
    def dataset(self) -> Path:
        return self.out / "dataset"

    @property
    def models(self) -> Path:
        return self.out / "models"


@dataclass
class DistillConfig:
    """Offline GLM-5.1 -> MLX-student distillation (a SEPARATE offline process).

    GLM-5.1 (zai-org/GLM-5.1, MIT, 754B-MoE/40B-active, SWE-Bench Pro 58.4) needs
    256GB+ even quantized, so it can't run on the Mac. We use it as a TEACHER via
    the Z.ai API (black-box) — which means black-box, sequence-level KD (teacher
    generates gold patches + reasoning; the student SFT-learns them). White-box
    logit / on-policy OPD is NOT available through an API. See RECEIPTS.md v2.
    """

    teacher_model: str = "glm-5.1"
    teacher_base_url: str = "https://api.z.ai/api/paas/v4"
    teacher_api_key_env: str = "ZAI_API_KEY"
    teacher_thinking: bool = True  # GLM-5.1 thinking mode -> richer reasoning traces
    teacher_max_tokens: int = 4096
    teacher_temperature: float = 0.7
    teacher_concurrency: int = 4
    # Z.ai list price (RECEIPTS v2): $0.95 / $3.15 per MTok in/out.
    price_in_per_mtok: float = 0.95
    price_out_per_mtok: float = 3.15


@dataclass
class MLXConfig:
    """Local Apple-Silicon student via mlx-lm. Tuned for a 16GB Mac (RECEIPTS v2):
    a 3B or 7B-4bit student fits (~4.5GB + KV); 30B-A3B (~33GB) does NOT."""

    # Student that fits 16GB. 3B is the safe default; 7B-4bit also fits but tighter.
    student: str = "mlx-community/Qwen2.5-Coder-3B-Instruct-4bit"
    student_7b: str = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
    adapter_path: str = "autopilot_out/mlx/adapters"
    fused_path: str = "autopilot_out/mlx/fused"
    # mlx_lm.lora memory knobs for 16GB (QLoRA is automatic on a 4-bit base):
    lora_layers: int = 8       # fewer layers = less backprop memory (try 4 on 8GB)
    batch_size: int = 1        # 1 fits 16GB comfortably; 2 if headroom
    iters: int = 600           # ~3 epochs on a few hundred examples
    learning_rate: float = 1e-4
    grad_checkpoint: bool = True
    max_seq_len: int = 2048
    # local OpenAI-compatible server (mlx_lm.server)
    serve_host: str = "127.0.0.1"
    serve_port: int = 8080
    # speculative decoding draft model (optional perf win on Mac)
    draft_model: str | None = None


@dataclass
class ChecksConfig:
    """Multi-subagent engineering-review workflow. Each subagent owns one check
    and uses RLM (depth=1) to externalize long context and return compact
    evidence. The RLM sub-LM is the LOCAL MLX model ($0); Claude is the parent
    orchestrator only. RLM depth>=2 is banned (overthinks / latency explodes —
    RECEIPTS v2, arXiv 2603.02615)."""

    checks: tuple[str, ...] = (
        "cicd",
        "security",
        "code_quality",
        "test_execution",
        "dependency_analysis",
        "deployment_validation",
    )
    rlm_depth: int = 1            # HARD cap; 2+ degrades (RECEIPTS v2)
    rlm_chunk_chars: int = 6000   # context slice size for sub-LM map
    rlm_max_subcalls: int = 24    # stopping mechanism (prevents runaway recursion)
    use_rlm_mcp: bool = True      # prefer the mcp__rlm__* runtime when available
    sub_lm: str = "mlx"           # "mlx" (local, cheap) | "stub" (offline test)
    evidence_char_budget: int = 1200  # compact evidence returned to the parent


@dataclass
class SponsorsConfig:
    """Hackathon sponsor backends. Both are optional and auto-selected when their
    env keys are present; otherwise local offline backends are used.

    Butterbase (https://docs.butterbase.ai) — agent database/state layer: Postgres
    + auto REST Data API + KV. We use the REST Data API for the event log, run
    records, and key/value agent state.

    EverMind / EverOS (https://docs.evermind.ai; the user's "Revermind") —
    long-context memory: add/flush/search returns compact episode summaries +
    profile (not raw logs), which is the same compact-context principle as RLM.
    """

    # Butterbase (state / DB)
    butterbase_base_url: str = "https://api.butterbase.ai"
    butterbase_app_id_env: str = "BUTTERBASE_APP_ID"
    butterbase_api_key_env: str = "BUTTERBASE_API_KEY"   # bb_sk_...
    butterbase_events_table: str = "agent_events"
    butterbase_runs_table: str = "agent_runs"
    butterbase_state_table: str = "agent_state"

    # EverMind / EverOS (long-context memory) — aka "Revermind"
    evermind_base_url: str = "https://api.evermind.ai"
    evermind_api_key_env: str = "EVEROS_API_KEY"          # also checks EVERMIND_API_KEY
    evermind_user_id: str = "autopilot"
    evermind_method: str = "hybrid"                        # keyword|vector|hybrid|agentic
    evermind_top_k: int = 8


@dataclass
class Config:
    models: ModelConfig = field(default_factory=ModelConfig)
    reward: RewardWeights = field(default_factory=RewardWeights)
    train: TrainConfig = field(default_factory=TrainConfig)
    serve: ServeConfig = field(default_factory=ServeConfig)
    risk: RiskPolicy = field(default_factory=RiskPolicy)
    paths: Paths = field(default_factory=Paths)
    distill: DistillConfig = field(default_factory=DistillConfig)
    mlx: MLXConfig = field(default_factory=MLXConfig)
    checks: ChecksConfig = field(default_factory=ChecksConfig)
    sponsors: SponsorsConfig = field(default_factory=SponsorsConfig)

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT = Config()
