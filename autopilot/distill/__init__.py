"""Offline GLM-5.1 -> MLX-student distillation (a SEPARATE offline process).

GLM-5.1 (zai-org/GLM-5.1, MIT, 754B-MoE/40B-active) is the TEACHER, queried via
the Z.ai API (black-box). It generates gold patches + reasoning for our tasks;
the local student (Qwen2.5-Coder 3B/7B-4bit) SFT-learns them via mlx-lm QLoRA on
the Mac. This is black-box, sequence-level KD — white-box logit / on-policy OPD
needs the teacher's weights, which a 754B model over an API does not give us.
See RECEIPTS.md v2 (clusters: GLM-5.1, MLX, distillation).
"""
