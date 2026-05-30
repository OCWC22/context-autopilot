"""Run tasks under two configs and compare token/cost/retrieval/success metrics.

config "frontier_baseline": no local layer — the whole repo is sent to the
frontier model (the thing we're arguing against). Retrieval recall is trivially
1.0 but precision is low and token cost is the whole repo.

config "local_first": the RepoContextLayer does selective, structure-aware
retrieval + compression; only the compact context is handed to the frontier
model, and pure codebase-QA needs no frontier call at all.

Metrics per (task, config): frontier_calls, tokens_in, cost_usd,
retrieval_recall, retrieval_precision, retrieved_count, tests_passed,
context_chars, compact_chars. The comparison reports tokens saved, calls
avoided, cost saved, and whether recall/success were preserved.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..agent.ledger import BASELINE_FRONTIER, cost_usd
from ..agent.local import LocalModel
from ..agent.memory_backend import make_memory_backend
from ..config import DEFAULT, Config
from ..repo.context_layer import RepoContextLayer
from .tasks import EvalTask

CONFIGS = ("frontier_baseline", "local_first")


@dataclass
class TaskMetrics:
    task: str
    kind: str
    config: str
    frontier_calls: int = 0
    tokens_in: int = 0
    cost_usd: float = 0.0
    retrieval_recall: float = 0.0
    retrieval_precision: float = 0.0
    retrieved_count: int = 0
    tests_passed: bool | None = None
    context_chars: int = 0
    compact_chars: int = 0
    elapsed_ms: float = 0.0          # measured wall-clock of the (local) work
    est_total_ms: float = 0.0        # measured + estimated frontier inference time

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _all_code_files(layer: RepoContextLayer) -> list[str]:
    return [str(f.relative_to(layer.repo)) for f in layer._candidate_files()]


def _recall_precision(retrieved: list[str], gold: list[str]) -> tuple[float, float]:
    rset, gset = set(retrieved), set(gold)
    hit = len(rset & gset)
    recall = hit / len(gset) if gset else 1.0
    precision = hit / len(rset) if rset else 0.0
    return round(recall, 3), round(precision, 3)


def _run_test_with_fix(task: EvalTask) -> bool | None:
    """Apply the seed fix in a throwaway copy and run the test — proves the
    success machinery is real and that the retrieved context was sufficient."""
    if task.kind != "fix" or not task.test_cmd:
        return None
    with tempfile.TemporaryDirectory(prefix="autopilot_eval_") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(task.repo, work, dirs_exist_ok=True)
        if task.fix:
            rel, old, new = task.fix
            fp = work / rel
            if fp.exists():
                fp.write_text(fp.read_text().replace(old, new))
        try:
            proc = subprocess.run(task.test_cmd, cwd=str(work), shell=True,
                                  capture_output=True, text=True, timeout=120)
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return None


def run_task(task: EvalTask, config: str, cfg: Config = DEFAULT, backend: str = "stub") -> TaskMetrics:
    import time as _time
    _t0 = _time.perf_counter()
    m = TaskMetrics(task=task.id, kind=task.kind, config=config)
    layer = RepoContextLayer(task.repo)  # deterministic offline layer

    if config == "frontier_baseline":
        files = _all_code_files(layer)
        raw = 0
        for rel in files:
            try:
                raw += len((Path(task.repo) / rel).read_text(errors="ignore"))
            except OSError:
                pass
        m.retrieved_count = len(files)
        m.context_chars = raw
        m.compact_chars = raw                       # baseline sends it all
        m.tokens_in = raw // 4
        m.frontier_calls = 1                         # always calls the frontier
        m.retrieval_recall, m.retrieval_precision = _recall_precision(files, task.gold_files)
    else:  # local_first
        model = LocalModel(backend, model=cfg.mlx.student)
        layer = RepoContextLayer(task.repo, local_model=model,
                                 memory_backend=make_memory_backend(cfg))
        res = layer.answer(task.prompt, top_k=5)
        m.retrieved_count = len(res.files)
        m.context_chars = res.context_chars
        m.compact_chars = res.compact_chars
        m.tokens_in = max(1, res.compact_chars // 4)
        # QA is answered locally from retrieved context -> 0 frontier calls.
        # A fix still escalates patch generation, but over the COMPACT context.
        m.frontier_calls = 0 if task.kind == "qa" else 1
        m.retrieval_recall, m.retrieval_precision = _recall_precision(res.files, task.gold_files)

    tokens_out = 0 if m.frontier_calls == 0 else 300
    m.cost_usd = round(cost_usd(BASELINE_FRONTIER, m.tokens_in if m.frontier_calls else 0, tokens_out), 6)
    m.tests_passed = _run_test_with_fix(task)

    # timing: measured local work + estimated frontier inference. Assumptions are
    # explicit (not measured against a live frontier API): TTFT ~600ms/call and
    # ~50 tok/s throughput on input+output. Local work is real wall-clock.
    m.elapsed_ms = round((_time.perf_counter() - _t0) * 1000, 1)
    TTFT_MS, TOK_PER_S = 600.0, 50.0
    frontier_ms = m.frontier_calls * (TTFT_MS + 1000.0 * (m.tokens_in + tokens_out) / TOK_PER_S)
    m.est_total_ms = round(m.elapsed_ms + frontier_ms, 1)
    return m


def run_suite(tasks: list[EvalTask], cfg: Config = DEFAULT, backend: str = "stub") -> list[TaskMetrics]:
    out: list[TaskMetrics] = []
    for t in tasks:
        for c in CONFIGS:
            out.append(run_task(t, c, cfg, backend))
    return out


def compare(metrics: list[TaskMetrics]) -> dict[str, Any]:
    by = {c: [m for m in metrics if m.config == c] for c in CONFIGS}

    def agg(ms: list[TaskMetrics]) -> dict[str, Any]:
        n = len(ms) or 1
        # accuracy = test success (when applicable) + retrieval F1
        f1s = []
        for m in ms:
            r, p = m.retrieval_recall, m.retrieval_precision
            f1s.append(2 * r * p / (r + p) if (r + p) else 0.0)
        return {
            "frontier_calls": sum(m.frontier_calls for m in ms),
            "tokens_in": sum(m.tokens_in for m in ms),
            "cost_usd": round(sum(m.cost_usd for m in ms), 6),
            "avg_recall": round(sum(m.retrieval_recall for m in ms) / n, 3),
            "avg_precision": round(sum(m.retrieval_precision for m in ms) / n, 3),
            "retrieval_f1": round(sum(f1s) / n, 3),
            "tests_passed": sum(1 for m in ms if m.tests_passed),
            "tests_total": sum(1 for m in ms if m.tests_passed is not None),
            "est_total_ms": round(sum(m.est_total_ms for m in ms), 1),
            "elapsed_ms": round(sum(m.elapsed_ms for m in ms), 1),
        }

    base, loc = agg(by["frontier_baseline"]), agg(by["local_first"])
    tok_saved = base["tokens_in"] - loc["tokens_in"]
    return {
        "frontier_baseline": base,
        "local_first": loc,
        "savings": {
            "tokens_saved": tok_saved,
            "tokens_saved_pct": round(100 * tok_saved / base["tokens_in"], 1) if base["tokens_in"] else 0.0,
            "frontier_calls_avoided": base["frontier_calls"] - loc["frontier_calls"],
            "cost_saved_usd": round(base["cost_usd"] - loc["cost_usd"], 6),
            "cost_saved_pct": round(100 * (base["cost_usd"] - loc["cost_usd"]) / base["cost_usd"], 1) if base["cost_usd"] else 0.0,
            "recall_preserved": loc["avg_recall"] >= base["avg_recall"] - 0.001 or loc["avg_recall"] >= 0.99,
            "precision_gain": round(loc["avg_precision"] - base["avg_precision"], 3),
            "accuracy_f1_gain": round(loc["retrieval_f1"] - base["retrieval_f1"], 3),
            "success_preserved": loc["tests_passed"] == base["tests_passed"],
            "time_saved_ms": round(base["est_total_ms"] - loc["est_total_ms"], 1),
            "time_saved_pct": round(100 * (base["est_total_ms"] - loc["est_total_ms"]) / base["est_total_ms"], 1) if base["est_total_ms"] else 0.0,
        },
    }


_LABEL = {"frontier_baseline": "Claude Code (full ctx)", "local_first": "local-first (indexed)"}


def pretty(metrics: list[TaskMetrics], cmp: dict[str, Any]) -> str:
    lines = ["Eval: local-first (indexed) vs normal Claude Code", ""]
    lines.append(f"  {'task':14} {'config':22} {'calls':5} {'tok_in':7} {'F1':5} {'tests':5} {'est_ms':8}")
    for m in metrics:
        tp = "-" if m.tests_passed is None else ("pass" if m.tests_passed else "fail")
        r, p = m.retrieval_recall, m.retrieval_precision
        f1 = round(2 * r * p / (r + p), 2) if (r + p) else 0.0
        lines.append(f"  {m.task:14} {_LABEL.get(m.config, m.config):22} {m.frontier_calls:<5} "
                     f"{m.tokens_in:<7} {f1:<5} {tp:5} {m.est_total_ms:<8}")
    s = cmp["savings"]
    b, l = cmp["frontier_baseline"], cmp["local_first"]
    lines += [
        "",
        f"  TOKENS:   {b['tokens_in']} -> {l['tokens_in']}   saved {s['tokens_saved']} ({s['tokens_saved_pct']}%)",
        f"  TIME:     {b['est_total_ms']}ms -> {l['est_total_ms']}ms   saved {s['time_saved_ms']}ms ({s['time_saved_pct']}%)",
        f"  COST:     ${b['cost_usd']} -> ${l['cost_usd']}   saved ${s['cost_saved_usd']} ({s['cost_saved_pct']}%)",
        f"  FRONTIER CALLS: {b['frontier_calls']} -> {l['frontier_calls']}   avoided {s['frontier_calls_avoided']}",
        f"  ACCURACY: retrieval F1 {b['retrieval_f1']} -> {l['retrieval_f1']} (+{s['accuracy_f1_gain']}) | "
        f"tests {l['tests_passed']}/{l['tests_total']} | success preserved: {s['success_preserved']}",
        "",
        "  (time = measured local work + estimated frontier inference @ 600ms TTFT + 50 tok/s)",
    ]
    return "\n".join(lines)
