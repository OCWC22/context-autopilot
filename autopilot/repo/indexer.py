"""Local repo indexer that maintains a living SKILL.md — at $0.

Runs on-device (deterministic; a local model can enrich prose but isn't
required), so re-indexing the whole codebase on every change costs nothing in
frontier tokens. It produces `.autopilot/SKILL.md`: a structure-aware
architecture map (tree, modules, symbols, dependency edges, detected stack +
commands, conventions) that Claude Code / Opus reads instead of re-discovering
the repo each session. Each index also emits a trace for fine-tuning a personal,
style-aware coding model.

Grounding: GraphCoder (structure over chunks) + Repository Memory (persist what
the repo is) + the SKILL.md progressive-disclosure pattern. See CITATIONS.md.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent.ledger import BASELINE_FRONTIER, cost_usd
from .context_layer import _CODE_EXT, _DEF_RE, _IMPORT_RE

_SKIP = {".git", "node_modules", "__pycache__", "autopilot_out", ".venv", "venv",
         "dist", "build", ".next", ".mypy_cache", ".pytest_cache",
         ".autopilot"}  # exclude our own generated SKILL.md (prevents self-retrigger loop)
_IMPORT_NAME = re.compile(r"(?:from|import)\s+([A-Za-z_][\w\.]*)")


@dataclass
class FileInfo:
    path: str
    lang: str
    loc: int
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


@dataclass
class RepoIndex:
    root: str
    files: list[FileInfo] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    commands: dict[str, str] = field(default_factory=dict)
    conventions: list[str] = field(default_factory=list)
    dep_edges: list[tuple[str, str]] = field(default_factory=list)  # (file, imported-module)
    total_chars: int = 0

    @property
    def n_files(self) -> int:
        return len(self.files)

    @property
    def n_symbols(self) -> int:
        return sum(len(f.symbols) for f in self.files)

    def top_files(self, k: int = 8) -> list[FileInfo]:
        return sorted(self.files, key=lambda f: (len(f.symbols), f.loc), reverse=True)[:k]


_LANG = {".py": "Python", ".ts": "TypeScript", ".tsx": "TSX", ".js": "JavaScript",
         ".jsx": "JSX", ".go": "Go", ".rs": "Rust", ".java": "Java", ".rb": "Ruby",
         ".sql": "SQL", ".md": "Markdown", ".toml": "TOML", ".yml": "YAML", ".yaml": "YAML"}


class RepoIndexer:
    def __init__(self, repo: str | Path) -> None:
        self.repo = Path(repo)

    # --- scan ---

    def _candidates(self) -> list[Path]:
        out = []
        for f in self.repo.rglob("*"):
            if not f.is_file():
                continue
            if any(part in _SKIP for part in f.parts):
                continue
            if f.suffix in _CODE_EXT or f.name in _CODE_EXT:
                out.append(f)
        return out

    def index(self) -> RepoIndex:
        idx = RepoIndex(root=str(self.repo))
        local_modules: set[str] = set()
        for f in self._candidates():
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            rel = str(f.relative_to(self.repo))
            idx.total_chars += len(text)
            syms = [m.group(2) for m in _DEF_RE.finditer(text)][:40]
            imps = []
            for m in _IMPORT_RE.finditer(text):
                nm = _IMPORT_NAME.search(m.group(0))
                if nm:
                    imps.append(nm.group(1))
            fi = FileInfo(path=rel, lang=_LANG.get(f.suffix, f.suffix or "?"),
                          loc=text.count("\n") + 1, symbols=syms, imports=imps[:20])
            idx.files.append(fi)
            local_modules.add(rel.rsplit(".", 1)[0].replace("/", "."))

        # dependency edges: imports that resolve to repo-local modules
        for fi in idx.files:
            for imp in fi.imports:
                base = imp.split(".")[0]
                if any(base in lm.split(".") for lm in local_modules):
                    idx.dep_edges.append((fi.path, imp))

        idx.stack, idx.commands, idx.conventions = self._detect_stack()
        return idx

    def _detect_stack(self) -> tuple[list[str], dict[str, str], list[str]]:
        stack, commands, conventions = [], {}, []
        pyproject = self.repo / "pyproject.toml"
        pkg = self.repo / "package.json"
        if pyproject.exists():
            stack.append("Python")
            t = pyproject.read_text(errors="ignore")
            if "pytest" in t:
                commands["test"] = "pytest -q"
            if "ruff" in t:
                commands["lint"] = "ruff check ."
            if "[project.scripts]" in t:
                conventions.append("CLI entry points declared in pyproject [project.scripts]")
        if pkg.exists():
            stack.append("Node/TypeScript")
            try:
                pj = json.loads(pkg.read_text(errors="ignore"))
                for k, v in (pj.get("scripts") or {}).items():
                    if k in ("test", "lint", "build", "dev", "typecheck"):
                        commands[k] = f"npm run {k}"
                if "next" in json.dumps(pj):
                    conventions.append("Next.js project (app/ or pages/)")
            except json.JSONDecodeError:
                pass
        if (self.repo / "Dockerfile").exists() or list(self.repo.glob("**/Dockerfile")):
            conventions.append("Containerized (Dockerfile present)")
        if (self.repo / ".autopilot").exists():
            conventions.append("autopilot-managed (.autopilot/ present)")
        return stack, commands, conventions

    # --- render the living SKILL.md ---

    def render_skill_md(self, idx: RepoIndex, changed: list[str] | None = None,
                        max_chars: int = 12000) -> str:
        name = self.repo.name or "repo"
        tree = self._tree_lines(idx)
        top = idx.top_files()
        cmd_lines = "\n".join(f"- `{k}`: `{v}`" for k, v in idx.commands.items()) or "- (none detected)"
        conv_lines = "\n".join(f"- {c}" for c in idx.conventions) or "- (none detected)"
        key_lines = "\n".join(
            f"- `{f.path}` ({f.lang}, {f.loc} LOC) — {', '.join(f.symbols[:6]) or 'no top-level symbols'}"
            for f in top
        )
        changed_block = ""
        if changed:
            changed_block = "\n## Recently changed\n" + "\n".join(f"- `{c}`" for c in changed[:20]) + "\n"

        body = f"""---
