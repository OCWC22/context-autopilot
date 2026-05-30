"""Real-time watcher: re-index + regenerate SKILL.md on every codebase change.

Stdlib mtime-poll (no deps), so it runs anywhere at $0. `tick()` does one
change-detection pass (used by tests/CLI single runs); `watch()` loops. On any
change it re-indexes, rewrites `.autopilot/SKILL.md`, and emits a fine-tune
trace — keeping the frontier model's repo context fresh without it lifting a
finger.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from ..config import DEFAULT, Config
from .indexer import RepoIndexer, _SKIP
from ..agent.state_backend import make_state_backend

_CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb",
             ".sql", ".md", ".toml", ".yml", ".yaml"}


def _snapshot(repo: Path) -> dict[str, float]:
    snap: dict[str, float] = {}
    for f in repo.rglob("*"):
        if not f.is_file() or any(p in _SKIP for p in f.parts):
            continue
        if f.suffix in _CODE_EXT:
            try:
                snap[str(f)] = f.stat().st_mtime
            except OSError:
                pass
    return snap


def _diff(old: dict[str, float], new: dict[str, float]) -> list[str]:
    changed = [p for p, m in new.items() if old.get(p) != m]
    changed += [p for p in old if p not in new]  # deletions
    return sorted(set(changed))


class RepoWatcher:
    def __init__(self, repo: str | Path, cfg: Config = DEFAULT, write_skill: bool = True,
                 emit_traces: bool = True) -> None:
        self.repo = Path(repo)
        self.cfg = cfg
        self.indexer = RepoIndexer(self.repo)
        self.write_skill = write_skill
        self.emit_traces = emit_traces
        self._snap = _snapshot(self.repo)
        self.state = make_state_backend(cfg)

    def reindex(self, changed: list[str] | None = None) -> dict:
        idx = self.indexer.index()
        if self.write_skill:
            skill_path = self.indexer.write_skill(idx, changed=changed)
        else:
            skill_path = None
        if self.emit_traces:
            self.indexer.emit_trace(idx, changed, Path(self.cfg.paths.out) / "index_traces")
        cost = self.indexer.cost_summary(idx)
        rel_changed = [str(Path(c).relative_to(self.repo)) if str(c).startswith(str(self.repo)) else c
                       for c in (changed or [])]
        self.state.log_event("index", {"kind": "reindex", "changed": rel_changed[:20],
                                        "n_files": idx.n_files, "n_symbols": idx.n_symbols})
        return {
            "n_files": idx.n_files,
            "n_symbols": idx.n_symbols,
            "stack": idx.stack,
            "changed": rel_changed,
            "skill_md": str(skill_path) if skill_path else None,
            "cost": cost,
        }

    def tick(self) -> dict | None:
        """One change-detection pass. Returns the reindex result if something
        changed since the last tick, else None."""
        new = _snapshot(self.repo)
        changed = _diff(self._snap, new)
        self._snap = new
        if not changed:
            return None
        return self.reindex(changed=changed)

    def watch(self, interval: float = 2.0, max_iterations: int | None = None,
              on_change: Callable[[dict], None] | None = None) -> None:
        # initial full index so SKILL.md exists immediately
        first = self.reindex(changed=None)
        if on_change:
            on_change(first)
        i = 0
        while max_iterations is None or i < max_iterations:
            time.sleep(interval)
            i += 1
            res = self.tick()
            if res and on_change:
                on_change(res)
