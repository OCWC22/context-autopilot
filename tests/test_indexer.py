"""Indexer + real-time watcher tests: SKILL.md generation, change detection,
no self-retrigger loop, $0 local cost."""

from __future__ import annotations

import os

from autopilot.evals import seed_eval_repo
from autopilot.repo import RepoIndexer, RepoWatcher


def test_index_writes_skill_md(tmp_path):
    seed_eval_repo(tmp_path)
    repo = tmp_path / "eval_repo"
    idx = RepoIndexer(repo)
    index = idx.index()
    assert index.n_files > 5 and index.n_symbols > 0
    path = idx.write_skill(index)
    md = path.read_text()
    assert md.startswith("---") and "architecture" in md and "## File tree" in md
    assert idx.cost_summary(index)["local_index_cost_usd"] == 0.0


def test_watch_detects_change_and_no_self_retrigger(tmp_path):
    seed_eval_repo(tmp_path)
    repo = tmp_path / "eval_repo"
    w = RepoWatcher(repo)
    w.reindex()                      # initial index writes .autopilot/SKILL.md
    assert w.tick() is None          # writing SKILL.md must NOT count as a change

    (repo / "calc.py").write_text((repo / "calc.py").read_text() + "\ndef sub(a,b):\n    return a-b\n")
    os.utime(repo / "calc.py", None)
    res = w.tick()
    assert res is not None
    assert any(c.endswith("calc.py") for c in res["changed"])
    assert all(".autopilot" not in c for c in res["changed"])   # no self-retrigger
    assert "sub" in (repo / ".autopilot" / "SKILL.md").read_text()
    assert w.tick() is None          # stable again after reindex