name: {name}-architecture
description: Live architecture map of {name}. Auto-generated and kept fresh on every code change by the local indexer ($0). Read this before exploring the repo so you already have its structure, key files, symbols, conventions, and commands.
version: auto
metadata:
  generator: autopilot.repo.indexer
  files: {idx.n_files}
  symbols: {idx.n_symbols}
---

# {name} — architecture (auto-indexed)

Stack: {', '.join(idx.stack) or 'mixed'} · {idx.n_files} files · {idx.n_symbols} top-level symbols.
This file is regenerated locally whenever the codebase changes, so you (the
frontier model) already have repo context and don't need to re-discover it.

## Commands
{cmd_lines}

## Conventions
{conv_lines}

## Key files
{key_lines}

## File tree
```
{tree}
```
{changed_block}"""
        return body[:max_chars]

    def _tree_lines(self, idx: RepoIndex, max_lines: int = 80) -> str:
        paths = sorted(f.path for f in idx.files)
        return "\n".join(paths[:max_lines]) + ("" if len(paths) <= max_lines else f"\n… (+{len(paths)-max_lines} more)")

    def write_skill(self, idx: RepoIndex, changed: list[str] | None = None) -> Path:
        out = self.repo / ".autopilot" / "SKILL.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.render_skill_md(idx, changed=changed))
        return out

    # --- trace for fine-tuning a personal, style-aware coding model ---

    def emit_trace(self, idx: RepoIndex, changed: list[str] | None, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        rec = {
            "root": idx.root,
            "changed": changed or [],
            "n_files": idx.n_files,
            "n_symbols": idx.n_symbols,
            "stack": idx.stack,
            "commands": idx.commands,
            # the (architecture-context -> ) signal a personal model learns from
            "architecture_skill": self.render_skill_md(idx, changed=changed, max_chars=4000),
        }
        with (out_dir / "index_traces.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")

    # --- cost framing: local index is $0 vs re-discovering via the frontier ---

    def cost_summary(self, idx: RepoIndex) -> dict[str, Any]:
        # what a frontier model would spend re-reading the repo to (re)learn its
        # architecture each session, vs the $0 local index that produces SKILL.md.
        frontier_tokens = idx.total_chars // 4
        return {
            "local_index_cost_usd": 0.0,
            "frontier_rediscovery_tokens": frontier_tokens,
            "frontier_rediscovery_cost_usd": round(cost_usd(BASELINE_FRONTIER, frontier_tokens, 0), 6),
            "note": "local re-index is $0; the figure is what the frontier would spend re-learning the repo each session if SKILL.md weren't pre-built.",
        }
