"""Turn GLM-5.1 teacher completions into MLX-LM fine-tuning data.

mlx_lm.lora reads `train.jsonl` / `valid.jsonl` / `test.jsonl` from a data dir.
We emit chat format ({"messages": [...]}), which mlx-lm supports, so the student
learns to map (task + context) -> (teacher explanation + diff). This is the
distillation dataset: GLM-5.1's behavior, captured as sequences.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .teacher_glm import TeacherResult

_STUDENT_SYSTEM = (
    "You are a personal coding model. Follow the project memory. Make minimal, "
    "type-safe diffs; do not touch unrelated files or add dependencies unless "
    "asked. Explain briefly, then give the change as a unified diff."
)


def to_mlx_records(results: Iterable[TeacherResult]) -> list[dict]:
    records: list[dict] = []
    for r in results:
        if not r.completion or r.error:
            continue
        records.append(
            {
                "messages": [
                    {"role": "system", "content": _STUDENT_SYSTEM},
                    {"role": "user", "content": r.prompt},
                    {"role": "assistant", "content": r.completion},
                ]
            }
        )
    return records


def write_mlx_data(records: list[dict], out_dir: Path, valid_frac: float = 0.1, test_frac: float = 0.1) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(records)
    n_test = max(1, int(n * test_frac)) if n >= 10 else 0
    n_valid = max(1, int(n * valid_frac)) if n >= 10 else 0
    test = records[:n_test]
    valid = records[n_test : n_test + n_valid]
    train = records[n_test + n_valid :]

    _write(out_dir / "train.jsonl", train)
    if valid:
        _write(out_dir / "valid.jsonl", valid)
    if test:
        _write(out_dir / "test.jsonl", test)

    return {
        "data_dir": str(out_dir),
        "train": len(train),
        "valid": len(valid),
        "test": len(test),
        "small_data_warning": (
            f"{n} distilled examples — below the comfortable 500-1000 band; expect "
            "style/convention transfer from GLM-5.1, not full capability transfer. "
            "Use lora_layers<=8, batch_size 1, <=2-3 epochs (RECEIPTS v2)."
            if n < 500
            else "dataset size adequate"
        ),
    }


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
