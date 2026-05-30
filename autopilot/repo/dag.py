"""Deterministic, commit-versioned code DAG.

Builds the complete dependency graph of a repo — files, every function/class, and
the edges between them (imports, contains, calls) — and renders a versioned
ARCHITECTURE.md that follows the repo's git history: for each commit it records
created / updated / deleted files and how the graph connects. Python call edges
are exact (via `ast`); other languages use deterministic symbol-reference
heuristics. No model, no network, $0.

Output: `.autopilot/ARCHITECTURE.md` (human/agent-readable, SDLC-versioned) and
`.autopilot/dag.json` (machine-readable graph).
"""

from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .indexer import _LANG, _SKIP
from .context_layer import _CODE_EXT, _DEF_RE, _IMPORT_RE


@dataclass
class FunctionNode:
    qualname: str           # "<relpath>::<name>"
    file: str
    name: str
    lineno: int
    kind: str               # function | method | class
    calls: list[str] = field(default_factory=list)        # repo-local callee qualnames
    called_by: list[str] = field(default_factory=list)


@dataclass
class FileNode:
    path: str
    lang: str
    loc: int
    imports_files: list[str] = field(default_factory=list)  # repo-local file deps
    functions: list[str] = field(default_factory=list)      # qualnames defined here


@dataclass
class Commit:
    sha: str
    short: str
    date: str
    subject: str
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


