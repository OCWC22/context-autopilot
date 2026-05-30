"""Stage A: LoRA SFT warm-up on the student model (TRL SFTTrainer + PEFT).

This is the supervised warm-up that runs BEFORE Stage B GRPO. It trains a small
LoRA adapter on accepted-diff chat examples exported from the user's local
Claude Code / Codex traces, so the student picks up the user's coding
*conventions* (file layout, naming, preferred libraries, comment style) before
the verifiable-reward RL stage refines behavior.

Honest framing (RECEIPTS.md cluster 5):
- The dataset is ~hundreds of diffs. That budget buys **style / convention
  adaptation, NOT new capability**. We therefore lean on strong regularization
  (small LoRA rank, high dropout, few epochs) and a held-out eval split rather
  than chasing train loss. If the LoRA "learns" something the base model could
  not already do, that is almost certainly overfit, not capability.
- Qwen3-Coder-Next is the configured 80B target (Apache-2.0, 70.6 SWE-Bench
  Verified, RECEIPTS.md cluster 5); the dense single-GPU student
  (Qwen2.5-Coder-7B-Instruct) is the runnable default for this stage.

All heavy dependencies (torch, datasets, trl, peft) are imported lazily inside
`run_sft` so that `import autopilot.cli` never pulls them. The CLI calls
`run_sft` inside a try/except ImportError.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ..config import DEFAULT

logger = logging.getLogger("autopilot.train.sft_lora")

# Sensible default LoRA target modules for Qwen-family decoder blocks: the four
# attention projections plus the three MLP projections.
_QWEN_LORA_TARGETS = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]

# Small-data guard threshold (RECEIPTS.md cluster 5): below this many examples,
# treat the run as pure convention adaptation and cap epochs hard.
_SMALL_DATA_THRESHOLD = 500


def run_sft(dataset_path: Path, model: str | None = None) -> int:
    """Run Stage A LoRA SFT warm-up. Returns 0 on success.

    Args:
        dataset_path: directory containing `sft_train.jsonl` (and optionally
            `sft_eval.jsonl`), each line a chat-format record
            `{"messages": [{role, content}, ...]}` as written by `autopilot build`.
        model: HF model id of the student to warm up. Defaults to
            `DEFAULT.models.student` (Qwen2.5-Coder-7B-Instruct).
    """
    # Lazy heavy imports — keep `import autopilot.cli` free of torch/trl/peft.
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    model_id = model or DEFAULT.models.student
    dataset_path = Path(dataset_path)

    train_file = dataset_path / "sft_train.jsonl"
    eval_file = dataset_path / "sft_eval.jsonl"

    if not train_file.exists():
        logger.error("SFT train file not found: %s", train_file)
        logger.error("Run `autopilot build` first to materialize the dataset.")
        return 1

    logger.info("Loading SFT train split from %s", train_file)
    train_ds = load_dataset("json", data_files=str(train_file), split="train")

    eval_ds = None
    if eval_file.exists():
        logger.info("Loading SFT eval split from %s", eval_file)
        eval_ds = load_dataset("json", data_files=str(eval_file), split="train")
    else:
        logger.warning(
            "No sft_eval.jsonl found at %s — training without a held-out eval. "
            "With only hundreds of diffs a held-out split is the only honest "
            "signal of convention adaptation (RECEIPTS.md cluster 5).",
            eval_file,
        )

    n_train = len(train_ds)
    train_cfg = DEFAULT.train
    epochs = train_cfg.sft_epochs

    # Small-data guard (RECEIPTS.md cluster 5).
    if n_train < _SMALL_DATA_THRESHOLD:
        capped = min(epochs, 2)
        logger.warning(
            "Small dataset: %d < %d examples. This run can only do style / "
            "convention adaptation, NOT new capability. Capping epochs %d -> %d "
            "and relying on strong regularization (LoRA r=%d, dropout=%.2f, "
            "recommended r=8 / high dropout — already the defaults). Trust the "
            "held-out eval, not the train loss.",
            n_train,
            _SMALL_DATA_THRESHOLD,
            epochs,
            capped,
            train_cfg.lora_r,
            train_cfg.lora_dropout,
        )
        epochs = capped

    output_dir = DEFAULT.paths.models / "sft-lora"
    output_dir.mkdir(parents=True, exist_ok=True)

    use_bf16 = bool(getattr(torch.cuda, "is_available", lambda: False)()) and bool(
        getattr(torch.cuda, "is_bf16_supported", lambda: False)()
    )
    logger.info("bf16 %s", "enabled" if use_bf16 else "disabled (no CUDA/bf16 support)")

    lora_config = LoraConfig(
        r=train_cfg.lora_r,
        lora_alpha=train_cfg.lora_alpha,
        lora_dropout=train_cfg.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=_QWEN_LORA_TARGETS,
    )

    sft_config = SFTConfig(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        learning_rate=train_cfg.sft_lr,
        max_seq_length=train_cfg.max_seq_len,
        bf16=use_bf16,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_ds is not None else "no",
        report_to=[],
    )

    logger.info(
        "Starting Stage A LoRA SFT: model=%s, examples=%d, epochs=%d, lr=%.2e, "
        "max_seq_len=%d, output_dir=%s",
        model_id,
        n_train,
        epochs,
        train_cfg.sft_lr,
        train_cfg.max_seq_len,
        output_dir,
    )

    trainer = SFTTrainer(
        model=model_id,
        args=sft_config,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        peft_config=lora_config,
    )

    trainer.train()
    trainer.save_model(str(output_dir))

    logger.info("=" * 64)
    logger.info("Stage A SFT complete.")
    logger.info("  examples trained : %d", n_train)
    logger.info("  base model       : %s", model_id)
    logger.info("  LoRA adapter     : %s", output_dir)
    logger.info(
        "  note: this warm-up yields convention / style adaptation, NOT new "
        "capability (RECEIPTS.md cluster 5). Stage B GRPO refines behavior "
        "against verifiable rewards next."
    )
    logger.info("=" * 64)
    return 0


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="Stage A LoRA SFT warm-up on the student model."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT.paths.dataset,
        help="Directory with sft_train.jsonl / sft_eval.jsonl "
        "(default: DEFAULT.paths.dataset).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Student model id (default: DEFAULT.models.student).",
    )
    args = parser.parse_args()
    return run_sft(dataset_path=args.dataset, model=args.model)


if __name__ == "__main__":
    raise SystemExit(_main())
