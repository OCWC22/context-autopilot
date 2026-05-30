"""Query GLM-5.1 (teacher) via the Z.ai API to generate distillation targets.

Black-box, sequence-level KD: for each task prompt we ask GLM-5.1 (thinking mode
on) for the gold patch + reasoning. Those completions become the student's SFT
targets. Stdlib-only (urllib). Concurrency + cost accounting included.

Set ZAI_API_KEY. Z.ai is OpenAI-compatible at /paas/v4/chat/completions
(RECEIPTS v2: $0.95 / $3.15 per MTok in/out).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import DEFAULT, Config

_SYSTEM = (
    "You are an expert software engineer producing TRAINING DATA for a smaller "
    "coding model. Given a task, repo context, and project memory, produce the "
    "single best change as a unified diff, preceded by a short, concrete "
    "explanation of the approach. Make minimal, type-safe edits; do not touch "
    "unrelated files or add dependencies unless required. Output the explanation, "
    "then the diff in a ```diff code block."
)


@dataclass
class TeacherResult:
    task_id: str
    prompt: str
    completion: str
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


@dataclass
class TeacherRun:
    results: list[TeacherResult] = field(default_factory=list)

    @property
    def ok(self) -> list[TeacherResult]:
        return [r for r in self.results if r.completion and not r.error]

    def cost_usd(self, cfg_in: float, cfg_out: float) -> float:
        tin = sum(r.input_tokens for r in self.results)
        tout = sum(r.output_tokens for r in self.results)
        return round(tin / 1e6 * cfg_in + tout / 1e6 * cfg_out, 4)


def _build_prompt(task: dict[str, Any]) -> str:
    ctx = "\n".join(f"- {c}" for c in (task.get("repo_context", []) + task.get("memory_context", [])))
    body = task.get("prompt", "")
    if ctx:
        body = f"{body}\n\nProject context / memory:\n{ctx}"
    if task.get("reference_patch"):
        body += "\n\n(There is a known-good reference change; produce your best independent solution.)"
    return body


def _call_zai(prompt: str, cfg: Config, timeout: float = 180.0) -> tuple[str, int, int]:
    key = os.environ.get(cfg.distill.teacher_api_key_env, "")
    if not key:
        raise RuntimeError(
            f"{cfg.distill.teacher_api_key_env} not set. Export your Z.ai API key to query GLM-5.1."
        )
    url = cfg.distill.teacher_base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": cfg.distill.teacher_model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": cfg.distill.teacher_max_tokens,
        "temperature": cfg.distill.teacher_temperature,
    }
    if cfg.distill.teacher_thinking:
        payload["thinking"] = {"type": "enabled"}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    text = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {})
    return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def generate(tasks: list[dict[str, Any]], cfg: Config = DEFAULT) -> TeacherRun:
    run = TeacherRun()

    def one(task: dict[str, Any]) -> TeacherResult:
        prompt = _build_prompt(task)
        tid = task.get("id", "")
        try:
            text, tin, tout = _call_zai(prompt, cfg)
            return TeacherResult(tid, prompt, text, tin, tout)
        except (urllib.error.URLError, RuntimeError, KeyError) as e:
            return TeacherResult(tid, prompt, "", error=str(e))

    with ThreadPoolExecutor(max_workers=cfg.distill.teacher_concurrency) as pool:
        futs = [pool.submit(one, t) for t in tasks]
        for f in as_completed(futs):
            run.results.append(f.result())
    return run


def load_tasks(dataset_dir: Path) -> list[dict[str, Any]]:
    """Prefer RL tasks (they carry repo+memory context); fall back to traces."""
    for name in ("rl_train.jsonl", "rl_eval.jsonl", "traces.jsonl"):
        p = dataset_dir / name
        if p.exists():
            rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
            if rows:  # skip empty files, fall through to the next source
                return rows
    return []
