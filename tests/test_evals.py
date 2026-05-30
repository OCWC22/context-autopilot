"""Eval-harness tests: local_first must cut tokens + avoid frontier calls while
preserving retrieval recall and task success."""

from __future__ import annotations

from autopilot.evals import bundled_tasks, run_suite, compare


def test_local_first_saves_tokens_and_preserves_success(tmp_path):
    tasks = bundled_tasks(tmp_path)
    metrics = run_suite(tasks, backend="stub")
    cmp = compare(metrics)
    s = cmp["savings"]
    # the core product claims:
    assert s["tokens_saved_pct"] > 80          # big token reduction on a realistic repo
    assert s["frontier_calls_avoided"] >= 1     # QA answered locally, no frontier call
    assert s["recall_preserved"] is True        # still found the gold files
    assert s["success_preserved"] is True       # tests still pass
    assert cmp["local_first"]["avg_precision"] > cmp["frontier_baseline"]["avg_precision"]


def test_retrieval_finds_gold_files(tmp_path):
    tasks = bundled_tasks(tmp_path)
    metrics = run_suite(tasks, backend="stub")
    loc = [m for m in metrics if m.config == "local_first"]
    # every local_first task achieves full recall of its gold files
    assert all(m.retrieval_recall >= 0.99 for m in loc)
    # and retrieves far fewer files than the whole repo
    base = [m for m in metrics if m.config == "frontier_baseline"]
    assert max(m.retrieved_count for m in loc) < min(m.retrieved_count for m in base)