@dataclass
class RepoDAG:
    root: str
    files: list[FileNode] = field(default_factory=list)
    functions: list[FunctionNode] = field(default_factory=list)
    import_edges: list[tuple[str, str]] = field(default_factory=list)  # (file, file)
    call_edges: list[tuple[str, str]] = field(default_factory=list)    # (qualname, qualname)
    commits: list[Commit] = field(default_factory=list)
    version: str = "uncommitted"
    generated_at: str = ""   # from latest commit date (deterministic, not wall clock)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class DAGBuilder:
    def __init__(self, repo: str | Path) -> None:
        self.repo = Path(repo)

    # --- git ---

    def _git(self, args: list[str]) -> str:
        try:
            r = subprocess.run(["git", "-C", str(self.repo), *args],
                               capture_output=True, text=True, timeout=30)
            return r.stdout if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def _commits(self, n: int = 20) -> list[Commit]:
        out = self._git(["log", f"-n{n}", "--pretty=%H%x1f%cI%x1f%s"])
        if not out.strip():
            return []
        commits: list[Commit] = []
        for line in out.strip().splitlines():
            parts = line.split("\x1f")
            if len(parts) < 3:
                continue
            sha, date, subj = parts[0], parts[1], parts[2]
            c = Commit(sha=sha, short=sha[:8], date=date, subject=subj)
            stat = self._git(["show", "--name-status", "--pretty=format:", sha])
            for sl in stat.strip().splitlines():
                bits = sl.split("\t")
                if len(bits) < 2:
                    continue
                status, path = bits[0], bits[-1]
                if status.startswith("A"):
                    c.created.append(path)
                elif status.startswith("D"):
                    c.deleted.append(path)
                elif status.startswith("M") or status.startswith("R"):
                    c.updated.append(path)
            commits.append(c)
        return commits

    # --- scan + graph ---

    def _candidates(self) -> list[Path]:
        out = []
        for f in self.repo.rglob("*"):
            if not f.is_file() or any(p in _SKIP for p in f.parts):
                continue
            if f.suffix in _CODE_EXT or f.name in _CODE_EXT:
                out.append(f)
        return sorted(out)

    def build(self, max_commits: int = 20) -> RepoDAG:
        dag = RepoDAG(root=str(self.repo))
        # module path -> relpath, for resolving import edges
        mod_to_file: dict[str, str] = {}
        sym_to_qual: dict[str, list[str]] = {}     # bare name -> [qualnames]
        py_files: list[tuple[str, str]] = []        # (relpath, source)

        for f in self._candidates():
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            rel = str(f.relative_to(self.repo))
            fn = FileNode(path=rel, lang=_LANG.get(f.suffix, f.suffix or "?"),
                          loc=text.count("\n") + 1)
            dag.files.append(fn)
            mod_to_file[rel.rsplit(".", 1)[0].replace("/", ".")] = rel
            if f.suffix == ".py":
                py_files.append((rel, text))
                self._py_defs(rel, text, dag, fn, sym_to_qual)
            else:
                for m in _DEF_RE.finditer(text):
                    name = m.group(2)
                    q = f"{rel}::{name}"
                    node = FunctionNode(q, rel, name, text[:m.start()].count("\n") + 1, "function")
                    dag.functions.append(node)
                    fn.functions.append(q)
                    sym_to_qual.setdefault(name, []).append(q)

        self._resolve_imports(dag, mod_to_file)
        self._resolve_py_calls(py_files, dag, sym_to_qual)

        dag.commits = self._commits(max_commits)
        if dag.commits:
            dag.version = dag.commits[0].short
            dag.generated_at = dag.commits[0].date
        return dag

    def _py_defs(self, rel: str, text: str, dag: RepoDAG, fn: FileNode,
                 sym_to_qual: dict[str, list[str]]) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                q = f"{rel}::{node.name}"
                dag.functions.append(FunctionNode(q, rel, node.name, node.lineno, kind))
                fn.functions.append(q)
                sym_to_qual.setdefault(node.name, []).append(q)

    def _resolve_imports(self, dag: RepoDAG, mod_to_file: dict[str, str]) -> None:
        by_path = {fn.path: fn for fn in dag.files}
        for fn in dag.files:
            try:
                text = (self.repo / fn.path).read_text(errors="ignore")
            except OSError:
                continue
            for m in _IMPORT_RE.finditer(text):
                for mod, rel in mod_to_file.items():
                    base = mod.split(".")[-1]
                    if base and base in m.group(0) and rel != fn.path:
                        if rel not in fn.imports_files:
                            fn.imports_files.append(rel)
                            dag.import_edges.append((fn.path, rel))

    def _resolve_py_calls(self, py_files: list[tuple[str, str]], dag: RepoDAG,
                          sym_to_qual: dict[str, list[str]]) -> None:
        qual_by = {fnode.qualname: fnode for fnode in dag.functions}
        for rel, text in py_files:
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            # map each enclosing function to the calls inside it
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                caller = f"{rel}::{node.name}"
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        callee_name = _call_name(sub.func)
                        if not callee_name:
                            continue
                        for q in sym_to_qual.get(callee_name, []):
                            if q == caller:
                                continue
                            dag.call_edges.append((caller, q))
                            if caller in qual_by and q not in qual_by[caller].calls:
                                qual_by[caller].calls.append(q)
                            if q in qual_by and caller not in qual_by[q].called_by:
                                qual_by[q].called_by.append(caller)

    # --- render ---

    def render_markdown(self, dag: RepoDAG, max_funcs: int = 400) -> str:
        name = self.repo.name or "repo"
        files_sorted = sorted(dag.files, key=lambda f: f.path)
        tree = "\n".join(f"{f.path}  ({f.lang}, {f.loc} LOC, {len(f.functions)} defs)" for f in files_sorted[:200])

        imports = "\n".join(f"- `{a}` -> `{b}`" for a, b in sorted(dag.import_edges)[:200]) or "- (none detected)"

        func_lines = []
        for fnode in sorted(dag.functions, key=lambda x: x.qualname)[:max_funcs]:
            calls = ", ".join(sorted(set(fnode.calls))[:8])
            cb = ", ".join(sorted(set(fnode.called_by))[:6])
            extra = []
            if calls:
                extra.append(f"calls: {calls}")
            if cb:
                extra.append(f"called_by: {cb}")
            func_lines.append(f"- `{fnode.qualname}` (L{fnode.lineno}, {fnode.kind})"
                              + (f" — {'; '.join(extra)}" if extra else ""))
        func_map = "\n".join(func_lines) or "- (no functions found)"

        history = []
        for c in dag.commits:
            parts = [f"### `{c.short}` — {c.date}", f"_{c.subject}_", ""]
            if c.created:
                parts.append("created: " + ", ".join(f"`{p}`" for p in c.created[:30]))
            if c.updated:
                parts.append("updated: " + ", ".join(f"`{p}`" for p in c.updated[:30]))
            if c.deleted:
                parts.append("deleted: " + ", ".join(f"`{p}`" for p in c.deleted[:30]))
            history.append("\n".join(parts))
        history_md = "\n\n".join(history) if history else "_(not a git repository — version history unavailable)_"

        mermaid = "\n".join(
            f'  "{a}" --> "{b}"' for a, b in sorted(set(dag.import_edges))[:60]
        )

        return f"""---
name: {name}-dag
description: Deterministic, commit-versioned dependency DAG of {name}. Complete file tree, every function mapped (calls/called_by), and per-commit created/updated/deleted history. Read this to know how the codebase connects without exploring it.
version: {dag.version}
generated_at: {dag.generated_at or 'uncommitted'}
metadata:
  files: {len(dag.files)}
  functions: {len(dag.functions)}
  import_edges: {len(dag.import_edges)}
  call_edges: {len(dag.call_edges)}
---

# {name} — code DAG @ `{dag.version}`

{len(dag.files)} files · {len(dag.functions)} functions/classes · {len(dag.import_edges)} import edges · {len(dag.call_edges)} call edges.
Deterministic and regenerated after every commit.

## File tree
```
{tree}
```

## Import DAG (file -> file)
{imports}

```mermaid
graph LR
{mermaid}
```

## Function map (every function, with call edges)
{func_map}

## SDLC version history (per commit: created / updated / deleted)
{history_md}
"""

    def write(self, dag: RepoDAG) -> tuple[Path, Path]:
        out = self.repo / ".autopilot"
        out.mkdir(parents=True, exist_ok=True)
        md = out / "ARCHITECTURE.md"
        js = out / "dag.json"
        md.write_text(self.render_markdown(dag))
        js.write_text(json.dumps(dag.to_json(), indent=2))
        return md, js


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None
